"""
LLM-based OCR Agent for extracting text from identity documents.
"""

import base64
import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# OCR System Prompt
OCR_SYSTEM_PROMPT = """You are an expert OCR specialist for identity document verification.

Extract ALL text and data from the provided identity document image.

## Document Types
Identify the document type:
- id_card: National ID, Aadhaar, NRIC, etc.
- passport: Any country passport
- visa: Work permit, employment pass, visa sticker/card
- drivers_license: Driving license

## Required Fields
Extract these fields (use "UNREADABLE" if not visible):

For ALL documents:
- document_type: id_card, passport, visa, or drivers_license
- first_name, last_name, full_name
- date_of_birth: Format as YYYY-MM-DD
- nationality: Full country name (e.g., "INDIAN", "SINGAPORE", "UNITED STATES", not abbreviations like "IND", "SG", "US")
- issue_date, expiry_date: Format as YYYY-MM-DD
- gender: M, F, or as shown

For ID cards:
- id_card_number: The ID card number
- address: Full address if visible

For Passports:
- passport_number: The passport number
- place_of_birth

For Driver's License:
- license_number: The license number

For Visas/Work Permits:
- visa_number: The VISA STICKER NUMBER - this is the unique visa identifier, usually:
  * Printed in a corner (often top-right) OUTSIDE the form fields
  * Alphanumeric format like "CJ*******", "V123456", or similar
  * DIFFERENT from the passport/travel document number
  * Do NOT confuse with "Travel Document No." which is the passport number
- passport_number: The "Travel Document No." field - this is the holder's PASSPORT number (NOT the visa number)
- visa_type: Employment Pass, Work Permit, S Pass, Double Journey, Tourist Visa, etc.
- period_of_stay: Duration or type of stay
- remarks: Any remarks or conditions
- employer: Company name (if shown)
- occupation: Job title (if shown)

IMPORTANT: Use document-specific ID fields (passport_number, visa_number, id_card_number, license_number) 
instead of generic document_number. This prevents data loss when merging multiple documents.

## Output Format
Return valid JSON with document-specific ID field:

For Passport:
{
    "document_type": "passport",
    "passport_number": "J*******",
    "first_name": "...", "last_name": "...", "full_name": "...",
    "date_of_birth": "YYYY-MM-DD", "nationality": "...", "gender": "M/F",
    "issue_date": "YYYY-MM-DD", "expiry_date": "YYYY-MM-DD",
    "place_of_birth": "..."
}

For Visa:
{
    "document_type": "visa",
    "visa_number": "CJ*******",  // The visa sticker number (often in corner, NOT Travel Document No.)
    "passport_number": "J*******",  // The Travel Document No. field (holder's passport number)
    "first_name": "...", "last_name": "...", "full_name": "...",
    "date_of_birth": "YYYY-MM-DD", "nationality": "...", "gender": "M/F",
    "issue_date": "YYYY-MM-DD", "expiry_date": "YYYY-MM-DD",
    "visa_type": "...", "period_of_stay": "...", "remarks": "..."
}

For ID Card:
{
    "document_type": "id_card",
    "id_card_number": "ID1234567",
    "first_name": "...", "last_name": "...", "full_name": "...",
    "date_of_birth": "YYYY-MM-DD", "nationality": "...", "gender": "M/F",
    "address": "..."
}

If NOT a valid identity document: {"error": "Not a valid identity document"}

Be thorough and accurate. This data is used for identity verification.
"""


