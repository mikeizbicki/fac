from contextlib import asynccontextmanager
from importlib.resources import files
from typing import Optional, Set
import asyncio
import logging
import sys

from fac.Errors import *
from fac.Fac import BuildState
from fac.Logging import *

from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uvicorn

from fastapi.responses import FileResponse
from facd import git_routes
from facd import monitor_jobs

################################################################################
# FastAPI setup
################################################################################

@asynccontextmanager
async def lifespan(app: FastAPI):
    # the lifespan function allows us to create/destroy variables
    # that will be used when running FastAPI
    # but not when the file is loaded in other contexts (e.g. doctests)

    # register state routes
    state = BuildState()
    state.file_manager.start()
    app.include_router(state.router)
    app.include_router(state.file_manager.router)

    # register git routes
    app.include_router(git_routes.router)

    # register monitor_jobs routes and set build state reference
    monitor_jobs.set_build_state(state)
    app.include_router(monitor_jobs.router)

    # perform a dryrun to register all files with facd;
    # build_all=False allows facd startup to continue,
    # and the build_daemon will run the build concurrently
    # in the background thread
    state.full_dryrun(build_all=False)
    state.build_daemon()

    yield

    # cleanup code here
    await state.built_paths.shutdown()
    await git_routes.shutdown_git_routes()

app = FastAPI(title="fac build server", lifespan=lifespan)

# prepare /static mount point
static_path = files("facd") / "static"
app.mount("/static", StaticFiles(directory=static_path), name="static")

# prepare templates
templates_path = files("facd") / "static"
templates = Jinja2Templates(directory=str(templates_path))


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/favicon.ico")
def favicon():
    return FileResponse(static_path / "favicon.ico")


################################################################################
# streaming client logs
################################################################################

# Store connected client queues
log_queues: Set[asyncio.Queue] = set()

class BroadcastHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        for queue in log_queues:
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                pass

# Attach handler to your build system logger
#logger = logging.getLogger("fac")  # adjust to match your logger name
handler = BroadcastHandler()
#handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
handler.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(handler)

async def log_generator():
    queue = asyncio.Queue(maxsize=100)
    log_queues.add(queue)
    try:
        while True:
            msg = await queue.get()
            yield f"data: {msg}\n\n"
    finally:
        log_queues.discard(queue)

@app.get("/logs_stream")
async def stream_logs():
    return StreamingResponse(
        log_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

################################################################################
# run the server
################################################################################

def main():
    uvicorn.run(
            app,
            host='localhost',
            port=8080,
            timeout_graceful_shutdown=1,
            log_level='warning',
            )

if __name__ == '__main__':
    main()
