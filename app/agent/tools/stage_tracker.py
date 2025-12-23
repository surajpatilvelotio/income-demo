"""Stage tracking tool for updating KYC processing stages."""

from datetime import datetime, timezone
import asyncio

from strands import tool

from app.db.database import AsyncSessionLocal
from app.db.models import KYCApplication, KYCStage, User
from sqlalchemy import select


def _sync_update_stage(
    application_id: str,
    stage_name: str,
    status: str,
    result: dict | None = None,
) -> dict:
    """Synchronous wrapper for stage update."""
    
    async def _async_update():
        async with AsyncSessionLocal() as session:
            # Find application
            app_result = await session.execute(
                select(KYCApplication).where(KYCApplication.id == application_id)
            )
            application = app_result.scalar_one_or_none()
            
            if not application:
                return {
                    "success": False,
                    "error": f"Application not found: {application_id}",
                }
            
            now = datetime.now(timezone.utc)
            
            # Check if stage already exists
            stage_result = await session.execute(
                select(KYCStage).where(
                    KYCStage.application_id == application_id,
                    KYCStage.stage_name == stage_name,
                )
            )
            existing_stage = stage_result.scalar_one_or_none()
            
            if existing_stage:
                # Update existing stage
                existing_stage.status = status
                if result:
                    existing_stage.result = result
                if status == "in_progress" and not existing_stage.started_at:
                    existing_stage.started_at = now
                if status in ["completed", "failed"]:
                    existing_stage.completed_at = now
            else:
                # Create new stage
                new_stage = KYCStage(
                    application_id=application_id,
                    stage_name=stage_name,
                    status=status,
                    result=result,
                    started_at=now if status == "in_progress" else None,
                    completed_at=now if status in ["completed", "failed"] else None,
                )
                session.add(new_stage)
            
            # Update application current stage
            application.current_stage = stage_name
            application.updated_at = now
            
            # Update application status based on stage
            if stage_name == "decision_made":
                if result and result.get("decision") == "approved":
                    application.status = "completed"
                    application.decision = "approved"
                    application.decision_reason = result.get("decision_reason")
                    
                    # Update user KYC status
                    user_result = await session.execute(
                        select(User).where(User.id == application.user_id)
                    )
                    user = user_result.scalar_one_or_none()
                    if user:
                        user.kyc_status = "approved"
                        user.updated_at = now
                        
                elif result and result.get("decision") == "rejected":
                    application.status = "failed"
                    application.decision = "rejected"
                    application.decision_reason = result.get("decision_reason")
                    
                    # Update user KYC status
                    user_result = await session.execute(
                        select(User).where(User.id == application.user_id)
                    )
                    user = user_result.scalar_one_or_none()
                    if user:
                        user.kyc_status = "rejected"
                        user.updated_at = now
            elif status == "in_progress":
                application.status = "processing"
            
            await session.commit()
            
            return {
                "success": True,
                "stage_name": stage_name,
                "status": status,
                "application_id": application_id,
                "timestamp": now.isoformat(),
            }
    
    # Run async function in sync context
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(_async_update())


@tool
def update_kyc_stage(
    application_id: str,
    stage_name: str,
    status: str,
    result_data: dict | None = None,
) -> dict:
    """
    Update KYC processing stage in the database.
    
    This tool updates the current stage of a KYC application and records
    the stage result. Use this after completing each processing step.
    
    Valid stage names (in order):
    - document_uploaded: Documents have been uploaded
    - ocr_processing: OCR extraction is in progress
    - data_extracted: Identity data has been extracted
    - gov_verification: Government verification is in progress
    - fraud_check: Fraud detection check is in progress
    - decision_made: Final KYC decision has been made
    
    Valid status values:
    - pending: Stage not yet started
    - in_progress: Stage is currently being processed
    - completed: Stage completed successfully
    - failed: Stage failed
    
    Args:
        application_id: The KYC application ID
        stage_name: Name of the stage being updated
        status: Status of the stage
        result_data: Optional dictionary with stage result data
        
    Returns:
        Dictionary containing:
        - success: Whether update was successful
        - stage_name: Updated stage name
        - status: Updated status
        - application_id: Application ID
        - timestamp: Update timestamp
    """
    try:
        # Validate stage name
        valid_stages = [
            "document_uploaded",
            "ocr_processing",
            "data_extracted",
            "gov_verification",
            "fraud_check",
            "decision_made",
        ]
        
        if stage_name not in valid_stages:
            return {
                "success": False,
                "error": f"Invalid stage name: {stage_name}. Valid stages: {valid_stages}",
            }
        
        # Validate status
        valid_statuses = ["pending", "in_progress", "completed", "failed"]
        if status not in valid_statuses:
            return {
                "success": False,
                "error": f"Invalid status: {status}. Valid statuses: {valid_statuses}",
            }
        
        return _sync_update_stage(
            application_id=application_id,
            stage_name=stage_name,
            status=status,
            result=result_data,
        )
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "stage_name": stage_name,
            "status": status,
            "application_id": application_id,
        }

