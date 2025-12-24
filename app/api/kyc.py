"""API routes for KYC (Know Your Customer) workflow."""

import json
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from app.db.database import get_db, AsyncSessionLocal
from app.db.models import User, KYCApplication, KYCDocument, KYCStage

logger = logging.getLogger(__name__)

# Retry configuration for agent calls (handles Windows file locking)
MAX_RETRIES = 3
RETRY_DELAY = 0.5  # seconds


def call_agent_with_retry(agent, message: str, max_retries: int = MAX_RETRIES) -> dict:
    """
    Call the agent with retry logic to handle file locking issues on Windows.
    
    Args:
        agent: The Strands agent instance
        message: The message to send to the agent
        max_retries: Maximum number of retry attempts
        
    Returns:
        The agent result
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            return agent(message)
        except PermissionError as e:
            last_error = e
            logger.warning(f"Agent call attempt {attempt + 1}/{max_retries} failed with PermissionError: {e}")
            if attempt < max_retries - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
        except Exception as e:
            # Check if it's a wrapped PermissionError
            if "PermissionError" in str(e) or "Access is denied" in str(e):
                last_error = e
                logger.warning(f"Agent call attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                raise
    
    logger.error(f"All {max_retries} agent call attempts failed")
    raise last_error or Exception("Agent call failed after retries")
from app.api.schemas import (
    KYCInitiateRequest,
    KYCDocumentUploadResponse,
    KYCApplicationResponse,
    KYCProcessRequest,
    KYCStatusEvent,
)
from app.services.document_storage import document_storage
from app.agent.ekyc_agent import process_kyc_application

router = APIRouter(prefix="/kyc", tags=["kyc"])


@router.post("/initiate", response_model=KYCApplicationResponse, status_code=status.HTTP_201_CREATED)
async def initiate_kyc(
    request: KYCInitiateRequest,
    db: AsyncSession = Depends(get_db),
) -> KYCApplicationResponse:
    """
    Initiate a new KYC application for a user.

    Args:
        request: Request with user_id

    Returns:
        KYCApplicationResponse: Created KYC application

    Raises:
        HTTPException: If user not found or already has pending KYC
    """
    # Find user
    result = await db.execute(select(User).where(User.id == request.user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Check if user already has an active KYC application
    existing = await db.execute(
        select(KYCApplication)
        .where(KYCApplication.user_id == request.user_id)
        .where(KYCApplication.status.in_(["initiated", "documents_uploaded", "processing"]))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already has an active KYC application",
        )

    # Create KYC application
    application = KYCApplication(
        user_id=request.user_id,
        status="initiated",
        current_stage="initiated",
    )
    db.add(application)
    
    # Update user status
    user.kyc_status = "in_progress"

    await db.flush()
    await db.refresh(application)

    return KYCApplicationResponse(
        id=application.id,
        user_id=application.user_id,
        status=application.status,
        current_stage=application.current_stage,
        decision=application.decision,
        decision_reason=application.decision_reason,
        extracted_data=application.extracted_data,
        created_at=application.created_at,
        updated_at=application.updated_at,
        documents=[],
        stages=[],
    )


@router.post("/documents", response_model=KYCDocumentUploadResponse)
async def upload_document(
    application_id: Annotated[str, Form()],
    document_type: Annotated[str, Form()],
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> KYCDocumentUploadResponse:
    """
    Upload a document for KYC verification.

    Args:
        application_id: KYC application ID
        document_type: Type of document (id_card or passport)
        file: Uploaded document file

    Returns:
        KYCDocumentUploadResponse: Uploaded document info

    Raises:
        HTTPException: If application not found or invalid document type
    """
    # Validate document type
    valid_types = ["id_card", "passport"]
    if document_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid document type. Must be one of: {valid_types}",
        )

    # Find application
    result = await db.execute(
        select(KYCApplication).where(KYCApplication.id == application_id)
    )
    application = result.scalar_one_or_none()

    if not application:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KYC application not found",
        )

    if application.status not in ["initiated", "documents_uploaded"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot upload documents for this application status",
        )

    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/webp", "application/pdf"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {allowed_types}",
        )

    # Save document to storage
    file_path, filename = document_storage.save_document(
        application_id=application_id,
        file=file.file,
        original_filename=file.filename or "document",
        document_type=document_type,
    )

    # Create document record
    document = KYCDocument(
        application_id=application_id,
        document_type=document_type,
        file_path=file_path,
        original_filename=file.filename,
        mime_type=file.content_type,
    )
    db.add(document)

    # Update application status
    application.status = "documents_uploaded"
    application.current_stage = "document_uploaded"

    await db.flush()
    await db.refresh(document)

    return KYCDocumentUploadResponse.model_validate(document)


@router.post("/process/{application_id}")
async def trigger_processing(
    application_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Trigger KYC processing for an application.

    This endpoint starts the AI agent processing in the background
    and returns immediately. Use the /status/{application_id} endpoint
    to monitor progress.

    Args:
        application_id: KYC application ID

    Returns:
        dict: Processing started confirmation

    Raises:
        HTTPException: If application not found or no documents uploaded
    """
    # Find application with documents
    result = await db.execute(
        select(KYCApplication)
        .where(KYCApplication.id == application_id)
        .options(selectinload(KYCApplication.documents))
    )
    application = result.scalar_one_or_none()

    if not application:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KYC application not found",
        )

    if not application.documents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No documents uploaded for this application",
        )

    if application.status == "processing":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Application is already being processed",
        )

    if application.status in ["completed", "failed"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Application already {application.status}",
        )

    # Update status to processing
    application.status = "processing"
    await db.commit()

    # Prepare document info for agent
    documents = [
        {
            "document_type": doc.document_type,
            "file_path": doc.file_path,
            "original_filename": doc.original_filename,
        }
        for doc in application.documents
    ]

    # Add background task for processing
    background_tasks.add_task(
        run_kyc_processing,
        application_id=application_id,
        documents=documents,
    )

    return {
        "status": "processing_started",
        "application_id": application_id,
        "message": "KYC processing has been started. Monitor progress via /kyc/status/{application_id}",
    }


