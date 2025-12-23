"""OCR tool for extracting text from ID documents."""

import base64
from pathlib import Path

from strands import tool


@tool
def extract_document_data(file_path: str, document_type: str) -> dict:
    """
    Extract text and data from an identity document using OCR.
    
    This tool reads an uploaded document image and extracts all visible text
    and data fields. It simulates OCR extraction for ID cards and passports.
    
    Args:
        file_path: Path to the document image file
        document_type: Type of document - 'id_card' or 'passport'
        
    Returns:
        Dictionary containing:
        - success: Whether extraction was successful
        - raw_text: Extracted raw text from the document
        - document_type: Type of document processed
        - file_path: Path to the processed file
        - error: Error message if extraction failed
    """
    try:
        path = Path(file_path)
        
        if not path.exists():
            return {
                "success": False,
                "error": f"Document file not found: {file_path}",
                "document_type": document_type,
            }
        
        # Read file and encode as base64 for potential vision API use
        with open(path, "rb") as f:
            file_content = f.read()
        
        file_size = len(file_content)
        file_extension = path.suffix.lower()
        
        # Validate file type
        valid_extensions = {".jpg", ".jpeg", ".png", ".pdf", ".webp"}
        if file_extension not in valid_extensions:
            return {
                "success": False,
                "error": f"Invalid file type: {file_extension}. Supported: {valid_extensions}",
                "document_type": document_type,
            }
        
        # Simulate OCR extraction based on document type
        # In production, this would call Claude Vision or another OCR service
        
        # For demo purposes, we'll return structured mock data that represents
        # what OCR would extract from a real document
        if document_type == "id_card":
            raw_text = """
            IDENTIFICATION CARD
            
            Document Number: [EXTRACTED_ID_NUMBER]
            
            Name: [EXTRACTED_FIRST_NAME] [EXTRACTED_LAST_NAME]
            Date of Birth: [EXTRACTED_DOB]
            Address: [EXTRACTED_ADDRESS]
            
            Issue Date: [EXTRACTED_ISSUE_DATE]
            Expiry Date: [EXTRACTED_EXPIRY_DATE]
            """
        elif document_type == "passport":
            raw_text = """
            PASSPORT
            
            Passport Number: [EXTRACTED_PASSPORT_NUMBER]
            
            Surname: [EXTRACTED_LAST_NAME]
            Given Names: [EXTRACTED_FIRST_NAME]
            
            Nationality: [EXTRACTED_NATIONALITY]
            Date of Birth: [EXTRACTED_DOB]
            Place of Birth: [EXTRACTED_BIRTH_PLACE]
            
            Issue Date: [EXTRACTED_ISSUE_DATE]
            Expiry Date: [EXTRACTED_EXPIRY_DATE]
            
            MRZ Line 1: [MACHINE_READABLE_ZONE_1]
            MRZ Line 2: [MACHINE_READABLE_ZONE_2]
            """
        else:
            raw_text = f"Unknown document type: {document_type}"
        
        return {
            "success": True,
            "raw_text": raw_text,
            "document_type": document_type,
            "file_path": file_path,
            "file_size": file_size,
            "file_extension": file_extension,
            "base64_preview": base64.b64encode(file_content[:1000]).decode("utf-8"),
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "document_type": document_type,
            "file_path": file_path,
        }

