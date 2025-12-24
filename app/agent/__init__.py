"""Agent module for Strands Agents integration."""

from app.agent.factory import create_agent
from app.agent.ekyc_agent import process_kyc_application
from app.agent.callbacks import (
    create_event_callback,
    create_logging_callback,
    AgentEventCallback,
    AgentLoggingCallback,
)
from app.agent.kyc_workflow import KYCWorkflow, process_kyc_workflow

__all__ = [
    "create_agent",
    "process_kyc_application",
    "create_event_callback",
    "create_logging_callback",
    "AgentEventCallback",
    "AgentLoggingCallback",
    "KYCWorkflow",
    "process_kyc_workflow",
]