async def run_kyc_processing(application_id: str, documents: list[dict]) -> None:
    """Background task to run KYC processing."""
    try:
        # Run the synchronous agent processing in a thread pool
        await asyncio.to_thread(
            process_kyc_application, application_id, documents
        )
    except Exception as e:
        # Update application status on error
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(KYCApplication).where(KYCApplication.id == application_id)
            )
            application = result.scalar_one_or_none()
            if application:
                application.status = "failed"
                application.decision = "rejected"
                application.decision_reason = f"Processing error: {str(e)}"
                await session.commit()


@router.get("/status/{application_id}")
async def get_status_stream(application_id: str):
    """
    Stream KYC processing status updates via Server-Sent Events.

    This endpoint provides real-time updates on KYC processing stages.

    Args:
        application_id: KYC application ID

    Returns:
        EventSourceResponse: SSE stream of status updates
    """
    async def generate_events():
        last_stage_count = 0
        poll_count = 0
        max_polls = 300  # 5 minutes max at 1 second intervals
        initial_sent = False

        while poll_count < max_polls:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(KYCApplication)
                    .where(KYCApplication.id == application_id)
                    .options(selectinload(KYCApplication.stages))
                )
                application = result.scalar_one_or_none()

                if not application:
                    yield {
                        "event": "error",
                        "data": json.dumps({"error": "Application not found"}),
                    }
                    return

                # Send initial state on first connect (so UI knows current state immediately)
                if not initial_sent:
                    current_stages = sorted(application.stages, key=lambda s: s.created_at)
                    stages_data = [
                        {
                            "stage_name": s.stage_name,
                            "status": s.status,
                            "message": _get_stage_message(s.stage_name, s.status),
                            "result": s.result,
                            "started_at": s.started_at.isoformat() if s.started_at else None,
                            "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                        }
                        for s in current_stages
                    ]
                    yield {
                        "event": "init",
                        "data": json.dumps({
                            "application_id": application.id,
                            "status": application.status,
                            "current_stage": application.current_stage,
                            "decision": application.decision,
                            "decision_reason": application.decision_reason,
                            "stages": stages_data,
                        }),
                    }
                    initial_sent = True
                    last_stage_count = len(current_stages)

                # Send new stage updates
                current_stages = sorted(application.stages, key=lambda s: s.created_at)
                
                if len(current_stages) > last_stage_count:
                    for stage in current_stages[last_stage_count:]:
                        event_data = KYCStatusEvent(
                            stage=stage.stage_name,
                            status=stage.status,
                            message=_get_stage_message(stage.stage_name, stage.status),
                            data=stage.result,
                            timestamp=stage.created_at,
                        )
                        yield {
                            "event": "stage_update",
                            "data": event_data.model_dump_json(),
                        }
                    last_stage_count = len(current_stages)

                # Check if processing is complete
                if application.status in ["completed", "failed"]:
                    final_event = {
                        "status": application.status,
                        "decision": application.decision,
                        "decision_reason": application.decision_reason,
                        "extracted_data": application.extracted_data,
                    }
                    yield {
                        "event": "complete",
                        "data": json.dumps(final_event),
                    }
                    return

            # Wait before next poll
            await asyncio.sleep(1)
            poll_count += 1

        # Timeout
        yield {
            "event": "timeout",
            "data": json.dumps({"message": "Status polling timed out"}),
        }

    return EventSourceResponse(generate_events())


def _get_stage_message(stage_name: str, status: str) -> str:
    """Get human-readable message for a stage."""
    messages = {
        "document_uploaded": {
            "pending": "Waiting for document upload",
            "in_progress": "Processing uploaded documents",
            "completed": "Documents received successfully",
            "failed": "Document upload failed",
        },
        "ocr_processing": {
            "pending": "Waiting for OCR processing",
            "in_progress": "Extracting text from documents",
            "completed": "OCR extraction completed",
            "failed": "OCR extraction failed",
        },
        "data_extracted": {
            "pending": "Waiting for data extraction",
            "in_progress": "Parsing identity information",
            "completed": "Identity data extracted successfully",
            "failed": "Data extraction failed",
        },
        "user_review": {
            "pending": "Waiting for user review",
            "in_progress": "User reviewing extracted data",
            "completed": "User confirmed extracted data",
            "failed": "User rejected extracted data",
        },
        "gov_verification": {
            "pending": "Waiting for government verification",
            "in_progress": "Verifying with government database",
            "completed": "Government verification completed",
            "failed": "Government verification failed",
        },
        "fraud_check": {
            "pending": "Waiting for fraud check",
            "in_progress": "Analyzing for fraud indicators",
            "completed": "Fraud check completed",
            "failed": "Fraud check failed",
        },
        "decision_made": {
            "pending": "Waiting for final decision",
            "in_progress": "Making KYC decision",
            "completed": "KYC decision finalized",
            "failed": "Decision process failed",
        },
    }
    return messages.get(stage_name, {}).get(status, f"{stage_name}: {status}")


# ============================================
# KYC Workflow Endpoints
# ============================================

from app.agent.kyc_workflow import KYCWorkflow
from pydantic import BaseModel


class OCRResultResponse(BaseModel):
    """Response for OCR extraction."""
    status: str
    message: str
    extracted_data: list[dict] | None = None
    requires_user_action: bool = False
    next_action: str | None = None


class UserConfirmRequest(BaseModel):
    """Request for user confirmation of extracted data."""
    confirmed: bool = True
    corrections: dict | None = None


class VerificationResultResponse(BaseModel):
    """Response for verification result."""
    status: str
    decision: str | None = None
    message: str
    reason: str | None = None


@router.post("/ocr/{application_id}", response_model=OCRResultResponse)
async def run_ocr_extraction(
    application_id: str,
    db: AsyncSession = Depends(get_db),
) -> OCRResultResponse:
    """
    Step 1: Run OCR extraction on uploaded documents.
    
    This extracts data from documents and returns it for user review.
    The user must confirm the extracted data before verification proceeds.
    
    Args:
        application_id: KYC application ID
        
    Returns:
        OCRResultResponse: Extracted data for user review
    """
    # Get application and documents
    result = await db.execute(
        select(KYCApplication)
        .where(KYCApplication.id == application_id)
        .options(selectinload(KYCApplication.documents))
    )
    application = result.scalar_one_or_none()
    
    if not application:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KYC application not found",
        )
    
    if not application.documents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No documents uploaded. Please upload documents first.",
        )
    
    # Prepare documents for OCR
    documents = [
        {
            "file_path": doc.file_path,
            "document_type": doc.document_type,
            "original_filename": doc.original_filename,
        }
        for doc in application.documents
    ]
    
    # Run OCR workflow step
    workflow = KYCWorkflow(application_id)
    ocr_result = await workflow.run_ocr_step(documents)
    
    return OCRResultResponse(
        status=ocr_result.get("status", "unknown"),
        message=ocr_result.get("message", ""),
        extracted_data=ocr_result.get("extracted_data"),
        requires_user_action=ocr_result.get("requires_user_action", True),
        next_action=ocr_result.get("next_action"),
    )


