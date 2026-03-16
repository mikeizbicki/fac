from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio
import subprocess
import json
import os
from watchfiles import awatch, Change

router = APIRouter()

# Track subscribers for git events
_git_subscribers: set = set()
_watch_task = None
_stop_event = None
_shutdown = False


class CheckoutRequest(BaseModel):
    ref: str


def _get_stop_event():
    global _stop_event
    if _stop_event is None:
        _stop_event = asyncio.Event()
    return _stop_event


def _get_diff_stats(commit_hash: str) -> list[dict]:
    """
    Get diff stats for a commit compared to its parent.
    
    Returns a list of dicts, each containing:
      - path: file path
      - additions: number of lines added
      - deletions: number of lines removed
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--numstat", f"{commit_hash}^", commit_hash],
            capture_output=True,
            text=True,
            check=True
        )
        
        stats = []
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split('\t')
                if len(parts) == 3:
                    additions, deletions, path = parts
                    # Handle binary files (shown as '-')
                    stats.append({
                        "path": path,
                        "additions": int(additions) if additions != '-' else 0,
                        "deletions": int(deletions) if deletions != '-' else 0
                    })
        return stats
    except subprocess.CalledProcessError:
        # This can fail for root commits or other edge cases
        return []


def _get_git_log(limit: int = 100) -> list[dict]:
    """
    Get git log as a list of commit dicts, including all commits from all refs and reflog.
    
    Each dict contains:
      - hash: short commit hash
      - full_hash: full commit hash
      - message: full commit message
      - author: author name
      - date: ISO format date
      - parents: list of parent full hashes
      - branches: list of branch names pointing to this commit
      - tags: list of tag names pointing to this commit
      - is_head: whether HEAD points to this commit
      - diff_stats: list of file change stats (path, additions, deletions)
    """
    try:
        # Get all commits from --all --reflog to include orphaned commits
        result = subprocess.run(
            [
                "git", "log",
                "--all", "--reflog",
                "--format=%h%x00%H%x00%an%x00%aI%x00%P%x00%B%x00%x01"
            ],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Get branch info: which branches point to which commits
        branch_result = subprocess.run(
            ["git", "branch", "-a", "--format=%(objectname:short) %(refname:short)"],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Get tag info
        tag_result = subprocess.run(
            ["git", "tag", "--format=%(objectname:short) %(refname:short)"],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Get current HEAD
        head_result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True
        )
        head_hash = head_result.stdout.strip()
        
        # Build branch map: hash -> list of branch names
        branch_map: dict[str, list[str]] = {}
        for line in branch_result.stdout.strip().split('\n'):
            if line:
                parts = line.split(' ', 1)
                if len(parts) == 2:
                    commit_hash, branch_name = parts
                    if commit_hash not in branch_map:
                        branch_map[commit_hash] = []
                    branch_map[commit_hash].append(branch_name)
        
        # Build tag map: hash -> list of tag names
        tag_map: dict[str, list[str]] = {}
        for line in tag_result.stdout.strip().split('\n'):
            if line:
                parts = line.split(' ', 1)
                if len(parts) == 2:
                    commit_hash, tag_name = parts
                    if commit_hash not in tag_map:
                        tag_map[commit_hash] = []
                    tag_map[commit_hash].append(tag_name)
        
        # Parse commits, deduplicating by full_hash
        commits = []
        seen_hashes = set()
        raw_commits = result.stdout.split('\x01')
        
        for raw_commit in raw_commits:
            raw_commit = raw_commit.strip()
            if not raw_commit:
                continue
            
            parts = raw_commit.split('\x00')
            if len(parts) >= 6:
                short_hash = parts[0]
                full_hash = parts[1]
                author = parts[2]
                date = parts[3]
                parents_str = parts[4]
                message = parts[5].strip()
                
                # Skip duplicates
                if full_hash in seen_hashes:
                    continue
                seen_hashes.add(full_hash)
                
                parents = parents_str.split() if parents_str else []
                
                commits.append({
                    "hash": short_hash,
                    "full_hash": full_hash,
                    "message": message,
                    "author": author,
                    "date": date,
                    "parents": parents,
                    "branches": branch_map.get(short_hash, []),
                    "tags": tag_map.get(short_hash, []),
                    "is_head": short_hash == head_hash,
                    "diff_stats": _get_diff_stats(full_hash)
                })
        
        return commits
        
    except subprocess.CalledProcessError:
        return []


async def _broadcast_git_state():
    """Send current git state to all subscribers."""
    commits = _get_git_log()
    data = json.dumps(commits)
    
    dead_subscribers = set()
    for queue in _git_subscribers:
        try:
            await queue.put(data)
        except Exception:
            dead_subscribers.add(queue)
    
    _git_subscribers.difference_update(dead_subscribers)


def _no_filter(change: Change, path: str) -> bool:
    """Accept all file changes, including .git directory."""
    return True


async def _watch_git_directory():
    """
    Watch the .git directory for changes and notify subscribers.
    
    When changes are detected, sends the full commit list to all subscribers.
    """
    global _shutdown

    git_dir = ".git"
    if not os.path.exists(git_dir):
        return
    
    stop_event = _get_stop_event()

    try:
        async for changes in awatch(git_dir, stop_event=stop_event, watch_filter=_no_filter):
            if _shutdown:
                break
            await _broadcast_git_state()
    except Exception:
        pass


def _ensure_watch_task():
    """Ensure the git directory watch task is running."""
    global _watch_task
    if _watch_task is None or _watch_task.done():
        _watch_task = asyncio.create_task(_watch_git_directory())


async def _git_event_generator(request: Request):
    """Generate SSE events for git changes."""
    queue: asyncio.Queue = asyncio.Queue()
    _git_subscribers.add(queue)
    _ensure_watch_task()
    
    try:
        # Send initial state
        commits = _get_git_log()
        yield f"data: {json.dumps(commits)}\n\n"
        
        while True:
            if await request.is_disconnected():
                break
            
            try:
                data = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {data}\n\n"
            except asyncio.TimeoutError:
                # Send keepalive
                yield ": keepalive\n\n"
    finally:
        _git_subscribers.discard(queue)


@router.get("/git_events")
async def git_events(request: Request):
    """
    SSE endpoint for git repository changes.
    
    Sends a JSON array of commit objects whenever the repository changes.
    Includes all commits reachable from any branch, tag, or reflog entry,
    suitable for rendering: git log --oneline --graph --all --decorate --reflog
    
    Each commit object contains:
      - hash: short commit hash
      - full_hash: full commit hash  
      - message: full commit message
      - author: author name
      - date: ISO format date
      - parents: list of parent full hashes
      - branches: list of branch names pointing to this commit
      - tags: list of tag names pointing to this commit
      - is_head: whether HEAD points to this commit
      - diff_stats: list of file change stats, each containing:
          - path: file path
          - additions: number of lines added
          - deletions: number of lines removed
    """
    return StreamingResponse(
        _git_event_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/git_checkout")
async def git_checkout(request: CheckoutRequest):
    """
    Checkout a specified commit hash, branch, or tag.
    
    Args:
        ref: The commit hash, branch name, or tag name to checkout
        
    Returns:
        JSON object with:
          - success: boolean indicating if checkout succeeded
          - message: success or error message
    """
    try:
        result = subprocess.run(
            ["git", "checkout", request.ref],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Broadcast the new git state to all subscribers
        await _broadcast_git_state()
        
        return {
            "success": True,
            "message": f"Successfully checked out '{request.ref}'"
        }
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "message": e.stderr.strip() or f"Failed to checkout '{request.ref}'"
        }


@router.on_event("shutdown")
async def shutdown_git_routes():
    """Clean up on shutdown."""
    global _shutdown, _watch_task
    _shutdown = True
    stop_event = _get_stop_event()
    stop_event.set()
    if _watch_task:
        _watch_task.cancel()
        try:
            await _watch_task
        except asyncio.CancelledError:
            pass
