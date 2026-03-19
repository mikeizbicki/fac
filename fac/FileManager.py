from typing import AsyncGenerator
from collections import defaultdict
import asyncio
import json
import os

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
        self.path2context = {}
        self.path2status = {}
        self.rdeps = defaultdict(lambda: set())
        self._subscribers: list[asyncio.Queue] = []
        self._shutdown = False
        super().__init__()

    def get_fresh_paths(self):
        return [path for path, status in self.path2status.items() if status == 'fresh']

    def register_context(self, context, status):
        # do not register a context that can't resolve to a path
        if not context.path_safe():
            return

        self.path2context[context.path] = context

        # update rdeps
        for dep in context.dependencies_built:
            self.rdeps[dep['target']].add(context.path)

        # actually add path
        if context.path in self.path2status and self.path2status[context.path] == 'fresh' and status == 'queued':
            # do not overwrite fresh status with queued status
            pass
        else:
            if status == 'fresh' or context.mode != 'dryrun':
                mime_type = self.targets_dict.get(context.normalized_target, {}).get('mime-type')
                self._set_status(context.path, status)

    def _set_status(self, path, status, handle_rdeps=True):
        if handle_rdeps:
            for rdep in self.rdeps[path]:
                if rdep in self.path2status:
                    self._set_status(rdep, 'stale', handle_rdeps=False)
                    #rdep_context = self.path2context[rdep]
                    #if rdep_context.is_buildable():
                        #status = rdep_context.get_status()
                        #if 'out-of-date' in status:
                            #self._set_status(rdep, 'stale', handle_rdeps=False)
                        #else:
                            #self._set_status(rdep, 'fresh', handle_rdeps=False)

        self.path2status[path] = status
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
                if path not in self.path2status and not path_matches_target:
                    continue
                if change_type == Change.deleted:
                    self._set_status(path, 'deleted')
                else:
                    self._set_status(path, 'fresh')

    ##############################
    # FastAPI endpoints
    ##############################

    def _file_event(self, path: str) -> dict:
        context = self.path2context.get(path)
        if context:
            target = context.normalized_target
        else:
            target = path
        mime_type = self.targets_dict.get(target, {}).get('mime-type')
        info = {
            'status': self.path2status[path],
            'target': target,
            'mime-type': mime_type,
            }
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
            # NOTE:
            # we make a copy of self.path2status so that async changes to the dict
            # don't result in errors
            files_copy = dict(self.path2status)
            for path in files_copy:
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

        if path not in self.path2status:
            raise HTTPException(status_code=404, detail=f"File not tracked: {path}")

        # Ensure parent directory exists
        parent_dir = os.path.dirname(path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        with open(path, "w") as f:
            f.write(body.content)

        self._set_status(path, 'fresh')

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

        if path not in self.path2status:
            raise HTTPException(status_code=404, detail=f"File not tracked: {path}")

        if os.path.exists(path):
            os.remove(path)

        #self._set_status(path, "deleted")
        #self._notify(path)

        return {"status": "ok", "path": path}
