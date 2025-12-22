"""Pydantic schemas for request and response models."""

from pydantic import BaseModel, Field


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