@router.post("/confirm/{application_id}", response_model=VerificationResultResponse)
async def confirm_extracted_data(
    application_id: str,
    request: UserConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> VerificationResultResponse:
    """
    Step 2: User confirms or corrects extracted data.
    
    After confirmation, the system proceeds with verification.
    
    Args:
        application_id: KYC application ID
        request: Confirmation with optional corrections
        
    Returns:
        VerificationResultResponse: Confirmation result
    """
    # Get application
    result = await db.execute(
        select(KYCApplication).where(KYCApplication.id == application_id)
    )
    application = result.scalar_one_or_none()
    
    if not application:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KYC application not found",
        )
    
    # Create workflow with existing extracted data
    workflow = KYCWorkflow(application_id)
    workflow.extracted_data = application.extracted_data
    
    # Confirm data
    confirm_result = await workflow.confirm_user_data(
        confirmed=request.confirmed,
        corrections=request.corrections,
    )
    
    return VerificationResultResponse(
        status=confirm_result.get("status", "unknown"),
        message=confirm_result.get("message", ""),
    )


@router.post("/verify/{application_id}", response_model=VerificationResultResponse)
async def run_verification(
    application_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> VerificationResultResponse:
    """
    Step 3: Run full verification (Gov DB → Fraud Detection → Decision).
    
    This should only be called after user has confirmed the extracted data.
    
    Workflow:
    1. Government database verification
    2. If gov verification FAILS → STOP (manual review required)
    3. If gov verification PASSES → Fraud detection
    4. Final decision
    
    Args:
        application_id: KYC application ID
        
    Returns:
        VerificationResultResponse: Verification result
    """
    # Get application
    result = await db.execute(
        select(KYCApplication)
        .where(KYCApplication.id == application_id)
        .options(selectinload(KYCApplication.documents))
    )
    application = result.scalar_one_or_none()
    
    if not application:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KYC application not found",
        )
    
    if not application.extracted_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No extracted data. Please run OCR first (/kyc/ocr/{application_id}).",
        )
    
    # Create workflow with existing data
    workflow = KYCWorkflow(application_id)
    workflow.extracted_data = application.extracted_data
    
    # Run verification synchronously for immediate response
    # (For long-running, use background_tasks.add_task)
    verification_result = await workflow.run_full_verification()
    
    return VerificationResultResponse(
        status=verification_result.get("status", "unknown"),
        decision=verification_result.get("decision"),
        message=verification_result.get("message", ""),
        reason=verification_result.get("reason"),
    )


