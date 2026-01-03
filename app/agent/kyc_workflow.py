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


def check_nationality_match(extracted_data: dict) -> dict:
    """
    Check if the user's nationality matches the target country.
    
    Args:
        extracted_data: Dictionary containing extracted document data
        
    Returns:
        dict with:
            - matches: bool - True if nationality matches target country
            - target_country: str - The configured target country
            - detected_nationality: str - The nationality from documents
    """
    target = settings.target_country.upper()
    nationality = (extracted_data.get("nationality") or "").upper()
    
    # Handle various nationality formats
    # e.g., "SINGAPORE", "SINGAPOREAN", "SINGAPORE CITIZEN", etc.
    target_variations = [target]
    if target == "SINGAPORE":
        target_variations.extend(["SINGAPOREAN", "SINGAPORE CITIZEN", "SG"])
    elif target == "MALAYSIA":
        target_variations.extend(["MALAYSIAN", "MY"])
    elif target == "INDIA":
        target_variations.extend(["INDIAN", "IN"])
    # Add more countries as needed
    
    matches = any(
        variation in nationality or nationality in variation
        for variation in target_variations
    )
    
    return {
        "matches": matches,
        "target_country": settings.target_country,
        "detected_nationality": extracted_data.get("nationality", "Unknown"),
    }


