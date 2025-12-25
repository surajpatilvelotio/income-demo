"""Agent callback handlers for logging and event streaming."""

import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class AgentEventCallback:
    """
    Callback handler that logs meaningful agent events.
    
    Logs:
    - Tool calls (name and parameters)
    - Tool results (success/failure)
    - Full assistant responses (not chunks)
    - Important lifecycle events
    """
    
    def __init__(self, session_id: str | None = None, verbose: bool = True):
        self.session_id = session_id
        self.verbose = verbose
        self.events: list[dict] = []
        self._current_response = ""
        self._pending_tool_calls: dict[str, dict] = {}
    
    def __call__(self, **kwargs) -> None:
        """Handle agent events. Accepts **kwargs to handle all event types from Strands."""
        timestamp = datetime.utcnow().isoformat()
        
        # Tool call started
        if "tool_use" in kwargs:
            tool_info = kwargs.get("tool_use", {})
            if isinstance(tool_info, dict):
                tool_name = tool_info.get("name", "unknown")
                tool_id = tool_info.get("id", "")
                tool_input = tool_info.get("input", {})
                
                # Store for matching with result
                self._pending_tool_calls[tool_id] = {
                    "name": tool_name,
                    "started_at": timestamp,
                }
                
                event = {
                    "type": "tool_call",
                    "timestamp": timestamp,
                    "session_id": self.session_id,
                    "tool_name": tool_name,
                    "tool_id": tool_id,
                    "input_preview": str(tool_input)[:200] if tool_input else None,
                }
                self.events.append(event)
                
                if self.verbose:
                    logger.info(f"[Tool Call] {tool_name}")
                    if tool_input:
                        # Log key parameters (not full data)
                        safe_input = {k: v for k, v in tool_input.items() if k != "document_data" and k != "data"}
                        if safe_input:
                            logger.info(f"   Parameters: {json.dumps(safe_input, indent=2)[:300]}")
        
        # Tool result received
        elif "tool_result" in kwargs:
            result = kwargs.get("tool_result", {})
            tool_id = result.get("tool_use_id", "")
            content = result.get("content", {})
            
            # Get tool name from pending calls
            tool_info = self._pending_tool_calls.pop(tool_id, {})
            tool_name = tool_info.get("name", "unknown")
            
            # Determine success
            success = True
            if isinstance(content, dict):
                success = content.get("success", True)
            
            event = {
                "type": "tool_result",
                "timestamp": timestamp,
                "session_id": self.session_id,
                "tool_name": tool_name,
                "tool_id": tool_id,
                "success": success,
            }
            self.events.append(event)
            
            if self.verbose:
                status = "[OK]" if success else "[FAIL]"
                logger.info(f"{status} [Tool Result] {tool_name}: {'Success' if success else 'Failed'}")
        
        # Text chunk - accumulate for full response
        elif "data" in kwargs:
            text = kwargs.get("data", "")
            if isinstance(text, str):
                self._current_response += text
        
        # Message complete - log full response
        elif "message" in kwargs:
            msg = kwargs.get("message", {})
            role = msg.get("role") if isinstance(msg, dict) else None
            
            if role == "assistant" and self._current_response:
                event = {
                    "type": "assistant_response",
                    "timestamp": timestamp,
                    "session_id": self.session_id,
                    "response_length": len(self._current_response),
                }
                self.events.append(event)
                
                if self.verbose:
                    # Log truncated response
                    preview = self._current_response[:500]
                    if len(self._current_response) > 500:
                        preview += "..."
                    logger.info(f"[Assistant Response]\n{preview}")
                
                # Reset for next response
                self._current_response = ""
        
        # Stop reason
        elif "stop_reason" in kwargs:
            reason = kwargs.get("stop_reason")
            event = {
                "type": "stop",
                "timestamp": timestamp,
                "session_id": self.session_id,
                "reason": reason,
            }
            self.events.append(event)
            
            if self.verbose and reason not in ("end_turn",):
                logger.info(f"[Stop] Reason: {reason}")
    
    def get_events(self) -> list[dict]:
        """Return all captured events."""
        return self.events
    
    def clear_events(self) -> None:
        """Clear captured events."""
        self.events = []
        self._current_response = ""


def create_event_callback(session_id: str | None = None, verbose: bool = True) -> AgentEventCallback:
    """Create an event callback for the agent."""
    return AgentEventCallback(session_id=session_id, verbose=verbose)


# Alias for backward compatibility
AgentLoggingCallback = AgentEventCallback
create_logging_callback = create_event_callback
