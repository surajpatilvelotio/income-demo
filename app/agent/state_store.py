"""Simple file-based state persistence for agent sessions.

Strands' FileSessionManager persists conversation history, but agent state
is only maintained in-memory within a single agent instance. This module
provides a simple file-based state store to persist state across API calls.
"""

import json
import logging
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class SessionStateStore:
    """File-based state persistence for agent sessions."""
    
    def __init__(self, storage_dir: str | None = None):
        self.storage_dir = Path(storage_dir or settings.session_storage_dir) / "state"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_state_file(self, session_id: str) -> Path:
        """Get the state file path for a session."""
        # Sanitize session_id to be a valid filename
        safe_id = session_id.replace("/", "_").replace("\\", "_")
        return self.storage_dir / f"{safe_id}.json"
    
    def load(self, session_id: str) -> dict:
        """Load state for a session. Returns empty dict if not found."""
        state_file = self._get_state_file(session_id)
        if state_file.exists():
            try:
                with open(state_file, "r") as f:
                    state = json.load(f)
                    logger.debug(f"Loaded state for session {session_id}: {state}")
                    return state
            except Exception as e:
                logger.warning(f"Failed to load state for session {session_id}: {e}")
        return {}
    
    def save(self, session_id: str, state: dict) -> None:
        """Save state for a session."""
        state_file = self._get_state_file(session_id)
        try:
            # Ensure directory exists (in case it was deleted)
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2, default=str)
            logger.debug(f"Saved state for session {session_id}: {state}")
        except Exception as e:
            logger.warning(f"Failed to save state for session {session_id}: {e}")
    
    def update(self, session_id: str, updates: dict) -> dict:
        """Update state for a session (merge with existing)."""
        state = self.load(session_id)
        state.update(updates)
        self.save(session_id, state)
        return state
    
    def get(self, session_id: str, key: str, default: Any = None) -> Any:
        """Get a specific value from session state."""
        state = self.load(session_id)
        return state.get(key, default)
    
    def set(self, session_id: str, key: str, value: Any) -> None:
        """Set a specific value in session state."""
        state = self.load(session_id)
        state[key] = value
        self.save(session_id, state)


# Global instance
state_store = SessionStateStore()