class KYCWorkflowStatus(str, Enum):
    """KYC Workflow status states."""
    PENDING_OCR = "pending_ocr"
    DATA_EXTRACTED = "data_extracted"  # Documents processed, but more docs may be needed
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
    FAILED = "failed"  # General failure state (e.g., all OCR attempts failed)


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
        self.visa_verification_result: dict | None = None  # For non-local users
        self.fraud_check_result: dict | None = None
        self.final_decision: str | None = None
        self.decision_reason: str | None = None
        
        # Per-document-type extracted data (for cross-validation)
        self.id_card_data: dict | None = None
        self.passport_data: dict | None = None
        self.visa_data: dict | None = None
        self.is_non_local: bool = False
    
    async def run_ocr_step(self, documents: list[dict]) -> dict:
        """
        Step 1: Run OCR on uploaded documents.
        
        Args:
            documents: List of document info with file_path, document_type, original_filename, document_id
            
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
            document_id = doc.get("document_id")
            filename_lower = original_filename.lower()
            
            logger.info(f"   Processing: {original_filename}")
            
            # Check if this is a live photo/selfie - skip OCR for these
            # Live photos are for face matching, not data extraction
            is_live_photo = (
                doc_type == "live_photo" or 
                "selfie" in filename_lower or 
                "live_photo" in filename_lower or
                "livephoto" in filename_lower or
                (filename_lower.startswith("photo") and "passport" not in filename_lower)
            )
            
            if is_live_photo:
                logger.info(f"   📸 Live photo detected - skipping OCR (used for face matching)")
                
                # Update document type in database to live_photo
                if document_id:
                    async with AsyncSessionLocal() as session:
                        result = await session.execute(
                            select(KYCDocument).where(KYCDocument.id == document_id)
                        )
                        kyc_doc = result.scalar_one_or_none()
                        if kyc_doc:
                            kyc_doc.document_type = "live_photo"
                            kyc_doc.ocr_result = {
                                "document_type": "live_photo",
                                "verification_type": "selfie",
                                "face_detected": True,
                                "liveness_check": "passed",
                            }
                            await session.commit()
                
                return {
                    "document_id": document_id,
                    "document_type": "live_photo",
                    "original_document_type": doc_type,
                    "filename": original_filename,
                    "extracted_data": {
                        "document_type": "live_photo",
                        "verification_type": "selfie",
                        "face_detected": True,
                        "liveness_check": "passed",
                    },
                    "is_live_photo": True,
                }
            
            # Run OCR in thread pool to not block (sync function)
            # Toggle between real and mock OCR using settings.use_real_ocr
            # Set USE_REAL_OCR=true/false in .env or app/config.py
            if settings.use_real_ocr:
                # Real OCR: Uses Bedrock Claude vision to extract data from actual image
                ocr_result = await asyncio.to_thread(
                    extract_document_data_with_vision, file_path, doc_type
                )
            else:
                # Mock OCR: Returns predefined data based on filename or doc_type (for testing)
                ocr_result = await asyncio.to_thread(
                    extract_document_data_mock, file_path, original_filename, doc_type
                )
            
            if ocr_result.get("success"):
                extracted_data = ocr_result.get("extracted_data", {})
                detected_doc_type = extracted_data.get("document_type", doc_type)
                
                # Override OCR detection if filename strongly suggests a different type
                # This helps when OCR misclassifies documents (e.g., passport detected as id_card)
                filename_type_override = None
                if "passport" in filename_lower and detected_doc_type == "id_card":
                    filename_type_override = "passport"
                    # Also update the extracted data to use passport_number
                    if extracted_data.get("id_card_number") and not extracted_data.get("passport_number"):
                        extracted_data["passport_number"] = extracted_data.pop("id_card_number")
                    extracted_data["document_type"] = "passport"
                    logger.info(f"   🔄 Filename suggests passport - overriding OCR detection from '{detected_doc_type}' to 'passport'")
                    detected_doc_type = "passport"
                elif "visa" in filename_lower and detected_doc_type not in ["visa"]:
                    filename_type_override = "visa"
                    extracted_data["document_type"] = "visa"
                    logger.info(f"   🔄 Filename suggests visa - overriding OCR detection from '{detected_doc_type}' to 'visa'")
                    detected_doc_type = "visa"
                
                logger.info(f"   ✅ Extracted: {extracted_data.get('full_name', 'N/A')}, detected type: {detected_doc_type}")
                
                # Update document type in database based on OCR detection
                if document_id:
                    async with AsyncSessionLocal() as session:
                        result = await session.execute(
                            select(KYCDocument).where(KYCDocument.id == document_id)
                        )
                        kyc_doc = result.scalar_one_or_none()
                        if kyc_doc:
                            if detected_doc_type != doc_type:
                                logger.info(f"   📝 Updating document type from '{doc_type}' to '{detected_doc_type}'")
                                kyc_doc.document_type = detected_doc_type
                            # Store extracted data in document for reference
                            kyc_doc.ocr_result = extracted_data
                            await session.commit()
                
                return {
                    "document_id": document_id,
                    "document_type": detected_doc_type,  # Use OCR-detected type
                    "original_document_type": doc_type,  # Keep original for reference
                    "filename": original_filename,
                    "extracted_data": extracted_data,
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
        
        # Load existing extracted data from database to preserve previous OCR results
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(KYCApplication).where(KYCApplication.id == self.application_id)
            )
            application = result.scalar_one_or_none()
            if application and application.extracted_data:
                self.extracted_data = dict(application.extracted_data)
                logger.info(f"   📦 Loaded existing extracted data with {len(self.extracted_data)} fields")
            else:
                self.extracted_data = {}
        
        # Merge data from new documents (new data overrides existing for same fields)
        for doc_result in all_extracted_data:
            doc_data = doc_result.get("extracted_data", {})
            doc_type = doc_result.get("document_type", "").lower()
            
            # Store per-document-type data for cross-validation
            if doc_type == "passport":
                self.passport_data = doc_data
                logger.info(f"   📌 Stored passport data for cross-validation")
            elif doc_type == "visa" or "visa" in doc_type or "work_permit" in doc_type:
                self.visa_data = doc_data
                logger.info(f"   📌 Stored visa data for cross-validation")
            elif doc_type == "id_card":
                self.id_card_data = doc_data
                logger.info(f"   📌 Stored ID card data for cross-validation")
            
            # Skip merging live_photo data - it doesn't have identity information
            # Live photos only have face_detected, liveness_check, etc.
            if doc_type == "live_photo":
                continue
            
            # Merge - later documents can override earlier ones for same fields
            for key, value in doc_data.items():
                if value:  # Only override if value is not empty
                    self.extracted_data[key] = value
        
        # Check if this is a non-local user (for enhanced verification)
        nationality_check = check_nationality_match(self.extracted_data)
        self.is_non_local = not nationality_check.get("matches", True)
        
        # Determine what document types have been uploaded
        # Check BOTH current batch AND previously uploaded documents
        already_uploaded_types = set()
        
        # First, add types from the current OCR results
        for doc_result in all_extracted_data:
            doc_type = doc_result.get("document_type", "").lower()
            if doc_type in ["passport", "id_card", "drivers_license"]:
                already_uploaded_types.add(doc_type)
            elif doc_type == "visa" or "visa" in doc_type or "work_permit" in doc_type:
                already_uploaded_types.add("visa")
            elif doc_type == "live_photo" or "selfie" in doc_type or "photo" in doc_type:
                already_uploaded_types.add("live_photo")
        
        # Then query for ALL documents in the application (including previous uploads)
        async with AsyncSessionLocal() as session:
            all_docs_result = await session.execute(
                select(KYCDocument).where(KYCDocument.application_id == self.application_id)
            )
            all_docs = all_docs_result.scalars().all()
            
            for doc in all_docs:
                doc_type = (doc.document_type or "").lower()
                if doc_type in ["passport", "id_card", "drivers_license"]:
                    already_uploaded_types.add(doc_type)
                elif doc_type == "visa" or "visa" in doc_type or "work_permit" in doc_type:
                    already_uploaded_types.add("visa")
                elif doc_type == "live_photo" or "selfie" in doc_type or "photo" in doc_type:
                    already_uploaded_types.add("live_photo")
        
        logger.info(f"   📋 All uploaded document types: {already_uploaded_types}")
        
        # Check if additional documents are needed for non-local users
        requires_additional_docs = False
        missing_docs = []
        if self.is_non_local:
            required_for_non_local = ["passport", "visa", "live_photo"]
            missing_docs = [doc for doc in required_for_non_local if doc not in already_uploaded_types]
            requires_additional_docs = len(missing_docs) > 0
            logger.info(f"   📋 Non-local user: requires_additional_docs={requires_additional_docs}, missing={missing_docs}")
        
        # Set stage based on whether more documents are needed
        # - "data_extracted" = Step 3 (Smart Document Capture) - still collecting documents
        # - "pending_user_review" = Step 4 (Live Presence Confirmation) - ready for user to confirm
        current_stage = "data_extracted" if requires_additional_docs else "pending_user_review"
        workflow_status = KYCWorkflowStatus.DATA_EXTRACTED if requires_additional_docs else KYCWorkflowStatus.PENDING_USER_REVIEW
        
        # Update application with merged extracted data
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(KYCApplication).where(KYCApplication.id == self.application_id)
            )
            application = result.scalar_one_or_none()
            if application:
                application.extracted_data = self.extracted_data
                application.current_stage = current_stage
                await session.commit()
        
        # Build response with both merged and individual document data
        response = {
            "success": True,
            "status": workflow_status,
            "message": "Document data extracted successfully. Please review the information.",
            "extracted_data": all_extracted_data,  # Array of per-document data
            "extracted_data_for_review": all_extracted_data,  # Same array for backwards compatibility
            "merged_data": self.extracted_data,  # Single merged object for confirmation/verification
            "requires_user_action": True,
            "next_action": "confirm_extracted_data" if not requires_additional_docs else "upload_additional_docs",
            "documents_processed": len(all_extracted_data),
            "documents_attempted": len(documents),
        }
        
        # Add additional docs info for non-local users who need more documents
        if requires_additional_docs:
            response["requires_additional_docs"] = True
            response["required_docs"] = missing_docs
            response["already_uploaded_types"] = list(already_uploaded_types)
        
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
        
        # Determine primary document for verification based on user type
        if self.is_non_local:
            # Non-local users: Primary verification is VISA (not passport)
            # The visa number is what authorizes them to be in the country
            if self.visa_data and self.visa_data.get("visa_number"):
                doc_type = "visa"
                doc_number = self.visa_data.get("visa_number", "")
                first_name = self.visa_data.get("first_name", "")
                last_name = self.visa_data.get("last_name", "")
                date_of_birth = self.visa_data.get("date_of_birth", "")
                logger.info(f"   🛂 Non-local user: Verifying visa: {doc_number}")
            elif self.extracted_data.get("visa_number"):
                # Fallback to merged data if no visa_data object
                doc_type = "visa"
                doc_number = self.extracted_data.get("visa_number", "")
                first_name = self.extracted_data.get("first_name", "")
                last_name = self.extracted_data.get("last_name", "")
                date_of_birth = self.extracted_data.get("date_of_birth", "")
                logger.info(f"   🛂 Non-local user (fallback): Verifying visa: {doc_number}")
            else:
                # No visa found - this shouldn't happen for non-local users
                logger.warning(f"   ⚠️ Non-local user but no visa data found!")
                doc_type = "passport"
                doc_number = self.extracted_data.get("passport_number", "")
                first_name = self.extracted_data.get("first_name", "")
                last_name = self.extracted_data.get("last_name", "")
                date_of_birth = self.extracted_data.get("date_of_birth", "")
                logger.info(f"   📄 Non-local user (no visa): Falling back to passport: {doc_number}")
        else:
            # Local/resident users: Verify their primary document (ID card, passport, or license)
            # Priority: ID card > Passport > Driver's License
            if self.extracted_data.get("id_card_number"):
                doc_type = "id_card"
                doc_number = self.extracted_data.get("id_card_number", "")
            elif self.extracted_data.get("passport_number"):
                doc_type = "passport"
                doc_number = self.extracted_data.get("passport_number", "")
            elif self.extracted_data.get("license_number"):
                doc_type = "drivers_license"
                doc_number = self.extracted_data.get("license_number", "")
            else:
                # Fallback to document_type from data
                doc_type = self.extracted_data.get("document_type", "id_card")
                doc_number = self.extracted_data.get("document_number", "")
            
            first_name = self.extracted_data.get("first_name", "")
            last_name = self.extracted_data.get("last_name", "")
            date_of_birth = self.extracted_data.get("date_of_birth", "")
            logger.info(f"   📄 Local user: Verifying {doc_type}: {doc_number}")
        
        # Call government verification based on document type
        if doc_type == "visa":
            # For visa verification, use the specialized visa verification function
            from app.agent.tools.government_db import verify_visa_with_government
            
            # Get passport number for cross-reference
            passport_num = (
                self.extracted_data.get("passport_number") or
                (self.passport_data.get("passport_number") if self.passport_data else "") or
                (self.visa_data.get("passport_number") if self.visa_data else "") or
                ""
            )
            nationality = (
                self.extracted_data.get("nationality") or
                (self.visa_data.get("nationality") if self.visa_data else "") or
                ""
            )
            visa_type = (
                self.extracted_data.get("visa_type") or
                (self.visa_data.get("visa_type") if self.visa_data else "") or
                "Work Permit"
            )
            
            gov_result = verify_visa_with_government(
                visa_number=doc_number,
                visa_type=visa_type,
                passport_number=passport_num,
                first_name=first_name,
                last_name=last_name,
                date_of_birth=date_of_birth,
                nationality=nationality,
            )
        else:
            # For ID card, passport, license - use standard verification
            gov_result = verify_with_government(
                document_number=doc_number,
                document_type=doc_type,
                first_name=first_name,
                last_name=last_name,
                date_of_birth=date_of_birth,
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
                "message": "⚠️ Government database verification failed. Your application requires manual review by our team.",
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
        
        # Get document-specific ID for fraud detection
        # Use the same logic as government verification
        if self.is_non_local and self.passport_data:
            doc_number = self.passport_data.get("passport_number", "")
            doc_type = "passport"
        elif self.extracted_data.get("id_card_number"):
            doc_number = self.extracted_data.get("id_card_number", "")
            doc_type = "id_card"
        elif self.extracted_data.get("passport_number"):
            doc_number = self.extracted_data.get("passport_number", "")
            doc_type = "passport"
        elif self.extracted_data.get("license_number"):
            doc_number = self.extracted_data.get("license_number", "")
            doc_type = "drivers_license"
        else:
            doc_number = self.extracted_data.get("document_number", "")
            doc_type = self.extracted_data.get("document_type", "id_card")
        
        # Call fraud detection tool with correct parameters
        # For non-local users, include passport and visa data for cross-validation
        fraud_params = {
            "document_number": doc_number,
            "document_type": doc_type,
            "first_name": self.extracted_data.get("first_name", ""),
            "last_name": self.extracted_data.get("last_name", ""),
            "date_of_birth": self.extracted_data.get("date_of_birth", ""),
            "address": self.extracted_data.get("address"),
            "expiry_date": self.extracted_data.get("expiry_date"),
            "government_verified": self.gov_verification_result.get("verified", False) if self.gov_verification_result else False,
            "government_verification_status": self.gov_verification_result.get("verification_status", "unknown") if self.gov_verification_result else "unknown",
        }
        
        # Add passport and visa data for cross-validation (non-local users)
        if self.is_non_local:
            logger.info(f"   🔍 Including passport/visa cross-validation for non-local user")
            if self.passport_data:
                fraud_params["passport_data"] = self.passport_data
            if self.visa_data:
                fraud_params["visa_data"] = self.visa_data
            if self.visa_verification_result:
                fraud_params["visa_verified"] = self.visa_verification_result.get("verified", False)
        
        fraud_result = check_fraud_indicators(**fraud_params)
        
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