@router.get("/applications/{user_id}", response_model=list[KYCApplicationResponse])
async def list_user_applications(
    user_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[KYCApplicationResponse]:
    """
    List all KYC applications for a user.

    Args:
        user_id: User ID

    Returns:
        List of KYC applications with documents and stages
    """
    result = await db.execute(
        select(KYCApplication)
        .where(KYCApplication.user_id == user_id)
        .options(
            selectinload(KYCApplication.documents),
            selectinload(KYCApplication.stages),
        )
        .order_by(KYCApplication.created_at.desc())
    )
    applications = result.scalars().all()

    return [KYCApplicationResponse.model_validate(app) for app in applications]


@router.get("/application/{application_id}", response_model=KYCApplicationResponse)
async def get_application(
    application_id: str,
    db: AsyncSession = Depends(get_db),
) -> KYCApplicationResponse:
    """
    Get a specific KYC application by ID.

    Args:
        application_id: KYC application ID

    Returns:
        KYCApplicationResponse: Application details with documents and stages

    Raises:
        HTTPException: If application not found
    """
    result = await db.execute(
        select(KYCApplication)
        .where(KYCApplication.id == application_id)
        .options(
            selectinload(KYCApplication.documents),
            selectinload(KYCApplication.stages),
        )
    )
    application = result.scalar_one_or_none()

    if not application:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KYC application not found",
        )

    return KYCApplicationResponse.model_validate(application)


# ============================================
# KYC Chat Endpoints
# ============================================

from app.api.schemas import ChatRequest, ChatResponse
from app.agent import create_agent
from app.agent.tools import upload_kyc_document, get_user_kyc_applications
import uuid


