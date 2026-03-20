# monitor_jobs.py
#
# SSE endpoint for streaming job updates to clients.
# Internally polls get_jobs() and sends events only when jobs change.

import asyncio
import json
from typing import Set

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()

# Reference to BuildState, set during app startup
_build_state = None

def set_build_state(state):
    global _build_state
    _build_state = state


def jobs_to_json(jobs):
    """Convert jobs list to JSON string for comparison and transmission."""
    return json.dumps(jobs, sort_keys=True, default=str)


async def job_event_generator():
    """
    Generator that yields SSE events when jobs change.
    Polls get_jobs() every second and sends an event only if the data changed.
    """
    last_jobs_json = None
    
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
        
        await asyncio.sleep(1)


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
