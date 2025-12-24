"""KYC decision tool for making final approval/rejection decisions."""

from datetime import datetime, timezone

from strands import tool
from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.db.models import KYCApplication, KYCStage, User
from app.utils.async_helpers import run_sync


async def _async_finalize_decision(application_id: str, decision: str, decision_reason: str) -> None:
    """Async implementation to update the application with the final decision."""
    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        
        # Get application
        result = await session.execute(
            select(KYCApplication).where(KYCApplication.id == application_id)
        )
        application = result.scalar_one_or_none()
        
        if not application:
            return
        
        # Update application
        application.current_stage = "decision_made"
        application.decision = decision
        application.decision_reason = decision_reason
        application.status = "completed" if decision == "approved" else "failed"
        application.updated_at = now
        
        # Create or update decision stage
        stage_result = await session.execute(
            select(KYCStage).where(
                KYCStage.application_id == application_id,
                KYCStage.stage_name == "decision_made",
            )
        )
        existing_stage = stage_result.scalar_one_or_none()
        
        if existing_stage:
            existing_stage.status = "completed"
            existing_stage.result = {"decision": decision, "decision_reason": decision_reason}
            existing_stage.completed_at = now
        else:
            new_stage = KYCStage(
                application_id=application_id,
                stage_name="decision_made",
                status="completed",
                result={"decision": decision, "decision_reason": decision_reason},
                completed_at=now,
            )
            session.add(new_stage)
        
        # Update user KYC status
        user_result = await session.execute(
            select(User).where(User.id == application.user_id)
        )
        user = user_result.scalar_one_or_none()
        if user:
            user.kyc_status = decision
            user.updated_at = now
        
        await session.commit()


@tool
def make_kyc_decision(
    application_id: str,
    government_verified: bool,
    fraud_risk_level: str,
    fraud_risk_score: float,
    ocr_confidence: float,
    extracted_data: dict,
    fraud_indicators: list | None = None,
) -> dict:
    """
    Make final KYC decision based on all verification results.
    
    This tool evaluates all verification results and makes a final
    approval or rejection decision for the KYC application.
    
    Args:
        application_id: The KYC application ID
        government_verified: Whether government verification passed
        fraud_risk_level: Risk level from fraud detection ('low', 'medium', 'high', 'critical')
        fraud_risk_score: Numeric risk score (0.0 to 1.0)
        ocr_confidence: Confidence score from OCR extraction (0.0 to 1.0)
        extracted_data: Dictionary of extracted identity data
        fraud_indicators: List of detected fraud indicators (optional)
        
    Returns:
        Dictionary containing:
        - success: Whether decision was made successfully
        - decision: 'approved' or 'rejected'
        - decision_reason: Detailed reason for the decision
        - confidence: Decision confidence score
        - summary: Summary of all verification results
        - next_steps: Recommended next steps
    """
    try:
        fraud_indicators = fraud_indicators or []
        
        # Initialize decision factors
        approval_factors = []
        rejection_factors = []
        
        # Evaluate government verification
        if government_verified:
            approval_factors.append("Government verification passed")
        else:
            rejection_factors.append("Government verification failed")
        
        # Evaluate fraud risk
        if fraud_risk_level == "low":
            approval_factors.append("Low fraud risk")
        elif fraud_risk_level == "medium":
            approval_factors.append("Medium fraud risk (acceptable)")
        elif fraud_risk_level == "high":
            rejection_factors.append(f"High fraud risk (score: {fraud_risk_score:.2f})")
        elif fraud_risk_level == "critical":
            rejection_factors.append(f"Critical fraud risk (score: {fraud_risk_score:.2f})")
        
        # Evaluate OCR confidence
        if ocr_confidence >= 0.8:
            approval_factors.append(f"High OCR confidence ({ocr_confidence:.2f})")
        elif ocr_confidence >= 0.6:
            approval_factors.append(f"Acceptable OCR confidence ({ocr_confidence:.2f})")
        else:
            rejection_factors.append(f"Low OCR confidence ({ocr_confidence:.2f})")
        
        # Check extracted data completeness
        required_fields = ["document_number", "first_name", "last_name", "date_of_birth"]
        missing_fields = [f for f in required_fields if not extracted_data.get(f)]
        
        if not missing_fields:
            approval_factors.append("All required fields extracted")
        else:
            rejection_factors.append(f"Missing required fields: {', '.join(missing_fields)}")
        
        # Add specific fraud indicators
        critical_indicators = [i for i in fraud_indicators if i.get("severity") == "critical"]
        high_indicators = [i for i in fraud_indicators if i.get("severity") == "high"]
        
        for indicator in critical_indicators:
            rejection_factors.append(f"Critical: {indicator.get('message', 'Unknown')}")
        
        for indicator in high_indicators:
            rejection_factors.append(f"High risk: {indicator.get('message', 'Unknown')}")
        
        # Make decision
        # Automatic rejection criteria
        auto_reject = (
            not government_verified or
            fraud_risk_level in ["high", "critical"] or
            ocr_confidence < 0.5 or
            len(missing_fields) > 0 or
            len(critical_indicators) > 0
        )
        
        if auto_reject:
            decision = "rejected"
            decision_reason = "KYC rejected due to: " + "; ".join(rejection_factors)
            confidence = 0.9 if fraud_risk_level == "critical" else 0.8
            next_steps = [
                "User will be notified of rejection",
                "Account will remain in pending state",
                "User may resubmit with valid documents",
            ]
        else:
            decision = "approved"
            decision_reason = "KYC approved based on: " + "; ".join(approval_factors)
            confidence = min(0.95, 0.7 + (ocr_confidence * 0.2) + (0.1 if government_verified else 0))
            next_steps = [
                "User account will be activated",
                "Member record will be created with extracted data",
                "User can access full platform features",
            ]
        
        # Finalize the decision in the database
        run_sync(_async_finalize_decision(application_id, decision, decision_reason))
        
        return {
            "success": True,
            "decision": decision,
            "decision_reason": decision_reason,
            "confidence": confidence,
            "summary": {
                "application_id": application_id,
                "government_verified": government_verified,
                "fraud_risk_level": fraud_risk_level,
                "fraud_risk_score": fraud_risk_score,
                "ocr_confidence": ocr_confidence,
                "approval_factors": approval_factors,
                "rejection_factors": rejection_factors,
                "fraud_indicators_count": len(fraud_indicators),
            },
            "extracted_data": extracted_data,
            "next_steps": next_steps,
        }
        
    except Exception as e:
        return {
            "success": False,
            "decision": "rejected",
            "decision_reason": f"Decision process failed: {str(e)}",
            "confidence": 0.0,
            "error": str(e),
            "summary": None,
            "next_steps": ["Manual review required due to system error"],
        }

