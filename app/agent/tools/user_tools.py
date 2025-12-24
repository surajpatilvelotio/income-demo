"""User management tools for the chat agent.

Uses Strands Agent state to maintain context across tool calls:
https://strandsagents.com/latest/documentation/docs/user-guide/concepts/agents/state/
"""

import base64
import uuid
from pathlib import Path
from datetime import datetime, timezone

from strands import tool
from strands.types.tools import ToolContext
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.database import AsyncSessionLocal
from app.db.models import User, KYCApplication, KYCDocument, KYCStage
from app.services.password import hash_password
from app.config import settings
from app.utils.async_helpers import run_sync


MAX_DOCUMENTS_PER_APPLICATION = 3


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
            
            # Create user
            user = User(
                email=email,
                phone=phone,
                password_hash=hash_password(password),
                kyc_status="pending",
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
                "message": "Account created successfully! You can now start the KYC verification process.",
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
    Start the KYC verification process for a user.
    
    Use this tool when a user wants to begin their identity verification.
    This creates a new KYC application that tracks the verification progress.
    Uses user_id from agent state if not provided.
    
    Args:
        user_id: The user's unique identifier (optional, uses state if not provided)
        
    Returns:
        Dictionary with KYC application details
    """
    # Get user_id from state if not provided
    effective_user_id = user_id or tool_context.agent.state.get("user_id")
    if not effective_user_id:
        return {
            "success": False,
            "error": "No user_id provided or found in session. Please register or login first.",
        }
    
    async def _initiate():
        async with AsyncSessionLocal() as session:
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
            
            # Check for existing active application
            existing = await session.execute(
                select(KYCApplication)
                .where(KYCApplication.user_id == effective_user_id)
                .where(KYCApplication.status.in_(["initiated", "documents_uploaded", "processing"]))
            )
            existing_app = existing.scalar_one_or_none()
            if existing_app:
                return {
                    "success": True,
                    "application_id": existing_app.id,
                    "status": existing_app.status,
                    "existing": True,
                    "message": "You have an active KYC application. Let's continue with it.",
                    "next_step": "Upload your ID card or passport to continue." if existing_app.status == "initiated" else "Your documents are being processed.",
                }
            
            # Create application
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
                "application_id": application.id,
                "status": application.status,
                "message": "KYC process initiated! Please upload your identity documents (ID card or passport) to continue.",
                "next_step": "Upload your ID card or passport using the document upload feature.",
            }
    
    try:
        result = run_sync(_initiate())
        # Store application_id in agent state
        if result.get("success"):
            tool_context.agent.state.set("application_id", result["application_id"])
            tool_context.agent.state.set("kyc_status", "in_progress")
            tool_context.agent.state.set("workflow_stage", "initiated")
        return result
    except Exception as e:
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
                    "message": "No KYC applications found. Start the KYC process to begin verification.",
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
    Maximum 3 documents allowed per application.
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
            
            # Check document limit
            current_count = len(application.documents)
            if current_count >= MAX_DOCUMENTS_PER_APPLICATION:
                return {
                    "success": False,
                    "error": f"Maximum {MAX_DOCUMENTS_PER_APPLICATION} documents allowed. You already have {current_count} documents uploaded.",
                    "documents_uploaded": current_count,
                }
            
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
            ext = Path(filename).suffix.lower() if filename else ".jpg"
            if ext not in [".jpg", ".jpeg", ".png", ".pdf", ".webp"]:
                ext = ".jpg"
            
            mime_types = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".pdf": "application/pdf",
                ".webp": "image/webp",
            }
            mime_type = mime_types.get(ext, "image/jpeg")
            
            # Create upload directory
            upload_dir = Path(settings.upload_dir) / application_id
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
                application_id=application_id,
                document_type=document_type,
                file_path=str(file_path),
                original_filename=filename or unique_filename,
                mime_type=mime_type,
            )
            session.add(document)
            
            # Update application status
            application.status = "documents_uploaded"
            application.current_stage = "document_uploaded"
            application.updated_at = datetime.now(timezone.utc)
            
            await session.commit()
            
            new_count = current_count + 1
            remaining = MAX_DOCUMENTS_PER_APPLICATION - new_count
            
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
def run_ocr_extraction(tool_context: ToolContext, application_id: str | None = None) -> dict:
    """
    Run OCR extraction on uploaded documents and return data for user review.
    
    Use this tool after the user has uploaded documents. It extracts identity
    information from the documents and presents it for the user to review
    and confirm before verification.
    
    Args:
        application_id: The KYC application ID (optional, uses state if not provided)
        
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
            
            # Prepare documents for workflow
            documents = [
                {
                    "file_path": doc.file_path,
                    "document_type": doc.document_type,
                    "original_filename": doc.original_filename,
                }
                for doc in application.documents
            ]
            
            # Run OCR workflow step
            workflow = KYCWorkflow(effective_app_id)
            ocr_result = await workflow.run_ocr_step(documents)
            
            if not ocr_result.get("success", False):
                return {
                    "success": False,
                    "error": ocr_result.get("error", "OCR extraction failed"),
                }
            
            # Get extracted data for review
            extracted_data = ocr_result.get("extracted_data_for_review", [])
            
            return {
                "success": True,
                "status": "pending_user_review",
                "message": "I've extracted the following information from your document. Please review and confirm if it's correct:",
                "extracted_data": extracted_data,
                "next_step": "Please confirm if this information is correct, or let me know what needs to be corrected.",
            }
    
    try:
        result = run_sync(_run_ocr())
        # Update state
        if result.get("success"):
            tool_context.agent.state.set("workflow_stage", "ocr_completed")
            if result.get("extracted_data"):
                tool_context.agent.state.set("extracted_data", result["extracted_data"])
        return result
    except Exception as e:
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
        
        # Confirm data
        await workflow.confirm_user_data(extracted_data)
        
        # Run verification
        verification_result = await workflow.run_full_verification()
        
        return verification_result
    
    try:
        result = run_sync(_verify())
        # Update state with final result
        if result.get("status") == "approved":
            tool_context.agent.state.set("workflow_stage", "completed")
            tool_context.agent.state.set("kyc_status", "approved")
            tool_context.agent.state.set("kyc_decision", "approved")
        elif result.get("status") in ["rejected", "manual_review_required"]:
            tool_context.agent.state.set("workflow_stage", "completed")
            tool_context.agent.state.set("kyc_status", result.get("status"))
            tool_context.agent.state.set("kyc_decision", result.get("decision", "rejected"))
        return result
    except Exception as e:
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
                    status_message = "Your identity verification is complete and approved! Your account is now fully activated."
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

