"""API routes for chat endpoints."""

import json
import uuid

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.agent import create_agent
from app.api.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Handle chat requests without streaming.

    Args:
        request: Chat request containing message and optional session_id

    Returns:
        ChatResponse: Agent's response with session_id (generated if not provided)
    """
    # Generate new session ID if not provided
    session_id = request.session_id or str(uuid.uuid4())

    agent = create_agent(session_id)
    result = agent(request.message)

    # Extract text from the message content
    response_text = ""
    if result.message and result.message.get("content"):
        for content_block in result.message.get("content", []):
            if isinstance(content_block, dict) and "text" in content_block:
                response_text += content_block["text"]

    return ChatResponse(
        response=response_text,
        session_id=session_id,
    )


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """
    Handle chat requests with Server-Sent Events (SSE) streaming.

    Args:
        request: Chat request containing message and optional session_id

    Returns:
        EventSourceResponse: Streaming SSE response with session_id in first event
    """
    # Generate new session ID if not provided
    session_id = request.session_id or str(uuid.uuid4())

    agent = create_agent(session_id)

    async def generate():
        # Send session_id as first event so client knows which session to use
        yield {"data": json.dumps({"session_id": session_id})}

        async for event in agent.stream_async(request.message):
            if "data" in event:
                yield {"data": json.dumps({"text": event["data"]})}

    return EventSourceResponse(generate())
