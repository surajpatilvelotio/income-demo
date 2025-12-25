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

Your task is to extract ALL text and data from the provided identity document image.

## Instructions:
1. Carefully examine the document image
2. Extract ALL visible text including:
   - Document type (ID card, passport, driver's license)
   - Document number/ID
   - Full name (first name, last name)
   - Date of birth
   - Address (if visible)
   - Issue date
   - Expiry date
   - Nationality/Country
   - Any other relevant fields

3. Return the data in a structured JSON format:
{
    "document_type": "id_card|passport|drivers_license",
    "document_number": "...",
    "first_name": "...",
    "last_name": "...",
    "full_name": "...",
    "date_of_birth": "YYYY-MM-DD",
    "address": "...",
    "issue_date": "YYYY-MM-DD",
    "expiry_date": "YYYY-MM-DD",
    "nationality": "...",
    "gender": "...",
    "additional_fields": {...}
}

4. If you cannot read certain fields, indicate them as "UNREADABLE"
5. If the image is not a valid identity document, return {"error": "Not a valid identity document"}

Be thorough and accurate. The extracted data will be used for identity verification.
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
def extract_document_data_mock(file_path: str, original_filename: str) -> dict:
    """
    Mock OCR extraction based on filename keywords.
    Used for testing without real document images.
    
    Args:
        file_path: Path to the document
        original_filename: Original filename (used for mock data selection)
        
    Returns:
        dict: Mock extracted data based on filename keywords
    """
    logger.info(f"[OCR Agent Mock] Processing: {original_filename}")
    
    # Default mock data
    extracted_data = {
        "document_type": "id_card",
        "document_number": "ID-MOCK-999999",
        "first_name": "Test",
        "last_name": "User",
        "full_name": "Test User",
        "date_of_birth": "1990-01-01",
        "address": "100 Test Street, Test City, TC 12345",
        "issue_date": "2024-01-01",
        "expiry_date": "2034-01-01",
        "nationality": "US",
    }
    
    filename_lower = original_filename.lower()
    
    # Positive cases (will match mock government records)
    if "john" in filename_lower or "success" in filename_lower:
        extracted_data.update({
            "document_number": "ID-2024-001234",
            "first_name": "John",
            "last_name": "Doe",
            "full_name": "John Doe",
            "date_of_birth": "1985-06-15",
            "address": "123 Main St, New York, NY 10001",
        })
    elif "jane" in filename_lower:
        extracted_data.update({
            "document_type": "passport",
            "document_number": "PASS-US-987654",
            "first_name": "Jane",
            "last_name": "Smith",
            "full_name": "Jane Smith",
            "date_of_birth": "1990-03-22",
            "address": "456 Oak Ave, Los Angeles, CA 90001",
        })
    elif "alice" in filename_lower:
        extracted_data.update({
            "document_number": "ID-2024-005678",
            "first_name": "Alice",
            "last_name": "Williams",
            "full_name": "Alice Williams",
            "date_of_birth": "1978-04-12",
            "address": "789 Pine Rd, Chicago, IL 60601",
        })
    # Negative cases (will fail government verification)
    elif "fraud" in filename_lower:
        extracted_data.update({
            "document_number": "ID-FLAGGED-002",
            "first_name": "Charlie",
            "last_name": "Suspicious",
            "full_name": "Charlie Suspicious",
            "date_of_birth": "1992-05-10",
            "address": "111 Alert Ave, Watchlist, WL 11111",
        })
    elif "expired" in filename_lower:
        extracted_data.update({
            "document_number": "ID-EXPIRED-001",
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

