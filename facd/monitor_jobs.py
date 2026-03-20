# monitor_jobs.py
#
# SSE endpoint for streaming job updates to clients.
# Uses callback interface to receive notifications when jobs change.

import asyncio
import json
from typing import Set

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()

# Reference to BuildState, set during app startup
_build_state = None
# Event that gets set when jobs change
_jobs_changed_event: asyncio.Event = None
# Lock for thread-safe event creation
_event_lock = asyncio.Lock()


def set_build_state(state):
    global _build_state
    _build_state = state
    
    # Register callback with BuildState
    state.add_callback(_on_jobs_changed)


def _on_jobs_changed():
    """Callback invoked by BuildState when jobs change."""
    global _jobs_changed_event
    if _jobs_changed_event is not None:
        # Set the event in a thread-safe way
        # Since callbacks may come from a different thread, we need to be careful
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(_jobs_changed_event.set)
        except RuntimeError:
            # No running loop, try to set directly
            _jobs_changed_event.set()


def jobs_to_json(jobs):
    """Convert jobs list to JSON string for comparison and transmission."""
    return json.dumps(jobs, sort_keys=True, default=str)


async def job_event_generator():
    """
    Generator that yields SSE events when jobs change.
    Uses callback notifications to detect changes, with periodic polling as fallback.
    """
    global _jobs_changed_event
    
    # Create the event for this generator
    _jobs_changed_event = asyncio.Event()
    
    last_jobs_json = None
    
    try:
        while True:
            if _build_state is None:
                await asyncio.sleep(1)
                continue
            
            try:
                jobs = _build_state.get_jobs()
                current_jobs_json = jobs_to_json(jobs)
                
                # Only send if changed (or first time)
                if current_jobs_json != last_jobs_json:
                    last_jobs_json = current_jobs_json
                    yield f"data: {current_jobs_json}\n\n"
                
            except Exception as e:
                error_data = json.dumps({"error": str(e)})
                yield f"data: {error_data}\n\n"
            
            # Wait for either the callback event or a timeout (fallback polling)
            try:
                await asyncio.wait_for(_jobs_changed_event.wait(), timeout=5.0)
                _jobs_changed_event.clear()
            except asyncio.TimeoutError:
                # Fallback: check anyway in case we missed a callback
                pass
    finally:
        _jobs_changed_event = None


@router.get("/monitor_jobs")
async def monitor_jobs():
    """
    SSE endpoint that streams job updates.
    Sends a JSON array of jobs whenever the jobs list changes.
    """
    return StreamingResponse(
        job_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )
