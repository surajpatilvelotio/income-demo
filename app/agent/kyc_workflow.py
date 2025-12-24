"""
KYC Verification Workflow using Sequential Multi-Agent Pattern.

Workflow Steps:
1. OCR Agent: Extract data from documents
2. User Review: User confirms extracted data
3. KYC Agent: Government DB validation → Fraud detection → Decision

"""

import asyncio
import logging
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.database import AsyncSessionLocal
from app.db.models import KYCApplication, KYCDocument, KYCStage, User
from app.agent.ocr_agent import extract_document_data_mock, extract_document_data_with_vision
from app.agent.tools.government_db import verify_with_government
from app.agent.tools.fraud_detection import check_fraud_indicators
from app.agent.tools.stage_tracker import update_kyc_stage
from app.config import settings

logger = logging.getLogger(__name__)


class KYCWorkflowStatus(str, Enum):
    """KYC Workflow status states."""
    PENDING_OCR = "pending_ocr"
    PENDING_USER_REVIEW = "pending_user_review"
    USER_CONFIRMED = "user_confirmed"
    GOV_VERIFICATION_PENDING = "gov_verification_pending"
    GOV_VERIFICATION_PASSED = "gov_verification_passed"
    GOV_VERIFICATION_FAILED = "gov_verification_failed"
    FRAUD_CHECK_PENDING = "fraud_check_pending"
    FRAUD_CHECK_PASSED = "fraud_check_passed"
    FRAUD_CHECK_FAILED = "fraud_check_failed"
    APPROVED = "approved"
    REJECTED = "rejected"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


class KYCWorkflow:
    """
    Sequential KYC Workflow Manager.
    
    Implements the workflow pattern for KYC verification:
    OCR → User Review → Gov Validation → Fraud Detection → Decision
    """
    
    def __init__(self, application_id: str):
        self.application_id = application_id
        self.extracted_data: dict | None = None
        self.gov_verification_result: dict | None = None
        self.fraud_check_result: dict | None = None
        self.final_decision: str | None = None
        self.decision_reason: str | None = None
    
    async def run_ocr_step(self, documents: list[dict]) -> dict:
        """
        Step 1: Run OCR on uploaded documents.
        
        Args:
            documents: List of document info with file_path, document_type, original_filename
            
        Returns:
            dict: OCR results for user review
        """
        logger.info(f"🔍 [OCR Step] Processing {len(documents)} document(s) for application {self.application_id}")
        
        # Update stage (sync function from @tool decorator)
        update_kyc_stage(
            application_id=self.application_id,
            stage_name="ocr_processing",
            status="in_progress",
        )
        
        # Process documents in parallel using asyncio.gather
        async def process_single_document(doc: dict) -> dict | None:
            """Process a single document with OCR."""
            file_path = doc.get("file_path")
            doc_type = doc.get("document_type", "id_card")
            original_filename = doc.get("original_filename", "document.png")
            
            logger.info(f"   Processing: {original_filename}")
            
            # Run OCR in thread pool to not block (sync function)
            # Toggle between real and mock OCR using settings.use_real_ocr
            # Set USE_REAL_OCR=true/false in .env or app/config.py
            if settings.use_real_ocr:
                # Real OCR: Uses Bedrock Claude vision to extract data from actual image
                ocr_result = await asyncio.to_thread(
                    extract_document_data_with_vision, file_path, doc_type
                )
            else:
                # Mock OCR: Returns predefined data based on filename (for testing)
                ocr_result = await asyncio.to_thread(
                    extract_document_data_mock, file_path, original_filename
                )
            
            if ocr_result.get("success"):
                logger.info(f"   ✅ Extracted: {ocr_result.get('extracted_data', {}).get('full_name', 'N/A')}")
                return {
                    "document_type": doc_type,
                    "filename": original_filename,
                    "extracted_data": ocr_result.get("extracted_data", {}),
                }
            else:
                logger.warning(f"   ❌ OCR failed: {ocr_result.get('error')}")
                return None
        
        # Process all documents in parallel
        logger.info(f"   Starting parallel OCR for {len(documents)} document(s)...")
        results = await asyncio.gather(*[process_single_document(doc) for doc in documents])
        
        # Filter out None results (failed OCR)
        all_extracted_data = [r for r in results if r is not None]
        failed_count = len(documents) - len(all_extracted_data)
        logger.info(f"   Completed: {len(all_extracted_data)}/{len(documents)} documents processed")
        
        # Identify failed documents
        failed_documents = []
        for i, (doc, result) in enumerate(zip(documents, results)):
            if result is None:
                failed_documents.append(doc.get("original_filename", f"document_{i}"))
        
        # Check if OCR failed for all documents
        if not all_extracted_data:
            logger.error(f"   ❌ OCR failed for all {len(documents)} document(s)")
            
            # Update stage as failed
            update_kyc_stage(
                application_id=self.application_id,
                stage_name="ocr_processing",
                status="failed",
                result_data={
                    "error": "Failed to extract data from documents",
                    "documents_attempted": len(documents),
                    "failed_documents": failed_documents,
                },
            )
            
            # Update application status
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(KYCApplication).where(KYCApplication.id == self.application_id)
                )
                application = result.scalar_one_or_none()
                if application:
                    application.current_stage = "ocr_failed"
                    await session.commit()
            
            return {
                "success": False,
                "status": KYCWorkflowStatus.FAILED,
                "error": "Failed to extract data from documents. Please upload clearer images.",
                "documents_attempted": len(documents),
                "documents_processed": 0,
                "failed_documents": failed_documents,
            }
        
        # Check for partial failure
        is_partial_success = failed_count > 0
        if is_partial_success:
            logger.warning(f"   ⚠️ Partial OCR: {failed_count} document(s) failed: {', '.join(failed_documents)}")
        
        # Update stage - partial_success or completed
        stage_status = "partial_success" if is_partial_success else "completed"
        update_kyc_stage(
            application_id=self.application_id,
            stage_name="ocr_processing",
            status=stage_status,
            result_data={
                "documents_processed": len(all_extracted_data),
                "documents_failed": failed_count,
                "failed_documents": failed_documents if failed_documents else None,
            },
        )
        
        # Store combined data (use first document as primary)
        self.extracted_data = all_extracted_data[0].get("extracted_data", {})
        
        # Update application with extracted data
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(KYCApplication).where(KYCApplication.id == self.application_id)
            )
            application = result.scalar_one_or_none()
            if application:
                application.extracted_data = self.extracted_data
                application.current_stage = "pending_user_review"
                await session.commit()
        
        # Build response with partial failure info if applicable
        response = {
            "success": True,
            "status": KYCWorkflowStatus.PENDING_USER_REVIEW,
            "message": "Document data extracted successfully. Please review the information.",
            "extracted_data": all_extracted_data,
            "extracted_data_for_review": all_extracted_data,
            "requires_user_action": True,
            "next_action": "confirm_extracted_data",
            "documents_processed": len(all_extracted_data),
            "documents_attempted": len(documents),
        }
        
        # Add partial failure info if some documents failed
        if is_partial_success:
            response["partial_success"] = True
            response["documents_failed"] = failed_count
            response["failed_documents"] = failed_documents
            response["message"] = (
                f"Extracted data from {len(all_extracted_data)} of {len(documents)} documents. "
                f"Failed: {', '.join(failed_documents)}. "
                "Please review the extracted information and consider re-uploading failed documents."
            )
        
        return response
    
    async def confirm_user_data(self, confirmed: bool = True, corrections: dict | None = None) -> dict:
        """
        Step 2: User confirms or corrects extracted data.
        
        Args:
            confirmed: Whether user confirms the data
            corrections: Optional corrections to the extracted data
            
        Returns:
            dict: Confirmation status
        """
        logger.info(f"👤 [User Review] Confirmation received for application {self.application_id}")
        
        if not confirmed:
            return {
                "status": KYCWorkflowStatus.PENDING_USER_REVIEW,
                "message": "Please provide corrections to the extracted data.",
                "requires_user_action": True,
            }
        
        # Apply corrections if provided
        if corrections:
            if self.extracted_data:
                self.extracted_data.update(corrections)
            else:
                self.extracted_data = corrections
        
        # Update application
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(KYCApplication).where(KYCApplication.id == self.application_id)
            )
            application = result.scalar_one_or_none()
            if application:
                application.extracted_data = self.extracted_data
                application.current_stage = "user_confirmed"
                application.status = "processing"
                await session.commit()
        
        update_kyc_stage(
            application_id=self.application_id,
            stage_name="user_review",
            status="completed",
            result_data={"user_confirmed": True},
        )
        
        return {
            "status": KYCWorkflowStatus.USER_CONFIRMED,
            "message": "Data confirmed. Proceeding with government database verification.",
            "requires_user_action": False,
            "next_step": "government_verification",
        }
    
    async def run_government_verification(self) -> dict:
        """
        Step 3: Verify extracted data against government database.
        
        If verification fails → STOP and suggest manual KYC.
        
        Returns:
            dict: Verification result
        """
        logger.info(f"🏛️ [Gov Verification] Checking application {self.application_id}")
        
        if not self.extracted_data:
            # Load from database
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(KYCApplication).where(KYCApplication.id == self.application_id)
                )
                application = result.scalar_one_or_none()
                if application:
                    self.extracted_data = application.extracted_data
        
        if not self.extracted_data:
            return {
                "status": KYCWorkflowStatus.REJECTED,
                "message": "No extracted data available for verification.",
                "requires_user_action": False,
            }
        
        update_kyc_stage(
            application_id=self.application_id,
            stage_name="gov_verification",
            status="in_progress",
        )
        
        # Call government verification tool
        gov_result = verify_with_government(
            document_number=self.extracted_data.get("document_number", ""),
            document_type=self.extracted_data.get("document_type", "id_card"),
            first_name=self.extracted_data.get("first_name", ""),
            last_name=self.extracted_data.get("last_name", ""),
            date_of_birth=self.extracted_data.get("date_of_birth", ""),
        )
        
        self.gov_verification_result = gov_result
        
        # Check if verification passed
        if not gov_result.get("verified", False):
            logger.warning(f"   ❌ Gov verification FAILED: {gov_result.get('message', 'Unknown reason')}")
            
            update_kyc_stage(
                application_id=self.application_id,
                stage_name="gov_verification",
                status="failed",
                result_data=gov_result,
            )
            
            # Update application - STOP here, suggest manual KYC
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(KYCApplication).where(KYCApplication.id == self.application_id)
                )
                application = result.scalar_one_or_none()
                if application:
                    application.status = "failed"
                    application.decision = "manual_review"
                    application.decision_reason = f"Government database verification failed: {gov_result.get('message', 'Document not found in government records')}. Manual KYC review required."
                    application.current_stage = "gov_verification_failed"
                    await session.commit()
                
                # Also update user status
                user_result = await session.execute(
                    select(User).where(User.id == application.user_id)
                )
                user = user_result.scalar_one_or_none()
                if user:
                    user.kyc_status = "manual_review"
                    await session.commit()
            
            return {
                "status": KYCWorkflowStatus.MANUAL_REVIEW_REQUIRED,
                "message": "⚠️ Government database verification failed. Your application requires manual review by our team. You will be contacted within 2-3 business days.",
                "reason": gov_result.get("message", "Document not found in government records"),
                "requires_user_action": False,
                "workflow_stopped": True,
            }
        
        logger.info(f"   ✅ Gov verification PASSED")
        
        update_kyc_stage(
            application_id=self.application_id,
            stage_name="gov_verification",
            status="completed",
            result_data=gov_result,
        )
        
        return {
            "status": KYCWorkflowStatus.GOV_VERIFICATION_PASSED,
            "message": "Government database verification passed. Proceeding with fraud detection.",
            "requires_user_action": False,
            "next_step": "fraud_detection",
        }
    
    async def run_fraud_detection(self) -> dict:
        """
        Step 4: Run fraud detection checks.
        
        Only called if government verification passed.
        
        Returns:
            dict: Fraud detection result
        """
        logger.info(f"🔎 [Fraud Detection] Checking application {self.application_id}")
        
        update_kyc_stage(
            application_id=self.application_id,
            stage_name="fraud_check",
            status="in_progress",
        )
        
        # Call fraud detection tool with correct parameters
        fraud_result = check_fraud_indicators(
            document_number=self.extracted_data.get("document_number", ""),
            document_type=self.extracted_data.get("document_type", "id_card"),
            first_name=self.extracted_data.get("first_name", ""),
            last_name=self.extracted_data.get("last_name", ""),
            date_of_birth=self.extracted_data.get("date_of_birth", ""),
            address=self.extracted_data.get("address"),
            expiry_date=self.extracted_data.get("expiry_date"),
            government_verified=self.gov_verification_result.get("verified", False),
            government_verification_status=self.gov_verification_result.get("verification_status", "unknown"),
        )
        
        self.fraud_check_result = fraud_result
        
        update_kyc_stage(
            application_id=self.application_id,
            stage_name="fraud_check",
            status="completed",
            result_data=fraud_result,
        )
        
        risk_level = fraud_result.get("risk_level", "unknown")
        logger.info(f"   Risk level: {risk_level}")
        
        return {
            "status": KYCWorkflowStatus.FRAUD_CHECK_PASSED if risk_level in ["low", "medium"] else KYCWorkflowStatus.FRAUD_CHECK_FAILED,
            "risk_level": risk_level,
            "indicators": fraud_result.get("indicators", []),
            "next_step": "final_decision",
        }
    
    async def make_final_decision(self) -> dict:
        """
        Step 5: Make final KYC decision based on all checks.
        
        Uses update_kyc_stage() for all DB updates to avoid redundancy.
        The stage tracker handles updating both application and user status.
        
        Returns:
            dict: Final decision
        """
        logger.info(f"⚖️ [Final Decision] Processing application {self.application_id}")
        
        update_kyc_stage(
            application_id=self.application_id,
            stage_name="decision_made",
            status="in_progress",
        )
        
        # Determine decision based on verification results
        gov_verified = self.gov_verification_result and self.gov_verification_result.get("verified", False)
        fraud_risk = self.fraud_check_result.get("risk_level", "unknown") if self.fraud_check_result else "unknown"
        
        if not gov_verified:
            self.final_decision = "rejected"
            self.decision_reason = "Government database verification failed."
        elif fraud_risk in ["high", "critical"]:
            self.final_decision = "rejected"
            fraud_indicators = self.fraud_check_result.get("fraud_indicators", [])
            indicator_messages = [i.get("message", "") for i in fraud_indicators if i.get("severity") in ["high", "critical"]]
            self.decision_reason = f"High fraud risk detected: {', '.join(indicator_messages) or fraud_risk}"
        else:
            self.final_decision = "approved"
            self.decision_reason = "All verification checks passed successfully."
        
        logger.info(f"   Decision: {self.final_decision.upper()}")
        logger.info(f"   Reason: {self.decision_reason}")
        
        # Update stage with decision - this also updates application and user status
        update_kyc_stage(
            application_id=self.application_id,
            stage_name="decision_made",
            status="completed",
            result_data={"decision": self.final_decision, "decision_reason": self.decision_reason},
        )
        
        if self.final_decision == "approved":
            return {
                "status": KYCWorkflowStatus.APPROVED,
                "decision": "approved",
                "message": "🎉 Congratulations! Your identity has been verified. Your account is now fully active.",
                "reason": self.decision_reason,
            }
        else:
            return {
                "status": KYCWorkflowStatus.REJECTED,
                "decision": "rejected",
                "message": "❌ We were unable to verify your identity. Please contact support for assistance.",
                "reason": self.decision_reason,
            }
    
    async def run_full_verification(self, skip_user_review: bool = False) -> dict:
        """
        Run the complete KYC verification workflow.
        
        Workflow: Gov Verification → Fraud Detection (if gov passes) → Decision
        
        Args:
            skip_user_review: If True, skip waiting for user review
            
        Returns:
            dict: Final workflow result
        """
        logger.info(f"🚀 [KYC Workflow] Starting full verification for application {self.application_id}")
        
        # Step 3: Government verification
        gov_result = await self.run_government_verification()
        
        # STOP if gov verification failed
        if gov_result.get("workflow_stopped") or gov_result["status"] == KYCWorkflowStatus.MANUAL_REVIEW_REQUIRED:
            return gov_result
        
        # Step 4: Fraud detection (only if gov verification passed)
        fraud_result = await self.run_fraud_detection()
        
        # Step 5: Final decision
        decision_result = await self.make_final_decision()
        
        return decision_result


async def process_kyc_workflow(application_id: str, documents: list[dict]) -> dict:
    """
    Entry point for KYC workflow processing.
    
    Args:
        application_id: The KYC application ID
        documents: List of document info
        
    Returns:
        dict: Workflow result
    """
    workflow = KYCWorkflow(application_id)
    
    # Step 1: OCR
    ocr_result = await workflow.run_ocr_step(documents)
    
    # For auto-processing (skip user review in background processing)
    # In production, you'd wait for user confirmation
    confirm_result = await workflow.confirm_user_data(confirmed=True)
    
    # Run remaining verification steps
    final_result = await workflow.run_full_verification()
    
    return {
        "application_id": application_id,
        "ocr_result": ocr_result,
        "final_result": final_result,
    }