def encode_image_to_base64(file_path: str) -> str:
    """Encode a local image file to base64."""
    with open(file_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def get_image_mime_type(file_path: str) -> str:
    """Determine MIME type from file extension.
    
    Note: Only image formats supported by Bedrock vision API are included.
    PDF is not supported.
    """
    ext = Path(file_path).suffix.lower()
    mime_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return mime_types.get(ext, "image/jpeg")


def extract_document_data_with_vision(file_path: str, document_type: str = "id_card") -> dict:
    """
    Extract data from an identity document using LLM vision capabilities.
    
    Args:
        file_path: Path to the document image
        document_type: Type of document (id_card, passport)
        
    Returns:
        dict: Extracted document data or error
    """
    import boto3
    
    logger.info(f"[OCR Agent] Processing document: {file_path}")
    
    try:
        # Check if file exists
        path = Path(file_path)
        if not path.exists():
            return {
                "success": False,
                "error": f"Document file not found: {file_path}",
            }
        
        # Encode image to base64
        base64_image = encode_image_to_base64(file_path)
        mime_type = get_image_mime_type(file_path)
        
        # Validate supported image formats for Bedrock vision API
        # Bedrock only supports: jpeg, png, gif, webp
        supported_formats = ["image/jpeg", "image/png", "image/gif", "image/webp"]
        if mime_type not in supported_formats:
            return {
                "success": False,
                "error": f"Unsupported file format: {mime_type}. Bedrock vision API only supports JPEG, PNG, GIF, and WebP images. PDF files are not supported.",
            }
        
        # Use boto3 bedrock-runtime directly for vision
        client = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
        )
        
        # Build the vision message for Claude using boto3 converse API format
        # See: https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference-examples.html
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "text": f"Please extract all text and data from this {document_type} document and return it in structured JSON format as specified in your instructions."
                    },
                    {
                        "image": {
                            "format": mime_type.split("/")[1],  # "png", "jpeg", etc.
                            "source": {
                                "bytes": base64.b64decode(base64_image),
                            }
                        }
                    }
                ]
            }
        ]
        
        # Call Claude with vision
        response = client.converse(
            modelId=settings.model_id,
            messages=messages,
            system=[{"text": OCR_SYSTEM_PROMPT}],
            inferenceConfig={"temperature": 0.1},
        )
        
        # Extract text from response
        extracted_text = ""
        if response.get("output") and response["output"].get("message"):
            content = response["output"]["message"].get("content", [])
            for block in content:
                if block.get("text"):
                    extracted_text += block["text"]
        
        logger.info(f"[OCR Agent] Extraction complete. Response length: {len(extracted_text)}")
        
        # Try to parse JSON from response
        import json
        try:
            # Find JSON in the response
            json_start = extracted_text.find("{")
            json_end = extracted_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = extracted_text[json_start:json_end]
                extracted_data = json.loads(json_str)
                return {
                    "success": True,
                    "extracted_data": extracted_data,
                    "raw_text": extracted_text,
                    "document_type": document_type,
                    "file_path": file_path,
                }
        except json.JSONDecodeError:
            pass
        
        # If JSON parsing fails, return raw text
        return {
            "success": True,
            "extracted_data": None,
            "raw_text": extracted_text,
            "document_type": document_type,
            "file_path": file_path,
            "parse_error": "Could not parse structured data from OCR result",
        }
        
    except Exception as e:
        logger.error(f"[OCR Agent] Error: {e}")
        return {
            "success": False,
            "error": str(e),
            "file_path": file_path,
        }


