"""Pydantic schemas for request and response models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, EmailStr


# ============================================
# Chat Schemas
# ============================================

class ChatRequest(BaseModel):
    """Request model for chat endpoints."""

    message: str = Field(..., description="User message to send to the agent")
    session_id: str | None = Field(
        None,
        description="Optional session identifier. If not provided, a new session will be created",
    )


class ChatResponse(BaseModel):
    """Response model for non-streaming chat endpoint."""

    response: str = Field(..., description="Agent's response message")
    session_id: str = Field(..., description="Session identifier used for the conversation")


# ============================================
# User Schemas
# ============================================

class UserSignupRequest(BaseModel):
    """Request model for user signup."""

    email: EmailStr = Field(..., description="User email address")
    phone: str | None = Field(None, description="User phone number")
    password: str = Field(..., min_length=8, description="User password (min 8 characters)")


class UserResponse(BaseModel):
    """Response model for user data."""

    id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email address")
    phone: str | None = Field(None, description="User phone number")
    kyc_status: str = Field(..., description="KYC status: pending, in_progress, approved, rejected")
    member_id: str | None = Field(None, description="Associated member ID after KYC approval")
    created_at: datetime = Field(..., description="Account creation timestamp")

    model_config = {"from_attributes": True}


# ============================================
# KYC Schemas
# ============================================

class KYCInitiateRequest(BaseModel):
    """Request model for initiating KYC process."""

    user_id: str = Field(..., description="User ID to initiate KYC for")


class KYCDocumentUploadResponse(BaseModel):
    """Response model for document upload."""

    id: str = Field(..., description="Document ID")
    application_id: str = Field(..., description="KYC application ID")
    document_type: str = Field(..., description="Type of document: id_card, passport")
    original_filename: str | None = Field(None, description="Original filename")
    uploaded_at: datetime = Field(..., description="Upload timestamp")

    model_config = {"from_attributes": True}


class KYCStageResponse(BaseModel):
    """Response model for KYC stage."""

    id: str = Field(..., description="Stage ID")
    stage_name: str = Field(..., description="Name of the stage")
    status: str = Field(..., description="Stage status: pending, in_progress, completed, failed")
    result: dict[str, Any] | None = Field(None, description="Stage result data")
    started_at: datetime | None = Field(None, description="Stage start timestamp")
    completed_at: datetime | None = Field(None, description="Stage completion timestamp")

    model_config = {"from_attributes": True}


class KYCApplicationResponse(BaseModel):
    """Response model for KYC application."""

    id: str = Field(..., description="Application ID")
    user_id: str = Field(..., description="User ID")
    status: str = Field(..., description="Application status")
    current_stage: str | None = Field(None, description="Current processing stage")
    decision: str | None = Field(None, description="KYC decision: approved, rejected")
    decision_reason: str | None = Field(None, description="Reason for decision")
    extracted_data: dict[str, Any] | None = Field(None, description="Extracted identity data")
    created_at: datetime = Field(..., description="Application creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    documents: list[KYCDocumentUploadResponse] = Field(default_factory=list)
    stages: list[KYCStageResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class KYCProcessRequest(BaseModel):
    """Request model for triggering KYC processing."""

    application_id: str = Field(..., description="KYC application ID to process")


class KYCStatusEvent(BaseModel):
    """Model for KYC status SSE event."""

    stage: str = Field(..., description="Current stage name")
    status: str = Field(..., description="Stage status")
    message: str = Field(..., description="Human-readable status message")
    data: dict[str, Any] | None = Field(None, description="Additional stage data")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
