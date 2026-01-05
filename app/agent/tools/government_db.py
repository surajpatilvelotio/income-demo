"""Government database verification tool."""

import logging
import time
from strands import tool
from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.db.models import MockGovernmentRecord
from app.utils.async_helpers import run_sync

logger = logging.getLogger(__name__)

# Delay for demo purposes to allow UI animation to complete
# Animation takes ~5 seconds to complete all checks, so we need at least 5s
DEMO_VERIFICATION_DELAY_SECONDS = 6


async def _async_verify(document_number: str, document_type: str, first_name: str, last_name: str, date_of_birth: str) -> dict:
    """Async implementation for database verification."""
    logger.info("🏛️ [Gov Verification] Starting verification...")
    logger.info(f"   📄 Document Type: {document_type}")
    logger.info(f"   🔢 Document Number: {document_number}")
    logger.info(f"   👤 Name: {first_name} {last_name}")
    logger.info(f"   📅 DOB: {date_of_birth}")
    
    async with AsyncSessionLocal() as session:
        # Query mock government database
        result = await session.execute(
            select(MockGovernmentRecord).where(
                MockGovernmentRecord.document_number == document_number
            )
        )
        record = result.scalar_one_or_none()
        
        if not record:
            logger.warning(f"   ❌ Result: NOT FOUND - No record for document {document_number}")
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
        
        logger.info(f"   📋 Found gov record: {record.first_name} {record.last_name}, DOB: {record.date_of_birth}")
        
        # Check if document is valid
        if not record.is_valid:
            logger.warning(f"   ❌ Result: INVALID - {record.flag_reason or 'Unknown reason'}")
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
            logger.warning(f"   ❌ Result: FLAGGED - {record.flag_reason}")
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
        
        logger.info(f"   🔍 Comparison: Name match={name_match}, DOB match={dob_match}, Type match={type_match}")
        
        if mismatches:
            logger.warning(f"   ❌ Result: MISMATCH - {', '.join(mismatches)}")
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
        logger.info(f"   ✅ Result: VERIFIED - All checks passed!")
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
        # Add delay for demo purposes to allow UI animation to show
        logger.info(f"🏛️ [Gov Verification] Simulating verification delay ({DEMO_VERIFICATION_DELAY_SECONDS}s)...")
        time.sleep(DEMO_VERIFICATION_DELAY_SECONDS)
        
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


@tool
def verify_visa_with_government(
    visa_number: str,
    visa_type: str,
    passport_number: str,
    first_name: str,
    last_name: str,
    date_of_birth: str,
    nationality: str,
) -> dict:
    """
    Verify visa/work permit against immigration database.
    
    This is a mock verification for demo purposes. In production, this would
    query the actual immigration/visa database.
    
    Args:
        visa_number: The visa/work permit number
        visa_type: Type of visa (e.g., 'Employment Pass', 'Work Permit')
        passport_number: Passport number linked to the visa
        first_name: First name on the visa
        last_name: Last name on the visa
        date_of_birth: Date of birth
        nationality: Nationality of the visa holder
        
    Returns:
        Dictionary containing:
        - success: Whether the verification was successful
        - verified: Whether the visa is valid
        - verification_status: Status of verification
        - message: Human-readable result
        - details: Additional verification details
    """
    from datetime import datetime, date
    
    # Add delay for demo purposes to allow UI animation to show
    logger.info(f"🛂 [Visa Verification] Simulating verification delay ({DEMO_VERIFICATION_DELAY_SECONDS}s)...")
    time.sleep(DEMO_VERIFICATION_DELAY_SECONDS)
    
    logger.info("🛂 [Visa Verification] Starting verification...")
    logger.info(f"   📄 Visa Type: {visa_type}")
    logger.info(f"   🔢 Visa Number: {visa_number}")
    logger.info(f"   🛂 Passport Number: {passport_number}")
    logger.info(f"   👤 Name: {first_name} {last_name}")
    logger.info(f"   📅 DOB: {date_of_birth}")
    logger.info(f"   🌍 Nationality: {nationality}")
    
    # Mock visa verification logic
    # In production, this would query an actual immigration database
    
    # Check for mock test cases
    visa_lower = visa_number.lower() if visa_number else ""
    
    # Valid visa patterns (for demo) - ONLY these patterns are accepted
    # For a real demo where specific visa numbers must match, add them here
    valid_visa_patterns = [
        "visa-sg-2024",
        "ep-",
        "wp-",  
        "dp-",
        # Known valid CJ visa numbers for demo (add specific numbers)
        "cj 3760864", 
        "cj3760864",
    ]
    
    # Check if visa number follows a valid pattern
    is_valid_pattern = any(pattern in visa_lower for pattern in valid_visa_patterns)
    
    # Mock expired visa check
    if "expired" in visa_lower:
        logger.warning(f"   ❌ Result: EXPIRED - Visa has expired")
        return {
            "success": True,
            "verified": False,
            "verification_status": "expired",
            "message": "Visa has expired. Please renew your visa.",
            "details": {
                "visa_number": visa_number,
                "status": "expired",
            },
        }
    
    # Mock revoked visa check
    if "revoked" in visa_lower or "cancelled" in visa_lower:
        logger.warning(f"   ❌ Result: REVOKED - Visa has been revoked/cancelled")
        return {
            "success": True,
            "verified": False,
            "verification_status": "revoked",
            "message": "Visa has been revoked or cancelled.",
            "details": {
                "visa_number": visa_number,
                "status": "revoked",
            },
        }
    
    # Only accept visa numbers that match known valid patterns
    if is_valid_pattern:
        logger.info(f"   ✅ Result: VERIFIED - Visa is valid and active")
        return {
            "success": True,
            "verified": True,
            "verification_status": "verified",
            "message": "Visa successfully verified against immigration database",
            "details": {
                "visa_number": visa_number,
                "visa_type": visa_type,
                "passport_number": passport_number,
                "holder_name": f"{first_name} {last_name}",
                "nationality": nationality,
                "status": "active",
                "verified_at": datetime.now().isoformat(),
            },
        }
    
    # Visa number not found in mock database
    logger.warning(f"   ❌ Result: NOT FOUND - No visa record for {visa_number}")
    return {
        "success": True,
        "verified": False,
        "verification_status": "not_found",
        "message": f"No visa record found for visa number: {visa_number}. Please ensure you have uploaded the correct visa document.",
        "details": {
            "visa_number": visa_number,
        },
    }
