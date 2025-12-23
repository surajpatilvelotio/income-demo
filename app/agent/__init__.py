"""Agent module for Strands Agents integration."""

from app.agent.factory import create_agent
from app.agent.ekyc_agent import create_ekyc_agent, process_kyc_application

__all__ = ["create_agent", "create_ekyc_agent", "process_kyc_application"]
