"""User management tools for the chat agent.

Uses Strands Agent state to maintain context across tool calls:
https://strandsagents.com/latest/documentation/docs/user-guide/concepts/agents/state/
"""

import base64
import logging
import uuid
from pathlib import Path
from datetime import datetime, timezone

from strands import tool

logger = logging.getLogger(__name__)
from strands.types.tools import ToolContext
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.db.database import AsyncSessionLocal
from app.db.models import User, KYCApplication, KYCDocument, KYCStage, generate_member_id
from app.services.password import hash_password
from app.config import settings
from app.utils.async_helpers import run_sync


# Limit per request (not per application - users can upload more over multiple requests)
MAX_DOCUMENTS_PER_REQUEST = 3
# No hard limit per application, but we track count for user feedback
MAX_DOCUMENTS_PER_APPLICATION = 10  # Soft limit for display purposes


@tool(context=True)
def register_user(email: str, phone: str, password: str, tool_context: ToolContext) -> dict:
    """
    Register a new user account with pending KYC status.
    
    Use this tool when a user wants to create a new account or sign up.
    The user will need to complete KYC verification after registration.
    
    Args:
        email: User's email address (must be unique)
        phone: User's phone number
        password: User's password (will be securely hashed)
        
    Returns:
        Dictionary with user details or error message
    """
    async def _register():
        async with AsyncSessionLocal() as session:
            # Check if email exists
            result = await session.execute(
                select(User).where(User.email == email)
            )
            if result.scalar_one_or_none():
                return {
                    "success": False,
                    "error": "Email already registered. Please use a different email or login.",
                }
            
            # Generate auto_id and member_id (same as REST API signup)
            max_id_result = await session.execute(
                select(func.max(User.auto_id))
            )
            max_id = max_id_result.scalar() or 0
            next_auto_id = max_id + 1
            
            # Create user
            user = User(
                email=email,
                phone=phone,
                password_hash=hash_password(password),
                kyc_status="pending",
                auto_id=next_auto_id,
                member_id=generate_member_id(next_auto_id),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            
            return {
                "success": True,
                "user_id": user.id,
                "email": user.email,
                "phone": user.phone,
                "kyc_status": user.kyc_status,
                "message": "Account created successfully! You can now start the identity verification process.",
            }
    
    try:
        result = run_sync(_register())
        # Store user info in agent state for subsequent tool calls
        if result.get("success"):
            tool_context.agent.state.set("user_id", result["user_id"])
            tool_context.agent.state.set("user_email", result["email"])
            tool_context.agent.state.set("kyc_status", result["kyc_status"])
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def get_user_status(user_id: str) -> dict:
    """
    Get user account and KYC status by user ID.
    
    Use this tool to check a user's current status, including their
    KYC verification status. Use the user_id you remembered from registration.
    
    Args:
        user_id: The user's unique identifier (from registration)
        
    Returns:
        Dictionary with user status details
    """
    async def _get_status():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                return {
                    "success": False,
                    "error": "User not found. Please register first.",
                }
            
            return {
                "success": True,
                "user_id": user.id,
                "email": user.email,
                "phone": user.phone,
                "kyc_status": user.kyc_status,
                "member_id": user.member_id,
                "created_at": str(user.created_at),
            }
    
    try:
        return run_sync(_get_status())
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(context=True)
def find_user_by_email(email: str, tool_context: ToolContext) -> dict:
    """
    Find a user account by email address.
    
    Use this tool when a returning user provides their email to look up
    their account. This stores user_id in agent state for subsequent calls.
    
    Args:
        email: The user's email address
        
    Returns:
        Dictionary with user details including user_id for subsequent calls
    """
    async def _find_user():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.email == email)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                return {
                    "success": False,
                    "error": f"No account found with email {email}. Would you like to register?",
                }
            
            return {
                "success": True,
                "user_id": user.id,
                "email": user.email,
                "phone": user.phone,
                "kyc_status": user.kyc_status,
                "member_id": user.member_id,
                "created_at": str(user.created_at),
                "message": "Account found! You can now check status or continue with KYC.",
            }
    
    try:
        result = run_sync(_find_user())
        # Store user info in agent state
        if result.get("success"):
            tool_context.agent.state.set("user_id", result["user_id"])
            tool_context.agent.state.set("user_email", result["email"])
            tool_context.agent.state.set("kyc_status", result["kyc_status"])
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(context=True)
def initiate_kyc_process(tool_context: ToolContext, user_id: str | None = None) -> dict:
    """
    Start the identity verification process for a user.
    
    Use this tool when a user wants to begin their identity verification.
    This creates a new KYC application that tracks the verification progress.
    Uses user_id from agent state if not provided.
    
    Args:
        user_id: The user's unique identifier (optional, uses state if not provided)
        
    Returns:
        Dictionary with KYC application details
    """
    logger.info("🚀 [Initiate KYC] Tool called - starting KYC process")
    
    # Get user_id from state if not provided
    effective_user_id = user_id or tool_context.agent.state.get("user_id")
    logger.info(f"   👤 User ID: {effective_user_id}")
    if not effective_user_id:
        return {
            "success": False,
            "error": "No user_id provided or found in session. Please register or login first.",
        }
    
    async def _initiate():
        async with AsyncSessionLocal() as session:
            from sqlalchemy.orm import selectinload
            
            # Find user
            result = await session.execute(
                select(User).where(User.id == effective_user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                return {
                    "success": False,
                    "error": "User not found. Please register first.",
                }
            
            # Check for existing active application (exclude failed/completed)
            # Use order_by + first() to handle multiple applications gracefully
            existing = await session.execute(
                select(KYCApplication)
                .where(KYCApplication.user_id == effective_user_id)
                .where(KYCApplication.status.in_(["initiated", "documents_uploaded", "processing"]))
                .options(
                    selectinload(KYCApplication.documents),
                    selectinload(KYCApplication.stages),
                )
                .order_by(KYCApplication.created_at.desc())
            )
            existing_app = existing.scalars().first()
            
            # TODO: Resume handling disabled for now - uncomment to re-enable
            # if existing_app:
            #     # Build full context for resume
            #     uploaded_docs = [
            #         {"type": doc.document_type, "filename": doc.original_filename}
            #         for doc in existing_app.documents
            #     ]
            #     uploaded_types = list(set(doc.document_type for doc in existing_app.documents if doc.document_type))
            #     completed_stages = [s.stage_name for s in existing_app.stages if s.status == "completed"]
            #     
            #     # Extract per-document-type data from OCR results for state restoration
            #     passport_data = None
            #     visa_data = None
            #     id_card_data = None
            #     
            #     for doc in existing_app.documents:
            #         doc_type = (doc.document_type or "").lower()
            #         ocr_result = doc.ocr_result  # Stored during OCR processing
            #         
            #         if ocr_result:
            #             if doc_type == "passport":
            #                 passport_data = ocr_result
            #             elif doc_type == "visa" or "visa" in doc_type:
            #                 visa_data = ocr_result
            #             elif doc_type == "id_card":
            #                 id_card_data = ocr_result
            #     
            #     # Compute is_non_local from extracted data
            #     is_non_local = False
            #     if existing_app.extracted_data:
            #         from app.agent.kyc_workflow import check_nationality_match
            #         nationality_check = check_nationality_match(existing_app.extracted_data)
            #         is_non_local = not nationality_check.get("matches", True)
            #     
            #     # Determine next action based on current stage
            #     current_stage = existing_app.current_stage or "initiated"
            #     next_action = None
            #     resume_message = ""
            #     
            #     if current_stage == "initiated":
            #         next_action = "file_upload"
            #         resume_message = "Please upload your identity document to continue."
            #     elif current_stage == "document_uploaded":
            #         next_action = "file_upload"
            #         resume_message = "Your documents are uploaded. You can add more or proceed."
            #     elif current_stage == "pending_user_review":
            #         next_action = "confirm_data"
            #         resume_message = "Please review and confirm your extracted information."
            #     elif current_stage == "user_confirmed":
            #         resume_message = "Your verification is in progress. Please wait."
            #     elif current_stage in ["gov_verification", "fraud_check", "decision_made"]:
            #         resume_message = "Your verification is being processed. Please wait for the result."
            #     else:
            #         resume_message = "Let's continue with your verification."
            #     
            #     logger.info(f"   🔄 Resuming existing application: {existing_app.id}, stage: {current_stage}")
            #     
            #     return {
            #         "success": True,
            #         "existing": True,
            #         "application_id": existing_app.id,
            #         "status": existing_app.status,
            #         "current_stage": current_stage,
            #         "uploaded_documents": uploaded_docs,
            #         "uploaded_types": uploaded_types,
            #         "completed_stages": completed_stages,
            #         "extracted_data": existing_app.extracted_data,
            #         "passport_data": passport_data,
            #         "visa_data": visa_data,
            #         "id_card_data": id_card_data,
            #         "is_non_local": is_non_local,
            #         "next_action": next_action,
            #         "message": f"Welcome back! {resume_message}",
            #     }
            
            # For now, just log if existing app found (resume disabled)
            if existing_app:
                logger.info(f"   ℹ️ Found existing application: {existing_app.id}, but resume is disabled - creating new one")
            
            # Check if user has a rejected application (allow new application)
            rejected = await session.execute(
                select(KYCApplication)
                .where(KYCApplication.user_id == effective_user_id)
                .where(KYCApplication.status == "failed")
                .order_by(KYCApplication.created_at.desc())
            )
            rejected_app = rejected.scalars().first()
            if rejected_app:
                logger.info(f"   🔄 Previous application was rejected, creating new one")
            
            # Create new application
            application = KYCApplication(
                user_id=effective_user_id,
                status="initiated",
                current_stage="initiated",
            )
            session.add(application)
            
            # Update user status
            user.kyc_status = "in_progress"
            
            await session.commit()
            await session.refresh(application)
            
            return {
                "success": True,
                "existing": False,
                "application_id": application.id,
                "status": application.status,
                "current_stage": "initiated",
                "next_action": "file_upload",
                "message": "KYC process initiated! Please upload your identity document.",
            }
    
    try:
        result = run_sync(_initiate())
        # Store/restore state based on result
        if result.get("success"):
            app_id = result["application_id"]
            tool_context.agent.state.set("application_id", app_id)
            tool_context.agent.state.set("kyc_status", "in_progress")
            
            # Set workflow stage based on current stage
            current_stage = result.get("current_stage", "initiated")
            tool_context.agent.state.set("workflow_stage", current_stage)
            
            # TODO: Resume state restoration disabled for now - uncomment to re-enable
            # if result.get("existing"):
            #     if result.get("extracted_data"):
            #         tool_context.agent.state.set("merged_extracted_data", result["extracted_data"])
            #         logger.info(f"   📦 Restored extracted data from previous session")
            #     
            #     # Restore per-document-type data for cross-validation
            #     if result.get("passport_data"):
            #         tool_context.agent.state.set("passport_data", result["passport_data"])
            #         logger.info(f"   📦 Restored passport_data from DB")
            #     if result.get("visa_data"):
            #         tool_context.agent.state.set("visa_data", result["visa_data"])
            #         logger.info(f"   📦 Restored visa_data from DB")
            #     if result.get("id_card_data"):
            #         tool_context.agent.state.set("id_card_data", result["id_card_data"])
            #         logger.info(f"   📦 Restored id_card_data from DB")
            #     
            #     # Restore is_non_local flag
            #     tool_context.agent.state.set("is_non_local", result.get("is_non_local", False))
            #     logger.info(f"   🌍 Restored is_non_local={result.get('is_non_local', False)} from DB")
            
            logger.info(f"   ✅ KYC application {'resumed' if result.get('existing') else 'created'}: {app_id}")
        else:
            logger.warning(f"   ❌ Failed to initiate KYC: {result.get('error')}")
        return result
    except Exception as e:
        logger.error(f"   ❌ Exception in initiate_kyc_process: {e}")
        return {"success": False, "error": str(e)}


@tool
def check_kyc_application_status(application_id: str) -> dict:
    """
    Check the status of a KYC application.
    
    Use this tool to get detailed status of a KYC verification application,
    including all processing stages and the final decision.
    
    Args:
        application_id: The KYC application ID
        
    Returns:
        Dictionary with detailed application status
    """
    async def _check_status():
        async with AsyncSessionLocal() as session:
            from sqlalchemy.orm import selectinload
            
            result = await session.execute(
                select(KYCApplication)
                .where(KYCApplication.id == application_id)
                .options(
                    selectinload(KYCApplication.documents),
                    selectinload(KYCApplication.stages),
                )
            )
            app = result.scalar_one_or_none()
            
            if not app:
                return {
                    "success": False,
                    "error": "Application not found. Please check the application ID.",
                }
            
            # Format stages
            stages = []
            for stage in sorted(app.stages, key=lambda s: s.created_at):
                stages.append({
                    "stage": stage.stage_name,
                    "status": stage.status,
                    "completed_at": str(stage.completed_at) if stage.completed_at else None,
                })
            
            # Format documents
            documents = []
            for doc in app.documents:
                documents.append({
                    "type": doc.document_type,
                    "filename": doc.original_filename,
                    "uploaded_at": str(doc.uploaded_at),
                })
            
            return {
                "success": True,
                "application_id": app.id,
                "status": app.status,
                "current_stage": app.current_stage,
                "decision": app.decision,
                "decision_reason": app.decision_reason,
                "documents_uploaded": len(documents),
                "documents": documents,
                "stages_completed": len([s for s in stages if s["status"] == "completed"]),
                "stages": stages,
                "created_at": str(app.created_at),
            }
    
    try:
        return run_sync(_check_status())
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def get_user_kyc_applications(user_id: str) -> dict:
    """
    Get all KYC applications for a user.
    
    Use this tool to list all KYC verification attempts for a user,
    including past rejected applications and current active ones.
    
    Args:
        user_id: The user's unique identifier
        
    Returns:
        Dictionary with list of all applications
    """
    async def _get_applications():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(KYCApplication)
                .where(KYCApplication.user_id == user_id)
                .order_by(KYCApplication.created_at.desc())
            )
            applications = result.scalars().all()
            
            if not applications:
                return {
                    "success": True,
                    "applications": [],
                    "message": "No applications found. Start the identity verification process to begin.",
                }
            
            apps_list = []
            for app in applications:
                apps_list.append({
                    "application_id": app.id,
                    "status": app.status,
                    "decision": app.decision,
                    "current_stage": app.current_stage,
                    "created_at": str(app.created_at),
                })
            
            return {
                "success": True,
                "total_applications": len(apps_list),
                "applications": apps_list,
            }
    
    try:
        return run_sync(_get_applications())
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def get_kyc_requirements() -> dict:
    """
    Get information about KYC requirements and process.
    
    Use this tool to explain what documents are needed for KYC verification
    and how the process works.
    
    Returns:
        Dictionary with KYC requirements and process information
    """
    return {
        "success": True,
        "requirements": {
            "required_documents": [
                {
                    "type": "id_card",
                    "description": "Government-issued ID card with photo",
                    "required": True,
                },
                {
                    "type": "passport",
                    "description": "Valid passport (can be used instead of ID card)",
                    "required": False,
                },
            ],
            "document_formats": ["JPEG", "PNG", "PDF", "WebP"],
            "max_file_size": "10 MB",
        },
        "process_steps": [
            "1. Register an account with email and phone",
            "2. Initiate the KYC process",
            "3. Upload your ID card or passport",
            "4. Our AI system will verify your documents",
            "5. Receive approval or feedback within minutes",
        ],
        "verification_stages": [
            "Document Upload - Upload your identity documents",
            "OCR Processing - Extract information from documents",
            "Data Extraction - Parse and validate identity data",
            "Government Verification - Verify against official records",
            "Fraud Detection - Check for any fraud indicators",
            "Final Decision - Approve or request additional information",
        ],
        "tips": [
            "Ensure your document is clearly visible and not blurry",
            "Make sure all text on the document is readable",
            "Use a recent document that hasn't expired",
            "Avoid glare or shadows on the document",
        ],
        "max_documents": MAX_DOCUMENTS_PER_APPLICATION,
    }


@tool(context=True)
def upload_kyc_document(
    document_type: str,
    document_data: str,
    filename: str,
    tool_context: ToolContext,
    application_id: str | None = None,
) -> dict:
    """
    Upload a document for KYC verification.
    
    Use this tool when a user wants to upload their identity document.
    The document should be provided as base64-encoded data.
    Maximum 3 documents per request (no total limit per application).
    Uses application_id from agent state if not provided.
    
    Args:
        document_type: Type of document - must be 'id_card' or 'passport'
        document_data: Base64-encoded document image data
        filename: Original filename (e.g., 'my_id.jpg')
        application_id: The KYC application ID (optional, uses state if not provided)
        
    Returns:
        Dictionary with upload result and document count
    """
    # Get application_id from state if not provided
    effective_app_id = application_id or tool_context.agent.state.get("application_id")
    if not effective_app_id:
        return {
            "success": False,
            "error": "No application_id provided or found in session. Please initiate KYC first.",
        }
    
    async def _upload():
        async with AsyncSessionLocal() as session:
            # Find application with documents
            result = await session.execute(
                select(KYCApplication)
                .where(KYCApplication.id == effective_app_id)
                .options(selectinload(KYCApplication.documents))
            )
            application = result.scalar_one_or_none()
            
            if not application:
                return {
                    "success": False,
                    "error": "KYC application not found. Please initiate KYC first.",
                }
            
            if application.status in ["completed", "failed"]:
                return {
                    "success": False,
                    "error": f"Cannot upload documents - application already {application.status}.",
                }
            
            # Note: No total limit per application. Limit is per-request (handled in API endpoint).
            
            # Validate document type
            valid_types = ["id_card", "passport"]
            if document_type not in valid_types:
                return {
                    "success": False,
                    "error": f"Invalid document type. Must be one of: {valid_types}",
                }
            
            # Decode base64 data
            try:
                file_content = base64.b64decode(document_data)
            except Exception as e:
                return {
                    "success": False,
                    "error": "Invalid document data. Please provide valid base64-encoded image.",
                }
            
            # Validate file size (max 10MB)
            max_size = 10 * 1024 * 1024
            if len(file_content) > max_size:
                return {
                    "success": False,
                    "error": f"File too large. Maximum size is 10MB.",
                }
            
            # Determine file extension and mime type
            # Note: PDF is not supported - Bedrock vision API only accepts images
            ext = Path(filename).suffix.lower() if filename else ".jpg"
            if ext == ".pdf":
                return {
                    "success": False,
                    "error": "PDF files are not supported. Please upload an image file (JPEG, PNG, GIF, or WebP).",
                }
            if ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                ext = ".jpg"
            
            mime_types = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }
            mime_type = mime_types.get(ext, "image/jpeg")
            
            # Create upload directory
            upload_dir = Path(settings.upload_dir) / effective_app_id
            upload_dir.mkdir(parents=True, exist_ok=True)
            
            # Preserve original filename with unique suffix
            # This allows OCR tool to detect test hints in filename (e.g., "john", "success")
            original_stem = Path(filename).stem if filename else document_type
            unique_suffix = uuid.uuid4().hex[:8]
            unique_filename = f"{original_stem}_{unique_suffix}{ext}"
            file_path = upload_dir / unique_filename
            
            # Save file
            with open(file_path, "wb") as f:
                f.write(file_content)
            
            # Create document record
            document = KYCDocument(
                application_id=effective_app_id,
                document_type=document_type,
                file_path=str(file_path),
                original_filename=filename or unique_filename,
                mime_type=mime_type,
            )
            session.add(document)
            
            # Count documents before adding this one
            current_count = len(application.documents)
            
            # Update application status
            application.status = "documents_uploaded"
            application.current_stage = "document_uploaded"
            application.updated_at = datetime.now(timezone.utc)
            
            await session.commit()
            
            # Calculate new totals
            new_count = current_count + 1  # +1 because we just added one
            remaining = max(0, MAX_DOCUMENTS_PER_APPLICATION - new_count)
            
            return {
                "success": True,
                "document_id": document.id,
                "document_type": document_type,
                "filename": filename,
                "documents_uploaded": new_count,
                "remaining_slots": remaining,
                "message": f"Document uploaded successfully! You now have {new_count} document(s). " +
                          (f"You can upload {remaining} more." if remaining > 0 else "Maximum documents reached."),
            }
    
    try:
        result = run_sync(_upload())
        # Update state with document count
        if result.get("success"):
            tool_context.agent.state.set("documents_uploaded", result["documents_uploaded"])
            tool_context.agent.state.set("workflow_stage", "documents_uploaded")
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(context=True)
def get_uploaded_documents(tool_context: ToolContext, application_id: str | None = None) -> dict:
    """
    Get list of documents uploaded for a KYC application.
    
    Use this tool to check what documents have been uploaded and
    how many more can be added. Uses application_id from agent state if not provided.
    
    Args:
        application_id: The KYC application ID (optional, uses state if not provided)
        
    Returns:
        Dictionary with list of uploaded documents
    """
    # Get application_id from state if not provided
    effective_app_id = application_id or tool_context.agent.state.get("application_id")
    if not effective_app_id:
        return {
            "success": False,
            "error": "No application_id provided or found in session. Please initiate KYC first.",
        }
    
    async def _get_docs():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(KYCApplication)
                .where(KYCApplication.id == effective_app_id)
                .options(selectinload(KYCApplication.documents))
            )
            application = result.scalar_one_or_none()
            
            if not application:
                return {
                    "success": False,
                    "error": "KYC application not found.",
                }
            
            documents = []
            for doc in application.documents:
                documents.append({
                    "document_type": doc.document_type,
                    "filename": doc.original_filename,
                    "uploaded_at": str(doc.uploaded_at),
                })
            
            return {
                "success": True,
                "application_id": effective_app_id,
                "documents_uploaded": len(documents),
                "max_documents": MAX_DOCUMENTS_PER_APPLICATION,
                "remaining_slots": MAX_DOCUMENTS_PER_APPLICATION - len(documents),
                "documents": documents,
                "can_upload_more": len(documents) < MAX_DOCUMENTS_PER_APPLICATION,
            }
    
    try:
        return run_sync(_get_docs())
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(context=True)
def run_ocr_extraction(tool_context: ToolContext, application_id: str | None = None, document_ids: str | None = None) -> dict:
    """
    Run OCR extraction on uploaded documents and return data for user review.
    
    Use this tool after the user has uploaded documents. It extracts identity
    information from the documents and presents it for the user to review
    and confirm before verification.
    
    IMPORTANT: If document_ids is provided, ONLY those documents will be processed.
    This is the preferred approach when documents were just uploaded in the current request.
    
    Args:
        application_id: The KYC application ID (optional, uses state if not provided)
        document_ids: Comma-separated list of document IDs to process (optional, 
                     if not provided, processes ALL documents in the application)
        
    Returns:
        Dictionary with extracted data for user review
    """
    from app.agent.kyc_workflow import KYCWorkflow
    
    # Get application_id from state if not provided
    effective_app_id = application_id or tool_context.agent.state.get("application_id")
    if not effective_app_id:
        return {
            "success": False,
            "error": "No application_id provided or found in session. Please initiate KYC first.",
        }
    
    # Parse document_ids if provided
    target_doc_ids = None
    if document_ids:
        target_doc_ids = [doc_id.strip() for doc_id in document_ids.split(",") if doc_id.strip()]
    
    async def _run_ocr():
        async with AsyncSessionLocal() as session:
            # Get application with documents
            result = await session.execute(
                select(KYCApplication)
                .where(KYCApplication.id == effective_app_id)
                .options(selectinload(KYCApplication.documents))
            )
            application = result.scalar_one_or_none()
            
            if not application:
                return {"success": False, "error": "KYC application not found."}
            
            if not application.documents:
                return {"success": False, "error": "No documents uploaded. Please upload at least one document first."}
            
            if application.status in ["completed", "failed"]:
                return {
                    "success": False,
                    "error": f"Application already processed. Status: {application.status}, Decision: {application.decision}",
                }
            
            # Filter documents if specific IDs were provided
            if target_doc_ids:
                # Only process documents with matching IDs (current request documents)
                filtered_docs = [doc for doc in application.documents if doc.id in target_doc_ids]
                if not filtered_docs:
                    return {"success": False, "error": f"No documents found with the specified IDs: {document_ids}"}
            else:
                # Process all documents (legacy behavior)
                filtered_docs = application.documents
            
            # Prepare documents for workflow
            documents = [
                {
                    "file_path": doc.file_path,
                    "document_type": doc.document_type,
                    "original_filename": doc.original_filename,
                    "document_id": doc.id,
                }
                for doc in filtered_docs
            ]
            
            # Run OCR workflow step
            workflow = KYCWorkflow(effective_app_id)
            ocr_result = await workflow.run_ocr_step(documents)
            
            if not ocr_result.get("success", False):
                return {
                    "success": False,
                    "error": ocr_result.get("error", "OCR extraction failed"),
                }
            
            # Get extracted data for review - this is an array with each document's data
            extracted_data = ocr_result.get("extracted_data_for_review", [])
            
            # Also get the merged data for display
            merged_data = ocr_result.get("merged_data", {})
            
            # Check nationality against target country
            from app.agent.kyc_workflow import check_nationality_match
            nationality_check = check_nationality_match(merged_data)
            
            # Build set of already uploaded document types
            # Use OCR-detected types from the current extraction results (most accurate)
            already_uploaded_types = set()
            
            # First, add types from the current OCR results (these are the freshest)
            for doc_result in extracted_data:
                doc_type = (doc_result.get("document_type") or "").lower()
                # Normalize document types
                if doc_type in ["passport", "id_card", "drivers_license"]:
                    already_uploaded_types.add(doc_type)
                elif doc_type == "visa" or "visa" in doc_type or "work_permit" in doc_type:
                    already_uploaded_types.add("visa")
                elif doc_type == "live_photo" or "selfie" in doc_type:
                    already_uploaded_types.add("live_photo")
            
            # Then query for any previously uploaded documents (from earlier requests)
            # Use a fresh session to get the latest data
            async with AsyncSessionLocal() as fresh_session:
                all_docs_result = await fresh_session.execute(
                    select(KYCDocument).where(KYCDocument.application_id == effective_app_id)
                )
                all_docs = all_docs_result.scalars().all()
                
                for doc in all_docs:
                    doc_type = doc.document_type.lower() if doc.document_type else ""
                    # Normalize document types
                    if doc_type in ["passport", "id_card", "drivers_license"]:
                        already_uploaded_types.add(doc_type)
                    elif doc_type == "visa" or "visa" in doc_type or "work_permit" in doc_type:
                        already_uploaded_types.add("visa")
                    elif doc_type == "live_photo" or "selfie" in doc_type or "photo" in doc_type:
                        already_uploaded_types.add("live_photo")
            
            logger.info(f"   📋 Already uploaded document types: {already_uploaded_types}")
            
            # For non-locals, check what additional docs are still needed BEFORE setting status
            requires_additional_docs = False
            missing_docs = []
            if not nationality_check["matches"]:
                required_for_non_local = ["passport", "visa", "live_photo"]
                missing_docs = [doc for doc in required_for_non_local if doc not in already_uploaded_types]
                requires_additional_docs = len(missing_docs) > 0
            
            # Set status based on whether more documents are needed
            # - "data_extracted" = Step 3 (Smart Document Capture) - still collecting documents
            # - "pending_user_review" = Step 4 (Live Presence Confirmation) - ready for user to confirm
            result_status = "data_extracted" if requires_additional_docs else "pending_user_review"
            
            result_data = {
                "success": True,
                "status": result_status,
                "message": "I've extracted the following information from your documents. Please review and confirm if it's correct:",
                "extracted_data": extracted_data,  # Array of per-document data
                "merged_data": merged_data,  # Single merged object for display
                "documents_processed": len(extracted_data),
                "nationality_check": nationality_check,  # Nationality validation result
                "already_uploaded_types": list(already_uploaded_types),  # Types already in application
            }
            
            # Add appropriate next step based on nationality
            if nationality_check["matches"]:
                result_data["next_step"] = "Please confirm if this information is correct, or let me know what needs to be corrected."
            else:
                if missing_docs:
                    # Still need more documents - stay in Step 3
                    result_data["requires_additional_docs"] = True
                    result_data["required_docs"] = missing_docs
                    
                    # Build friendly message listing what's needed
                    doc_names = {
                        "passport": "passport",
                        "visa": "visa or work permit",
                        "live_photo": "selfie photo"
                    }
                    missing_names = [doc_names.get(d, d) for d in missing_docs]
                    
                    if len(missing_names) == 1:
                        docs_str = missing_names[0]
                    else:
                        docs_str = ", ".join(missing_names[:-1]) + " and " + missing_names[-1]
                    
                    result_data["next_step"] = f"As you are from {nationality_check['detected_nationality']}, we still need your {docs_str} to complete verification."
                else:
                    # All additional docs are uploaded, proceed to confirmation
                    result_data["next_step"] = "All required documents have been uploaded. Please confirm if the extracted information is correct."
                    result_data["all_docs_uploaded"] = True
            
            return result_data
    
    try:
        # OCR can take 60+ seconds for complex documents, increase timeout
        result = run_sync(_run_ocr(), timeout=120)
        # Update state based on OCR result
        if result.get("success"):
            tool_context.agent.state.set("workflow_stage", "ocr_completed")
            if result.get("extracted_data"):
                # Merge new extracted data with existing data in state
                existing_data = tool_context.agent.state.get("extracted_data") or []
                new_data = result["extracted_data"]
                
                # Create a dict of existing docs by document_id for efficient lookup
                existing_by_id = {doc.get("document_id"): doc for doc in existing_data if doc.get("document_id")}
                
                # Merge: add new docs, update existing ones
                for new_doc in new_data:
                    doc_id = new_doc.get("document_id")
                    if doc_id:
                        existing_by_id[doc_id] = new_doc
                    else:
                        existing_data.append(new_doc)
                
                merged_data = list(existing_by_id.values())
                tool_context.agent.state.set("extracted_data", merged_data)
                logger.info(f"   📦 State now contains {len(merged_data)} document(s)")
                
                # Store per-document-type data in state for cross-validation during verification
                # This allows confirm_and_verify to restore passport_data, visa_data, etc.
                for doc_result in new_data:
                    doc_type = (doc_result.get("document_type") or "").lower()
                    doc_extracted = doc_result.get("extracted_data", {})
                    
                    if doc_type == "passport":
                        # Merge with existing passport data
                        existing_passport = tool_context.agent.state.get("passport_data") or {}
                        existing_passport.update(doc_extracted)
                        tool_context.agent.state.set("passport_data", existing_passport)
                        logger.info(f"   📌 Stored passport data in state")
                    elif doc_type == "visa" or "visa" in doc_type or "work_permit" in doc_type:
                        # Merge with existing visa data
                        existing_visa = tool_context.agent.state.get("visa_data") or {}
                        existing_visa.update(doc_extracted)
                        tool_context.agent.state.set("visa_data", existing_visa)
                        logger.info(f"   📌 Stored visa data in state")
                    elif doc_type == "id_card":
                        # Merge with existing id card data
                        existing_id = tool_context.agent.state.get("id_card_data") or {}
                        existing_id.update(doc_extracted)
                        tool_context.agent.state.set("id_card_data", existing_id)
                        logger.info(f"   📌 Stored ID card data in state")
                
                # Store merged data for quick access
                if result.get("merged_data"):
                    tool_context.agent.state.set("merged_extracted_data", result["merged_data"])
                
                # Store nationality check result
                if result.get("nationality_check"):
                    is_non_local = not result["nationality_check"].get("matches", True)
                    tool_context.agent.state.set("is_non_local", is_non_local)
                    logger.info(f"   🌍 User is {'non-local' if is_non_local else 'local'}")
        else:
            tool_context.agent.state.set("workflow_stage", "ocr_failed")
        return result
    except TimeoutError:
        tool_context.agent.state.set("workflow_stage", "ocr_failed")
        return {"success": False, "error": "OCR processing timed out. Please try again or upload a clearer image."}
    except Exception as e:
        tool_context.agent.state.set("workflow_stage", "ocr_failed")
        return {"success": False, "error": str(e)}


