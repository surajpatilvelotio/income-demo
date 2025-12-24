"""Agent factory for creating Strands agents with session management."""

import logging
from typing import Callable

from strands import Agent
from strands.session.file_session_manager import FileSessionManager

from app.agent.llm import get_bedrock_model
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.callbacks import create_event_callback
from app.agent.state_store import state_store
from app.agent.tools import (
    register_user,
    get_user_status,
    find_user_by_email,
    initiate_kyc_process,
    check_kyc_application_status,
    get_user_kyc_applications,
    get_kyc_requirements,
    upload_kyc_document,
    get_uploaded_documents,
    run_ocr_extraction,
    confirm_and_verify,
    process_kyc,
    get_kyc_status,
)
from app.config import settings

logger = logging.getLogger(__name__)


def create_agent(
    session_id: str, 
    include_kyc_tools: bool = True,
    callback_handler: Callable | None = None,
    enable_logging: bool = True,
    initial_state: dict | None = None,
) -> Agent:
    """
    Create a Strands agent with session management and state.

    Args:
        session_id: Unique identifier for the session
        include_kyc_tools: Whether to include KYC management tools (default: True)
        callback_handler: Optional custom callback handler for events
        enable_logging: Whether to enable agent event logging (default: True)
        initial_state: Optional initial state dict with user_id, application_id, etc.

    Returns:
        Agent: Configured Strands agent instance with session management and state
    """
    session_manager = FileSessionManager(
        session_id=session_id,
        storage_dir=settings.session_storage_dir,
    )
    
    # KYC management tools for user-facing operations
    tools = []
    if include_kyc_tools:
        tools = [
            register_user,
            get_user_status,
            find_user_by_email,
            initiate_kyc_process,
            check_kyc_application_status,
            get_user_kyc_applications,
            get_kyc_requirements,
            upload_kyc_document,
            get_uploaded_documents,
            # Workflow tools (integrated OCR + verification)
            run_ocr_extraction,
            confirm_and_verify,
            process_kyc,  # Alias for run_ocr_extraction
            get_kyc_status,
        ]
    
    # Set up callback handler for logging agent events
    handler = callback_handler
    if handler is None and enable_logging:
        handler = create_event_callback(session_id, verbose=True)
    
    # Load persisted state and merge with initial_state
    # See: https://strandsagents.com/latest/documentation/docs/user-guide/concepts/agents/state/
    persisted_state = state_store.load(session_id)
    
    # Merge: persisted_state < initial_state (new values override)
    merged_state = {**persisted_state}
    if initial_state:
        # Only update with non-None values from initial_state
        for key, value in initial_state.items():
            if value is not None:
                merged_state[key] = value
    
    logger.debug(f"Creating agent with session_id: {session_id}, tools: {len(tools)}, state: {merged_state}")
    
    return Agent(
        model=get_bedrock_model(),
        system_prompt=SYSTEM_PROMPT,
        session_manager=session_manager,
        tools=tools if tools else None,
        callback_handler=handler,
        state=merged_state if merged_state else None,
    )
