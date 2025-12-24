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
    
    Supports optional document uploads via the 'documents' field.

    Args:
        request: Chat request containing message, optional session_id, and optional documents

    Returns:
        ChatResponse: Agent's response with session_id and document upload count
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

    # Handle document uploads if provided
    documents_uploaded = 0
    if request.documents:
        doc_info = []
        for doc in request.documents:
            doc_info.append(f"- {doc.document_type}: {doc.filename}")
        
        docs_message = f"""
The user has attached {len(request.documents)} document(s) for upload:
{chr(10).join(doc_info)}

Document data (base64):
{chr(10).join([f'{doc.document_type}|{doc.filename}|{doc.data}' for doc in request.documents])}

Please upload these documents using the upload_kyc_document tool if there's an active KYC application.
"""
        doc_result = agent(docs_message)
        
        if doc_result.message and doc_result.message.get("content"):
            for content_block in doc_result.message.get("content", []):
                if isinstance(content_block, dict) and "text" in content_block:
                    response_text += "\n\n" + content_block["text"]
        
        documents_uploaded = len(request.documents)

    return ChatResponse(
        response=response_text,
        session_id=session_id,
        documents_uploaded=documents_uploaded if documents_uploaded > 0 else None,
    )


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """
    Handle chat requests with Server-Sent Events (SSE) streaming.
    
    Supports optional document uploads via the 'documents' field.

    Args:
        request: Chat request containing message, optional session_id, and optional documents

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

Please upload these documents using the upload_kyc_document tool if there's an active KYC application.
"""
            yield {"data": json.dumps({"text": "\n\nProcessing document uploads..."})}
            
            async for event in agent.stream_async(docs_message):
                if "data" in event:
                    yield {"data": json.dumps({"text": event["data"]})}

    return EventSourceResponse(generate())
