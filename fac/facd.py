
from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from importlib.resources import files
from pydantic import BaseModel
from typing import Optional, Set
import asyncio
import logging
import uvicorn

from fac.Logging import *
from fac.Config import load_config
from fac.Fac import BuildState


################################################################################
# FastAPI setup
################################################################################

app = FastAPI(title="fac build server")

# prepare /static mount point
static_path = files("fac") / "static"
app.mount("/static", StaticFiles(directory=static_path), name="static")

# preparte templates
templates_path = files("fac") / "templates"
templates = Jinja2Templates(directory=str(templates_path))


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


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
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
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

@app.get("/logs/stream")
async def stream_logs():
    return StreamingResponse(
        log_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

################################################################################
# other routes
################################################################################

# register the BuildState routes
targets_dict = load_config('fac.yaml')
state = BuildState(targets_dict)
app.include_router(state.router)

# run the server
def main():
    uvicorn.run(app, host='localhost', port=8080)

if __name__ == '__main__':
    main()
