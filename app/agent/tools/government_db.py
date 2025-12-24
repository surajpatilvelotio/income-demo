"""Government database verification tool."""

from strands import tool
from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.db.models import MockGovernmentRecord
from app.utils.async_helpers import run_sync


async def _async_verify(document_number: str, document_type: str, first_name: str, last_name: str, date_of_birth: str) -> dict:
    """Async implementation for database verification."""
    async with AsyncSessionLocal() as session:
        # Query mock government database
        result = await session.execute(
            select(MockGovernmentRecord).where(
                MockGovernmentRecord.document_number == document_number
            )
        )
        record = result.scalar_one_or_none()
        
        if not record:
            return {
                "success": True,
                "verified": False,
                "verification_status": "not_found",
                "message": f"No government record found for document number: {document_number}",
                "details": {
                    "document_number": document_number,
                    "document_type": document_type,
                },
            }
        
        # Check if document is valid
        if not record.is_valid:
            return {
                "success": True,
                "verified": False,
                "verification_status": "invalid",
                "message": f"Document is not valid: {record.flag_reason or 'Unknown reason'}",
                "details": {
                    "document_number": document_number,
                    "flag_reason": record.flag_reason,
                },
            }
        
        # Check if document is flagged
        if record.is_flagged:
            return {
                "success": True,
                "verified": False,
                "verification_status": "flagged",
                "message": f"Document is flagged: {record.flag_reason}",
                "details": {
                    "document_number": document_number,
                    "flag_reason": record.flag_reason,
                    "is_flagged": True,
                },
            }
        
        # Verify name matches
        name_match = (
            record.first_name.lower() == first_name.lower() and
            record.last_name.lower() == last_name.lower()
        )
        
        # Verify date of birth matches
        dob_match = str(record.date_of_birth) == date_of_birth
        
        # Verify document type matches
        type_match = record.document_type == document_type
        
        mismatches = []
        if not name_match:
            mismatches.append(f"Name mismatch: expected {record.first_name} {record.last_name}")
        if not dob_match:
            mismatches.append(f"DOB mismatch: expected {record.date_of_birth}")
        if not type_match:
            mismatches.append(f"Document type mismatch: expected {record.document_type}")
        
        if mismatches:
            return {
                "success": True,
                "verified": False,
                "verification_status": "mismatch",
                "message": "Document data does not match government records",
                "details": {
                    "document_number": document_number,
                    "mismatches": mismatches,
                },
            }
        
        # All checks passed
        return {
            "success": True,
            "verified": True,
            "verification_status": "verified",
            "message": "Document successfully verified against government database",
            "details": {
                "document_number": document_number,
                "document_type": document_type,
                "name_verified": True,
                "dob_verified": True,
                "government_record": {
                    "first_name": record.first_name,
                    "last_name": record.last_name,
                    "date_of_birth": str(record.date_of_birth),
                    "address": record.address,
                },
            },
        }


@tool
def verify_with_government(
    document_number: str,
    document_type: str,
    first_name: str,
    last_name: str,
    date_of_birth: str,
) -> dict:
    """
    Verify identity document against government database.
    
    This tool queries the government database to verify that the document
    exists, is valid, and that the provided information matches official records.
    
    Args:
        document_number: The document ID number (e.g., 'ID-2024-001234')
        document_type: Type of document - 'id_card' or 'passport'
        first_name: First name as extracted from the document
        last_name: Last name as extracted from the document
        date_of_birth: Date of birth (format: YYYY-MM-DD)
        
    Returns:
        Dictionary containing:
        - success: Whether the API call was successful
        - verified: Whether the document passed verification
        - verification_status: 'verified', 'not_found', 'invalid', 'flagged', or 'mismatch'
        - message: Human-readable verification result
        - details: Additional verification details
    """
    try:
        return run_sync(_async_verify(
            document_number,
            document_type,
            first_name,
            last_name,
            date_of_birth,
        ))
    except Exception as e:
        return {
            "success": False,
            "verified": False,
            "verification_status": "error",
            "message": f"Government verification failed: {str(e)}",
            "details": {
                "error": str(e),
            },
        }

