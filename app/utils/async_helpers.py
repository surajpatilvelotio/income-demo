"""Async-to-sync utility helpers.

Provides thread-safe execution of async coroutines in sync contexts.
This is necessary for Strands @tool decorated functions which must be sync,
but need to call async database operations.
"""

import asyncio
import concurrent.futures
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")


def run_sync(coro: Coroutine[Any, Any, T], timeout: float = 30) -> T:
    """
    Run an async coroutine in a sync context.
    
    Uses ThreadPoolExecutor to run asyncio.run() in a separate thread,
    which avoids event loop conflicts when called from within an existing
    async context (e.g., FastAPI handlers).
    
    This is the recommended pattern for calling async code from sync
    tool functions that may be invoked during agent execution.
    
    Args:
        coro: The async coroutine to execute
        timeout: Maximum time to wait for completion (default: 30 seconds)
        
    Returns:
        The result of the coroutine
        
    Raises:
        TimeoutError: If execution exceeds timeout
        Exception: Any exception raised by the coroutine
        
    Example:
        async def fetch_user(user_id: str) -> User:
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(User).where(User.id == user_id))
                return result.scalar_one_or_none()
        
        # From a sync function:
        user = run_sync(fetch_user("user-123"))
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result(timeout=timeout)

