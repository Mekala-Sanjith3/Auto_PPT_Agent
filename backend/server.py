import sys
import os

# Make sure the project root is importable regardless of how uvicorn is launched
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import shutil
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.agent_runner import run_agent
from config import Config

app = FastAPI(title="Auto-PPT Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve generated PPTX files as static downloads
Config.ensure_output_dir()
app.mount("/download", StaticFiles(directory=str(Config.OUTPUT_DIR)), name="download")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "Auto-PPT Agent"}


class SaveToFolderRequest(BaseModel):
    filename: str
    target_dir: str


@app.post("/save-to-folder")
async def save_to_folder(req: SaveToFolderRequest):
    """Copy the generated PPTX to whatever folder the user wants.
    The original in auto_ppt_output is kept — this is a copy, not a move."""
    src = (Config.OUTPUT_DIR / req.filename).resolve()
    if not src.is_file():
        return JSONResponse(status_code=404, content={
            "success": False,
            "error": f"File '{req.filename}' not found."
        })

    dest_dir = Path(req.target_dir).expanduser().resolve()
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest_dir / src.name))
        return {"success": True, "saved_to": str(dest_dir / src.name)}
    except PermissionError:
        return JSONResponse(status_code=403, content={
            "success": False,
            "error": f"Permission denied for '{dest_dir}'."
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        data   = await websocket.receive_json()
        prompt = data.get("prompt", "").strip()
        theme  = data.get("theme", "ocean").strip() or "ocean"

        if not prompt:
            await websocket.send_json({"type": "error", "message": "No prompt provided."})
            return

        await run_agent(prompt, websocket, theme=theme)

    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
