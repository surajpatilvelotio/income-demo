"""Data extraction tool for parsing identity information from OCR results."""

import re
from datetime import datetime

from strands import tool


@tool
def parse_identity_info(
    raw_text: str,
    document_type: str,
    document_number: str,
    first_name: str,
    last_name: str,
    date_of_birth: str,
    address: str | None = None,
    nationality: str | None = None,
    issue_date: str | None = None,
    expiry_date: str | None = None,
) -> dict:
    """
    Parse and structure identity information from OCR-extracted text.
    
    This tool takes raw OCR text and extracts structured identity fields.
    The agent should analyze the raw_text and provide the extracted values
    for each parameter.
    
    Args:
        raw_text: Raw text extracted from OCR
        document_type: Type of document - 'id_card' or 'passport'
        document_number: Extracted document/ID number
        first_name: Extracted first/given name
        last_name: Extracted last/family name
        date_of_birth: Extracted date of birth (format: YYYY-MM-DD)
        address: Extracted address (optional, mainly for ID cards)
        nationality: Extracted nationality (optional, mainly for passports)
        issue_date: Document issue date (format: YYYY-MM-DD, optional)
        expiry_date: Document expiry date (format: YYYY-MM-DD, optional)
        
    Returns:
        Dictionary containing:
        - success: Whether parsing was successful
        - extracted_data: Structured identity information
        - validation_warnings: List of potential issues found
        - confidence_score: Extraction confidence (0.0 to 1.0)
    """
    try:
        validation_warnings = []
        confidence_score = 1.0
        
        # Validate document number format
        if not document_number or len(document_number) < 5:
            validation_warnings.append("Document number appears too short or missing")
            confidence_score -= 0.2
        
        # Validate names
        if not first_name or not first_name.strip():
            validation_warnings.append("First name is missing")
            confidence_score -= 0.3
        
        if not last_name or not last_name.strip():
            validation_warnings.append("Last name is missing")
            confidence_score -= 0.3
        
        # Validate and parse date of birth
        dob_parsed = None
        if date_of_birth:
            try:
                dob_parsed = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
                # Check if DOB is reasonable (not in future, not too old)
                today = datetime.now().date()
                age = (today - dob_parsed).days // 365
                if age < 0:
                    validation_warnings.append("Date of birth is in the future")
                    confidence_score -= 0.5
                elif age > 120:
                    validation_warnings.append("Date of birth indicates age over 120 years")
                    confidence_score -= 0.3
                elif age < 18:
                    validation_warnings.append("Applicant appears to be under 18 years old")
            except ValueError:
                validation_warnings.append(f"Invalid date of birth format: {date_of_birth}")
                confidence_score -= 0.3
        else:
            validation_warnings.append("Date of birth is missing")
            confidence_score -= 0.4
        
        # Validate expiry date if provided
        if expiry_date:
            try:
                expiry_parsed = datetime.strptime(expiry_date, "%Y-%m-%d").date()
                today = datetime.now().date()
                if expiry_parsed < today:
                    validation_warnings.append("Document has expired")
                    confidence_score -= 0.5
            except ValueError:
                validation_warnings.append(f"Invalid expiry date format: {expiry_date}")
        
        # Build structured data
        extracted_data = {
            "document_type": document_type,
            "document_number": document_number.upper().strip() if document_number else None,
            "first_name": first_name.strip().title() if first_name else None,
            "last_name": last_name.strip().title() if last_name else None,
            "full_name": f"{first_name.strip().title()} {last_name.strip().title()}" if first_name and last_name else None,
            "date_of_birth": date_of_birth,
            "address": address.strip() if address else None,
            "nationality": nationality.strip().upper() if nationality else None,
            "issue_date": issue_date,
            "expiry_date": expiry_date,
        }
        
        # Ensure confidence score is within bounds
        confidence_score = max(0.0, min(1.0, confidence_score))
        
        return {
            "success": True,
            "extracted_data": extracted_data,
            "validation_warnings": validation_warnings,
            "confidence_score": confidence_score,
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "extracted_data": None,
            "validation_warnings": [f"Parsing error: {str(e)}"],
            "confidence_score": 0.0,
        }