@tool(context=True)
def confirm_and_verify(tool_context: ToolContext, user_confirmed: bool = True, corrections: dict | None = None, application_id: str | None = None) -> dict:
    """
    Confirm extracted data and run full verification (government DB + fraud check + decision).
    
    Use this tool after the user has reviewed the OCR-extracted data and confirms it's correct.
    This runs the complete verification workflow and returns the final decision.
    
    Args:
        user_confirmed: Whether the user confirms the extracted data is correct
        corrections: Optional dict with corrected fields if user made changes
        application_id: The KYC application ID (optional, uses state if not provided)
        
    Returns:
        Dictionary with final verification decision
    """
    from app.agent.kyc_workflow import KYCWorkflow
    
    # Get application_id from state if not provided
    effective_app_id = application_id or tool_context.agent.state.get("application_id")
    if not effective_app_id:
        return {
            "success": False,
            "error": "No application_id provided or found in session. Please initiate KYC first.",
        }
    
    if not user_confirmed:
        return {
            "success": False,
            "message": "Verification cancelled. Please provide the correct information or upload new documents.",
        }
    
    async def _verify():
        async with AsyncSessionLocal() as session:
            # Get application
            result = await session.execute(
                select(KYCApplication)
                .where(KYCApplication.id == effective_app_id)
            )
            application = result.scalar_one_or_none()
            
            if not application:
                return {"success": False, "error": "KYC application not found."}
            
            if application.status in ["completed", "failed"]:
                return {
                    "success": False,
                    "error": f"Application already processed. Status: {application.status}, Decision: {application.decision}",
                }
            
            # Apply corrections if provided
            extracted_data = application.extracted_data or {}
            if corrections:
                extracted_data.update(corrections)
                application.extracted_data = extracted_data
                await session.commit()
        
        # Run full verification workflow
        workflow = KYCWorkflow(effective_app_id)
        
        # Set extracted data in workflow
        workflow.extracted_data = extracted_data
        
        return workflow
    
    try:
        # Verification can take time for gov DB and fraud checks, increase timeout
        workflow = run_sync(_verify(), timeout=120)
        
        # Check if we got an error dict instead of a workflow
        if isinstance(workflow, dict):
            return workflow  # Return error
        
        # Restore per-document-type data from agent state
        # This is needed for cross-validation during fraud detection
        passport_data = tool_context.agent.state.get("passport_data")
        visa_data = tool_context.agent.state.get("visa_data")
        id_card_data = tool_context.agent.state.get("id_card_data")
        is_non_local = tool_context.agent.state.get("is_non_local") or False
        
        if passport_data:
            workflow.passport_data = passport_data
            logger.info(f"   📦 Restored passport_data from state")
        if visa_data:
            workflow.visa_data = visa_data
            logger.info(f"   📦 Restored visa_data from state")
        if id_card_data:
            workflow.id_card_data = id_card_data
            logger.info(f"   📦 Restored id_card_data from state")
        
        workflow.is_non_local = is_non_local
        logger.info(f"   🌍 Restored is_non_local={is_non_local} from state")
        
        # Confirm data (auto-confirm since data was already set above)
        logger.info(f"   ✅ Confirming user data...")
        confirm_result = run_sync(workflow.confirm_user_data(confirmed=True), timeout=30)
        logger.info(f"   ✅ Confirm result: {confirm_result}")
        
        # Run verification
        logger.info(f"   🔄 Running full verification...")
        result = run_sync(workflow.run_full_verification(), timeout=120)
        logger.info(f"   🔄 Verification result: {result}")
        
        # Update state with final result
        # Handle both string and enum status values
        status = result.get("status")
        status_str = str(status.value) if hasattr(status, 'value') else str(status)
        
        if status_str == "approved" or "approved" in status_str.lower():
            tool_context.agent.state.set("workflow_stage", "completed")
            tool_context.agent.state.set("kyc_status", "approved")
            tool_context.agent.state.set("kyc_decision", "approved")
        elif "rejected" in status_str.lower() or "manual_review" in status_str.lower():
            tool_context.agent.state.set("workflow_stage", "completed")
            tool_context.agent.state.set("kyc_status", status_str)
            tool_context.agent.state.set("kyc_decision", result.get("decision", "rejected"))
        return result
    except TimeoutError:
        logger.error(f"   ❌ Verification timed out for application {effective_app_id}")
        return {"success": False, "error": "Verification timed out. Please try again."}
    except Exception as e:
        logger.error(f"   ❌ Exception in confirm_and_verify: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


# Legacy alias for backward compatibility
@tool(context=True)
def process_kyc(tool_context: ToolContext, application_id: str | None = None) -> dict:
    """
    Process KYC application - runs OCR extraction first.
    
    This is a convenience tool that starts the verification process.
    After calling this, present the extracted data to the user for confirmation,
    then use confirm_and_verify to complete the verification.
    
    Args:
        application_id: The KYC application ID (optional, uses state if not provided)
        
    Returns:
        Dictionary with OCR extracted data for review
    """
    return run_ocr_extraction(tool_context=tool_context, application_id=application_id)


@tool(context=True)
def get_kyc_status(tool_context: ToolContext, application_id: str | None = None) -> dict:
    """
    Get the current status and decision of a KYC application.
    
    Use this tool to check if the KYC verification is complete
    and what the final decision is. Uses application_id from agent state if not provided.
    
    Args:
        application_id: The KYC application ID (optional, uses state if not provided)
        
    Returns:
        Dictionary with current status and decision
    """
    # Get application_id from state if not provided
    effective_app_id = application_id or tool_context.agent.state.get("application_id")
    if not effective_app_id:
        return {
            "success": False,
            "error": "No application_id provided or found in session. Please initiate KYC first.",
        }
    
    async def _get_status():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(KYCApplication)
                .where(KYCApplication.id == effective_app_id)
                .options(selectinload(KYCApplication.stages))
            )
            application = result.scalar_one_or_none()
            
            if not application:
                return {
                    "success": False,
                    "error": "KYC application not found.",
                }
            
            # Get completed stages
            completed_stages = [s.stage_name for s in application.stages if s.status == "completed"]
            
            # Determine user-friendly status
            if application.status == "completed":
                if application.decision == "approved":
                    status_message = "Your identity has been successfully verified."
                else:
                    status_message = f"Your verification was not successful. Reason: {application.decision_reason}"
            elif application.status == "processing":
                status_message = "Your documents are being verified. Please wait for the process to complete."
            elif application.status == "failed":
                status_message = f"Verification failed. Reason: {application.decision_reason}"
            else:
                status_message = f"Current stage: {application.current_stage}. Please complete any pending steps."
            
            return {
                "success": True,
                "application_id": effective_app_id,
                "status": application.status,
                "current_stage": application.current_stage,
                "decision": application.decision,
                "decision_reason": application.decision_reason,
                "completed_stages": completed_stages,
                "status_message": status_message,
            }
    
    try:
        result = run_sync(_get_status())
        # Update state with final status
        if result.get("success"):
            tool_context.agent.state.set("kyc_status", result["status"])
            tool_context.agent.state.set("workflow_stage", result["current_stage"])
            if result.get("decision"):
                tool_context.agent.state.set("kyc_decision", result["decision"])
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}

