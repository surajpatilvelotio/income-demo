"""KYC Status service for updating user and application status.

Centralizes the logic for updating KYC-related status to avoid duplication
across multiple modules.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, KYCApplication


async def update_user_kyc_status(
    session: AsyncSession,
    user_id: str,
    kyc_status: str,
) -> bool:
    """
    Update a user's KYC status.
    
    Args:
        session: Database session
        user_id: The user's ID
        kyc_status: New status ('pending', 'in_progress', 'approved', 'rejected', 'manual_review')
        
    Returns:
        bool: True if update successful, False if user not found
    """
    result = await session.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        return False
    
    user.kyc_status = kyc_status
    user.updated_at = datetime.now(timezone.utc)
    
    return True


async def update_application_decision(
    session: AsyncSession,
    application_id: str,
    decision: str,
    decision_reason: str,
    current_stage: str = "decision_made",
) -> bool:
    """
    Update a KYC application with the final decision.
    
    Args:
        session: Database session
        application_id: The application ID
        decision: The decision ('approved', 'rejected', 'manual_review')
        decision_reason: Reason for the decision
        current_stage: Current stage name (default: 'decision_made')
        
    Returns:
        bool: True if update successful, False if application not found
    """
    result = await session.execute(
        select(KYCApplication).where(KYCApplication.id == application_id)
    )
    application = result.scalar_one_or_none()
    
    if not application:
        return False
    
    now = datetime.now(timezone.utc)
    
    application.decision = decision
    application.decision_reason = decision_reason
    application.current_stage = current_stage
    application.updated_at = now
    
    # Set status based on decision
    if decision == "approved":
        application.status = "completed"
    elif decision in ["rejected", "manual_review"]:
        application.status = "failed"
    
    return True


async def update_application_and_user_status(
    session: AsyncSession,
    application_id: str,
    decision: str,
    decision_reason: str,
    current_stage: str = "decision_made",
) -> tuple[bool, bool]:
    """
    Update both the application decision and user KYC status.
    
    Args:
        session: Database session
        application_id: The application ID
        decision: The decision ('approved', 'rejected', 'manual_review')
        decision_reason: Reason for the decision
        current_stage: Current stage name (default: 'decision_made')
        
    Returns:
        tuple[bool, bool]: (application_updated, user_updated)
    """
    app_updated = await update_application_decision(
        session, application_id, decision, decision_reason, current_stage
    )
    
    if not app_updated:
        return False, False
    
    # Get user_id from application
    result = await session.execute(
        select(KYCApplication.user_id).where(KYCApplication.id == application_id)
    )
    user_id = result.scalar_one_or_none()
    
    if not user_id:
        return True, False
    
    user_updated = await update_user_kyc_status(session, user_id, decision)
    
    return True, user_updated

