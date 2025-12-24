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
        
        # For demo/testing, we use mock data that matches valid government records
        # This simulates what OCR would extract from a real document
        
        # Use different mock data based on file name hints for testing
        file_name_lower = path.name.lower()
        
        # Test case: "john" or "success" in filename -> returns John Doe (valid record)
        if "john" in file_name_lower or "success" in file_name_lower or "valid" in file_name_lower:
            if document_type == "id_card":
                raw_text = """
                IDENTIFICATION CARD
                
                Document Number: ID-2024-001234
                
                Name: John Doe
                Date of Birth: 1985-06-15
                Address: 123 Main St, New York, NY 10001
                
                Issue Date: 2024-01-15
                Expiry Date: 2034-01-15
                """
            else:
                raw_text = """
                PASSPORT
                
                Passport Number: PASS-US-123456
                
                Surname: Johnson
                Given Names: Robert
                
                Nationality: USA
                Date of Birth: 1982-11-08
                Place of Birth: Houston, TX
                
                Issue Date: 2023-05-20
                Expiry Date: 2033-05-20
                """
        # Test case: "jane" in filename -> returns Jane Smith (valid passport)
        elif "jane" in file_name_lower:
            raw_text = """
            PASSPORT
            
            Passport Number: PASS-US-987654
            
            Surname: Smith
            Given Names: Jane
            
            Nationality: USA
            Date of Birth: 1990-03-22
            Place of Birth: Los Angeles, CA
            
            Issue Date: 2022-08-10
            Expiry Date: 2032-08-10
            """
        # Test case: "alice" in filename -> returns Alice Williams (valid id_card)
        elif "alice" in file_name_lower:
            raw_text = """
            IDENTIFICATION CARD
            
            Document Number: ID-2024-005678
            
            Name: Alice Williams
            Date of Birth: 1978-04-12
            Address: 789 Pine Rd, Chicago, IL 60601
            
            Issue Date: 2023-03-01
            Expiry Date: 2033-03-01
            """
        # Test case: "fraud" or "expired" in filename -> returns invalid record
        elif "fraud" in file_name_lower or "expired" in file_name_lower or "invalid" in file_name_lower:
            raw_text = """
            IDENTIFICATION CARD
            
            Document Number: ID-EXPIRED-001
            
            Name: Bob Fraud
            Date of Birth: 1988-01-01
            Address: 999 Fake St, Nowhere, XX 00000
            
            Issue Date: 2014-01-01
            Expiry Date: 2019-01-01
            """
        # Default: generic mock data (will likely fail government verification)
        elif document_type == "id_card":
            raw_text = """
            IDENTIFICATION CARD
            
            Document Number: ID-MOCK-999999
            
            Name: Test User
            Date of Birth: 1990-01-01
            Address: 100 Test Street, Test City, TC 12345
            
            Issue Date: 2024-01-01
            Expiry Date: 2034-01-01
            """
        elif document_type == "passport":
            raw_text = """
            PASSPORT
            
            Passport Number: PASS-MOCK-999999
            
            Surname: User
            Given Names: Test
            
            Nationality: USA
            Date of Birth: 1990-01-01
            Place of Birth: Test City
            
            Issue Date: 2024-01-01
            Expiry Date: 2034-01-01
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