# For mock testing when we don't have real images
def extract_document_data_mock(file_path: str, original_filename: str, doc_type_hint: str | None = None) -> dict:
    """
    Mock OCR extraction based on filename keywords or document type hint.
    Used for testing without real document images.
    
    Args:
        file_path: Path to the document
        original_filename: Original filename (used for mock data selection)
        doc_type_hint: Optional document type hint from frontend (e.g., "visa", "live_photo")
        
    Returns:
        dict: Mock extracted data based on filename keywords or doc_type_hint
    """
    logger.info(f"[OCR Agent Mock] Processing: {original_filename}, type hint: {doc_type_hint}")
    
    filename_lower = original_filename.lower()
    
    # Use doc_type_hint as primary source if provided (from frontend)
    # This allows proper identification even when filename doesn't contain type keywords
    effective_type = None
    if doc_type_hint:
        effective_type = doc_type_hint.lower()
    
    # Detect document type from filename OR doc_type_hint
    if effective_type == "visa" or "visa" in filename_lower or "work_permit" in filename_lower or "workpermit" in filename_lower:
        # Visa/Work Permit document - use visa_number, not document_number
        extracted_data = {
            "document_type": "visa",
            "visa_number": "CJ3760864",
            "visa_type": "DOUBLE JOURNEY",
            "first_name": "ANAND",
            "last_name": "KUMAR",
            "full_name": "ANAND KUMAR",
            "passport_number": "J8365854",
            "date_of_birth": "1985-05-24",
            "nationality": "INDIAN",  # Use full country name for consistency
            "gender": "M",
            "issue_date": "2025-01-01",
            "expiry_date": "2027-01-01",
            "period_of_stay": "SHORT VISIT",
            "remarks": "Not Valid for Employment",
        }
        
    elif effective_type == "live_photo" or "selfie" in filename_lower or "live_photo" in filename_lower:
        # Live photo / selfie - minimal data
        extracted_data = {
            "document_type": "live_photo",
            "verification_type": "selfie",
            "face_detected": True,
            "liveness_check": "passed",
        }
        
    elif effective_type == "passport" or "passport" in filename_lower:
        # Passport document - use passport_number, not document_number
        extracted_data = {
            "document_type": "passport",
            "passport_number": "J8365854",
            "first_name": "ANAND",
            "last_name": "KUMAR",
            "full_name": "ANAND KUMAR",
            "date_of_birth": "1985-05-24",
            "nationality": "INDIAN",
            "issue_date": "2016-01-01",
            "expiry_date": "2026-01-01",
            "place_of_birth": "MUMBAI, MAHARASHTRA",
            "gender": "M",
        }
        
        # Indian passport for testing non-local flow
        if "indian" in filename_lower or "india" in filename_lower or "raj" in filename_lower or "-in" in filename_lower or "_in" in filename_lower:
            extracted_data.update({
                "passport_number": "J8365854",
                "first_name": "ANAND",
                "last_name": "KUMAR",
                "full_name": "ANAND KUMAR",
                "date_of_birth": "1985-05-24",
                "nationality": "INDIAN",
                "place_of_birth": "MUMBAI, MAHARASHTRA",
            })
        elif "jane" in filename_lower:
            extracted_data.update({
                "passport_number": "P987654321",
                "first_name": "Jane",
                "last_name": "Smith",
                "full_name": "Jane Smith",
                "date_of_birth": "1990-03-22",
                "nationality": "US",
            })
    else:
        # Default: ID card - use id_card_number, not document_number
        extracted_data = {
            "document_type": "id_card",
            "id_card_number": "S1234567A",
            "first_name": "Test",
            "last_name": "User",
            "full_name": "Test User",
            "date_of_birth": "1990-01-01",
            "address": "100 Test Street, Test City, TC 12345",
            "issue_date": "2024-01-01",
            "expiry_date": "2034-01-01",
            "nationality": "SINGAPORE",
        }
        
        # Check for specific test cases
        if "john" in filename_lower or "success" in filename_lower:
            extracted_data.update({
                "id_card_number": "S9876543B",
                "first_name": "John",
                "last_name": "Doe",
                "full_name": "John Doe",
                "date_of_birth": "1985-06-15",
                "address": "123 Main St, Singapore 123456",
                "nationality": "SINGAPORE",
            })
        elif "alice" in filename_lower:
            extracted_data.update({
                "id_card_number": "S5678901C",
                "first_name": "Alice",
                "last_name": "Williams",
                "full_name": "Alice Williams",
                "date_of_birth": "1978-04-12",
                "address": "789 Pine Rd, Singapore 789012",
                "nationality": "SINGAPORE",
            })
        # Non-local ID cards (for testing additional docs flow)
        elif "indian" in filename_lower or "india" in filename_lower or "raj" in filename_lower or "-in" in filename_lower or "_in" in filename_lower:
            extracted_data.update({
                "id_card_number": "1234-5678-9012",
                "first_name": "ANAND",
                "last_name": "KUMAR",
                "full_name": "ANAND KUMAR",
                "date_of_birth": "1985-05-24",
                "address": "42 MG Road, Mumbai, Maharashtra 400001",
                "nationality": "INDIA",
            })
        # Negative cases (will fail government verification)
        elif "fraud" in filename_lower:
            extracted_data.update({
                "id_card_number": "FLAGGED-002",
                "first_name": "Charlie",
                "last_name": "Suspicious",
                "full_name": "Charlie Suspicious",
                "date_of_birth": "1992-05-10",
                "address": "111 Alert Ave, Watchlist, WL 11111",
            })
        elif "expired" in filename_lower:
            extracted_data.update({
                "id_card_number": "EXPIRED-001",
                "first_name": "Bob",
                "last_name": "Expired",
                "full_name": "Bob Expired",
                "date_of_birth": "1988-01-01",
                "issue_date": "2010-01-01",
                "expiry_date": "2020-01-01",
            })
    
    return {
        "success": True,
        "extracted_data": extracted_data,
        "document_type": extracted_data["document_type"],
        "file_path": file_path,
        "original_filename": original_filename,
    }

