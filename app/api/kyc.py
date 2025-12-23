"""API routes for KYC (Know Your Customer) workflow."""

import json
import asyncio
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from app.db.database import get_db, AsyncSessionLocal
from app.db.models import User, KYCApplication, KYCDocument, KYCStage
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