async def _process_document_uploads(
    request: ChatRequest,
    session_context: dict,
) -> tuple[list[dict], str]:
    """
    Process document uploads from the request.
    
    Returns:
        Tuple of (upload_results, context_message)
    """
    if not request.documents:
        return [], ""
    
    upload_results = []
    
    # Try to find the application_id from session context or recent applications
    application_id = session_context.get("application_id")
    
    if not application_id:
        # No application ID in context - documents can't be uploaded
        return [], "\n\n[Note: Documents were provided but no active KYC application found. Please initiate KYC first, then upload documents.]"
    
    for doc in request.documents:
        result = upload_kyc_document(
            application_id=application_id,
            document_type=doc.document_type,
            document_data=doc.data,
            filename=doc.filename,
        )
        upload_results.append(result)
    
    # Build context message about uploads
    successful = [r for r in upload_results if r.get("success")]
    failed = [r for r in upload_results if not r.get("success")]
    
    context_parts = []
    if successful:
        context_parts.append(f"[{len(successful)} document(s) uploaded successfully]")
    if failed:
        errors = [r.get("error", "Unknown error") for r in failed]
        context_parts.append(f"[Upload failed for {len(failed)} document(s): {'; '.join(errors)}]")
    
    context_message = "\n\n" + " ".join(context_parts) if context_parts else ""
    
    return upload_results, context_message


