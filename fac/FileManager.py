import asyncio
import json
import os
from typing import AsyncGenerator

from fac.util.FastAPI import *
from fac.util.targets import *

from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from watchfiles import awatch, Change


class EditFileRequest(BaseModel):
    content: str


class FileManager(Routable):
    def __init__(self, targets_dict):
        self.targets_dict = targets_dict
        self.files: dict[str, dict] = {}
        self._subscribers: list[asyncio.Queue] = []
        self._shutdown = False
        super().__init__()

    def get_fresh_paths(self):
        return [path for path, metainfo in self.files.items() if metainfo['status'] == 'fresh']

    def add(self, path, status):
        self._validate_path(path)

        # compute meta-info for path
        targets = match_pattern_starstar(self.targets_dict, path)
        if len(targets) == 0: # happens when path doesn't correspond
            target = path
            mime = 'unknown'
        elif len(targets) == 1:
            target, variables = targets[0]
            mime = self.targets_dict[target]['mime-type']
        else:
            raise ValueError('path corresponds to multiple targets; this should never happen with a correct fac.yaml file')

        # actually add path
        if path in self.files and self.files[path]['status'] == 'fresh' and status == 'queued':
            # do not overwrite fresh status with queued status
            pass
        else:
            self.files[path] = {
                    'status': status,
                    'target': target,
                    'mime-type': mime,
                    }
            self._notify(path)

    def _validate_path(self, path: str) -> None:
        '''
        Validate that path is safe (no directory traversal, no absolute paths).
        '''
        if os.path.isabs(path):
            raise HTTPException(status_code=400, detail="Absolute paths are not allowed")
        if ".." in path.split(os.sep):
            raise HTTPException(status_code=400, detail="Directory traversal is not allowed")
        normalized = os.path.normpath(path)
        if normalized.startswith(".."):
            raise HTTPException(status_code=400, detail="Directory traversal is not allowed")

    '''
    FIXME:
    add/remove?

    def __contains__(self, path: str) -> bool:
        return path in self.files

    def __len__(self) -> int:
        return len(self.files)

    def __iter__(self):
        return iter(self.files)
    '''

    ##############################
    # async helpers
    ##############################

    def start(self):
        self._watch_task = asyncio.create_task(self._watch_files())

    async def shutdown(self):
        self._shutdown = True
        self._stop_event.set()
        if self._watch_task:
            await self._watch_task
        for queue in self._subscribers:
            await queue.put(None)

    @property
    def _stop_event(self):
        if not hasattr(self, "_stop_event_obj"):
            self._stop_event_obj = asyncio.Event()
        return self._stop_event_obj

    async def _watch_files(self):
        async for changes in awatch(".", stop_event=self._stop_event):
            for change_type, abs_path in changes:
                path = os.path.relpath(abs_path)
                targets = match_pattern_starstar(self.targets_dict, path)
                path_matches_target = len(targets) > 0
                if path not in self.files and not path_matches_target:
                    continue
                if change_type == Change.deleted:
                    self.files[path]['status'] = 'deleted'
                else:
                    self.files[path]['status'] = 'fresh'
                self._notify(path)

    ##############################
    # FastAPI endpoints
    ##############################

    def _file_event(self, path: str) -> dict:
        info = self.files[path]
        if info['mime-type'].startswith('text'):
            try:
                with open(path, "r") as f:
                    content = f.read()
            except FileNotFoundError:
                content = None
        else:
            content = None
        return {
            "path": path,
            "content": content,
            **info
        }

    def _notify(self, path: str):
        event = self._file_event(path)
        for queue in self._subscribers:
            queue.put_nowait(event)

    async def _event_stream(self, request: Request) -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        try:
            for path in self.files:
                if await request.is_disconnected():
                    return
                event = self._file_event(path)
                yield f"data: {json.dumps(event)}\n\n"
            while not self._shutdown:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    if event is None:
                        break
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    continue
        finally:
            self._subscribers.remove(queue)

    @route("/monitor_files", methods=["GET"])
    async def monitor_files(self, request: Request) -> StreamingResponse:
        '''
        Stream file events via Server-Sent Events (SSE).

        On connection, sends the current state of all files that correspond to a target in the 'fac.yaml' file.
        Then streams real-time updates whenever a file is added or its status changes.

        Each event is a JSON object with fields:
        - path
        - mime-type
        - content (may be None for large files) 
        - target: the target in 'fac.yaml' that the specified path was generated from
        - status:
            - "fresh": the file exists and is up-to-date (all newly created/edited/built files will have a fresh status)
            - "building": the file is currently being built
            - "queued": the file is queued to be built in the future
            - "stale": the file exists but needs to be rebuilt because dependencies have been modified
            - "deleted": the file has been deleted
        ```
        '''
        # FIXME:
        # The graceful shutdown code in this route does not work.
        # When someone connects to this route, facd will hang on shutdown.
        return StreamingResponse(
            self._event_stream(request),
            media_type="text/event-stream",
        )

    @route("/contents", methods=["GET"])
    async def contents(self, path):
        '''
        Get the contents of a file.
        Primarily useful for downloading large binary files whose contents are not returned with the /monitor_files route.
        '''
        self._validate_path(path)
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"File not found: {path}")
        return FileResponse(path)

    @route("/edit_file/{path:path}", methods=["PUT"])
    async def edit_file(self, path: str, body: EditFileRequest) -> dict:
        '''
        Edit a file's contents.

        Only works for files with mime-types starting with "text/".
        The file must already be tracked by the FileManager.

        Args:
            path: The relative path to the file
            body: JSON body with "content" field containing the new file contents

        Returns:
            {"status": "ok", "path": path}
        '''
        self._validate_path(path)

        if path not in self.files:
            raise HTTPException(status_code=404, detail=f"File not tracked: {path}")

        mime_type = self.files[path].get("mime-type", "")
        if not mime_type.startswith("text/"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot edit file with mime-type '{mime_type}'. Only text/* files are editable."
            )

        # Ensure parent directory exists
        parent_dir = os.path.dirname(path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        with open(path, "w") as f:
            f.write(body.content)

        self.files[path]["status"] = "fresh"
        self._notify(path)

        return {"status": "ok", "path": path}

    @route("/delete_file/{path:path}", methods=["DELETE"])
    async def delete_file(self, path: str) -> dict:
        '''
        Delete a file.

        The file must already be tracked by the FileManager.

        Args:
            path: The relative path to the file

        Returns:
            {"status": "ok", "path": path}
        '''
        self._validate_path(path)

        if path not in self.files:
            raise HTTPException(status_code=404, detail=f"File not tracked: {path}")

        if os.path.exists(path):
            os.remove(path)

        self.files[path]["status"] = "deleted"
        self._notify(path)

        return {"status": "ok", "path": path}
