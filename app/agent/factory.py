"""Agent factory for creating Strands agents with session management."""

from strands import Agent
from strands.session.file_session_manager import FileSessionManager

from app.agent.llm import get_bedrock_model
from app.agent.prompts import SYSTEM_PROMPT
from app.config import settings


def create_agent(session_id: str) -> Agent:
    """
    Create a Strands agent with session management.

    Args:
        session_id: Unique identifier for the session

    Returns:
        Agent: Configured Strands agent instance with session management
    """
    session_manager = FileSessionManager(
        session_id=session_id,
        storage_dir=settings.session_storage_dir,
    )
    return Agent(
        model=get_bedrock_model(),
        system_prompt=SYSTEM_PROMPT,
        session_manager=session_manager,
        callback_handler=None,
    )