@router.post("/chat", response_model=ChatResponse)
async def kyc_chat(request: ChatRequest) -> ChatResponse:
    """
    Conversational KYC chat endpoint with document upload support.

    This endpoint provides a chat interface for KYC-related queries and actions.
    Users can:
    - Ask about KYC requirements
    - Register a new account (or continue as returning user via user_id/user_email)
    - Initiate KYC process
    - Check their KYC status
    - Upload identity documents (via the 'documents' field)
    - Get help with the verification process

    For returning users (e.g., after signup via /users/signup):
    - Pass user_id or user_email to identify the user
    - Agent will automatically use this context for KYC operations

    Documents can be uploaded by including the 'documents' array with up to 3 items,
    each containing 'data' (base64), 'filename', and 'document_type' (id_card/passport).

    Args:
        request: Chat request with message, optional session_id, user_id/user_email, and documents

    Returns:
        ChatResponse: Agent's response with session_id and document upload count
    """
    session_id = request.session_id or f"kyc-chat-{uuid.uuid4()}"

    # Build initial state from request context
    # See: https://strandsagents.com/latest/documentation/docs/user-guide/concepts/agents/state/
    initial_state = {}
    if request.user_id:
        initial_state["user_id"] = request.user_id
    if request.user_email:
        initial_state["user_email"] = request.user_email
    if request.application_id:
        initial_state["application_id"] = request.application_id
    
    agent = create_agent(
        session_id, 
        include_kyc_tools=True, 
        initial_state=initial_state if initial_state else None,
    )
    
    # Build the message with user context if provided
    message_with_context = request.message
    context_parts = []
    
    # Add user context
    if request.user_id:
        context_parts.append(f"user_id: {request.user_id}")
    if request.user_email:
        context_parts.append(f"user_email: {request.user_email}")
    if request.application_id:
        context_parts.append(f"application_id: {request.application_id}")
    
    # If any context provided, add system message
    if context_parts:
        context_str = ", ".join(context_parts)
        
        # Different instructions based on what's provided
        if request.application_id:
            instructions = f"""[SYSTEM CONTEXT: {context_str}]
This user has an active KYC application. Use application_id directly for uploads, processing, and status."""
        elif request.user_id:
            instructions = f"""[SYSTEM CONTEXT: {context_str}]
IMPORTANT: This user just clicked "Initiate KYC" from the UI.
ACTION REQUIRED: 
1. FIRST call initiate_kyc_process(user_id="{request.user_id}") to start their KYC
2. Remember the application_id from the response
3. Then guide them to upload documents
Do NOT ask them to register - they already have an account."""
        else:
            instructions = f"""[SYSTEM CONTEXT: {context_str}]
Look up user by email using find_user_by_email, then proceed with KYC."""
        
        message_with_context = f"{instructions}\n\nUser message: {request.message}"
    
    # First, run the agent to process the message (with retry for file locking)
    # This may create user/application which we need for document uploads
    result = call_agent_with_retry(agent, message_with_context)

    # Extract text from the message content
    response_text = ""
    if result.message and result.message.get("content"):
        for content_block in result.message.get("content", []):
            if isinstance(content_block, dict) and "text" in content_block:
                response_text += content_block["text"]

    # Process document uploads if provided
    documents_uploaded = 0
    if request.documents:
        # Save documents directly (don't pass base64 to agent - too many tokens)
        import base64
        
        # Find the user's active application
        async with AsyncSessionLocal() as session:
            # Get user_id from request or find from conversation
            user_id = request.user_id
            if not user_id and request.user_email:
                result = await session.execute(
                    select(User).where(User.email == request.user_email)
                )
                user = result.scalar_one_or_none()
                if user:
                    user_id = user.id
            
            if user_id:
                # Find active application
                result = await session.execute(
                    select(KYCApplication)
                    .where(KYCApplication.user_id == user_id)
                    .where(KYCApplication.status.in_(["initiated", "documents_uploaded"]))
                    .order_by(KYCApplication.created_at.desc())
                )
                application = result.scalar_one_or_none()
                
                if application:
                    # Save each document
                    saved_docs = []
                    for doc in request.documents:
                        try:
                            file_content = base64.b64decode(doc.data)
                            file_path = await document_storage.save_document(
                                application_id=application.id,
                                file_content=file_content,
                                original_filename=doc.filename,
                            )
                            
                            # Create KYCDocument record
                            kyc_doc = KYCDocument(
                                application_id=application.id,
                                document_type=doc.document_type,
                                file_path=file_path,
                                original_filename=doc.filename,
                                mime_type="image/png",  # Default
                            )
                            session.add(kyc_doc)
                            saved_docs.append(doc.filename)
                            documents_uploaded += 1
                        except Exception as e:
                            logger.error(f"Failed to save document {doc.filename}: {e}")
                    
                    if saved_docs:
                        # Update application status
                        application.status = "documents_uploaded"
                        await session.commit()
                        
                        # Tell agent about uploads (without base64 data)
                        doc_info = ", ".join(saved_docs)
                        docs_message = f"The user has successfully uploaded {len(saved_docs)} document(s): {doc_info}. The documents are now saved and ready for processing. Please confirm the upload and ask if they want to proceed with verification."
                        
                        try:
                            doc_result = call_agent_with_retry(agent, docs_message)
                            if doc_result.message and doc_result.message.get("content"):
                                for content_block in doc_result.message.get("content", []):
                                    if isinstance(content_block, dict) and "text" in content_block:
                                        response_text += "\n\n" + content_block["text"]
                        except Exception as e:
                            logger.warning(f"Agent call for document confirmation failed: {e}")
                            response_text += f"\n\nI've successfully uploaded your {len(saved_docs)} document(s). Would you like me to proceed with the verification?"
                else:
                    response_text += "\n\nI couldn't find an active KYC application. Please start the KYC process first."
            else:
                response_text += "\n\nPlease provide your email or register first to upload documents."

    # Persist agent state for next call
    # The agent.state contains user_id, application_id, etc. set by tools
    from app.agent.state_store import state_store
    from app.api.schemas import KYCProgressInfo, KYCStageInfo
    
    kyc_progress = None
    app_id = None
    
    if agent.state:
        current_state = agent.state.get() if hasattr(agent.state, 'get') and callable(agent.state.get) else {}
        if isinstance(current_state, dict) and current_state:
            state_store.save(session_id, current_state)
            logger.debug(f"Persisted state for session {session_id}: {current_state}")
            app_id = current_state.get("application_id")
    
    # Fetch current KYC stages for UI display
    if app_id:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(KYCApplication)
                .where(KYCApplication.id == app_id)
                .options(selectinload(KYCApplication.stages))
            )
            application = result.scalar_one_or_none()
            
            if application:
                stages = [
                    KYCStageInfo(
                        stage_name=stage.stage_name,
                        status=stage.status,
                        result=stage.result,
                        started_at=stage.started_at,
                        completed_at=stage.completed_at,
                    )
                    for stage in application.stages
                ]
                kyc_progress = KYCProgressInfo(
                    application_id=application.id,
                    status=application.status,
                    current_stage=application.current_stage,
                    stages=stages,
                )

    return ChatResponse(
        response=response_text,
        session_id=session_id,
        documents_uploaded=documents_uploaded if documents_uploaded > 0 else None,
        kyc_progress=kyc_progress,
    )


@router.post("/chat/stream")
async def kyc_chat_stream(request: ChatRequest):
    """
    Streaming KYC chat endpoint using Server-Sent Events (SSE).

    This endpoint provides real-time streaming responses for KYC-related
    conversations. Users can interact with the KYC agent and receive
    streaming updates. Document uploads are also supported.

    For returning users:
    - Pass user_id or user_email to identify the user
    - Agent will automatically use this context for KYC operations

    Args:
        request: Chat request with message, optional session_id, user_id/user_email, and documents

    Returns:
        EventSourceResponse: Streaming SSE response
    """
    session_id = request.session_id or f"kyc-chat-{uuid.uuid4()}"

    # Build initial state from request context
    # See: https://strandsagents.com/latest/documentation/docs/user-guide/concepts/agents/state/
    initial_state = {}
    if request.user_id:
        initial_state["user_id"] = request.user_id
    if request.user_email:
        initial_state["user_email"] = request.user_email
    if request.application_id:
        initial_state["application_id"] = request.application_id
    
    agent = create_agent(
        session_id, 
        include_kyc_tools=True, 
        initial_state=initial_state if initial_state else None,
    )
    
    # Build the message with user context if provided
    message_with_context = request.message
    context_parts = []
    
    if request.user_id:
        context_parts.append(f"user_id: {request.user_id}")
    if request.user_email:
        context_parts.append(f"user_email: {request.user_email}")
    if request.application_id:
        context_parts.append(f"application_id: {request.application_id}")
    
    if context_parts:
        context_str = ", ".join(context_parts)
        
        if request.application_id:
            instructions = f"""[SYSTEM CONTEXT: {context_str}]
This user has an active KYC application. Use application_id directly for uploads, processing, and status."""
        elif request.user_id:
            instructions = f"""[SYSTEM CONTEXT: {context_str}]
IMPORTANT: This user just clicked "Initiate KYC" from the UI.
ACTION REQUIRED: 
1. FIRST call initiate_kyc_process(user_id="{request.user_id}") to start their KYC
2. Remember the application_id from the response
3. Then guide them to upload documents
Do NOT ask them to register - they already have an account."""
        else:
            instructions = f"""[SYSTEM CONTEXT: {context_str}]
Look up user by email using find_user_by_email, then proceed with KYC."""
        
        message_with_context = f"{instructions}\n\nUser message: {request.message}"

    async def generate():
        # Send session_id as first event
        yield {"event": "session", "data": json.dumps({"session_id": session_id})}

        # Stream the main message response (with user context if provided)
        async for event in agent.stream_async(message_with_context):
            if "data" in event:
                # Text content
                yield {"event": "text", "data": json.dumps({"text": event["data"]})}
            elif "tool_use" in event:
                # Tool being called
                tool_info = event.get("tool_use", {})
                yield {
                    "event": "tool_call",
                    "data": json.dumps({
                        "tool_name": tool_info.get("name"),
                        "tool_id": tool_info.get("id"),
                    })
                }
            elif "tool_result" in event:
                # Tool result
                result = event.get("tool_result", {})
                # Only send success status, not full result (could be large)
                yield {
                    "event": "tool_result",
                    "data": json.dumps({
                        "tool_id": result.get("tool_use_id"),
                        "success": result.get("content", {}).get("success", True) if isinstance(result.get("content"), dict) else True,
                    })
                }
            elif "stop_reason" in event:
                yield {"event": "stop", "data": json.dumps({"reason": event.get("stop_reason")})}
        
        # Handle document uploads if provided
        if request.documents:
            doc_info = []
            for doc in request.documents:
                doc_info.append(f"- {doc.document_type}: {doc.filename}")
            
            docs_message = f"""
The user has attached {len(request.documents)} document(s) for upload:
{chr(10).join(doc_info)}

Document data (base64):
{chr(10).join([f'{doc.document_type}|{doc.filename}|{doc.data}' for doc in request.documents])}

Please upload these documents using the upload_kyc_document tool.
"""
            yield {"data": json.dumps({"text": "\n\nProcessing document uploads..."})}
            
            async for event in agent.stream_async(docs_message):
                if "data" in event:
                    yield {"data": json.dumps({"text": event["data"]})}

    return EventSourceResponse(generate())

