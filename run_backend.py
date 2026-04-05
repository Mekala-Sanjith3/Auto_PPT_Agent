"""
run_backend.py — Start the Auto-PPT FastAPI server from the project root.

Usage:
    python run_backend.py
    python run_backend.py --port 8001
    python run_backend.py --reload
"""

import sys
import os
import argparse

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-PPT backend")
    parser.add_argument("--host",   default="0.0.0.0")
    parser.add_argument("--port",   type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    print(f"\n Auto-PPT backend starting at  http://{args.host}:{args.port}")
    print(f" WebSocket endpoint:            ws://{args.host}:{args.port}/ws")
    print(f" Download endpoint:             http://{args.host}:{args.port}/download/<file>\n")

    uvicorn.run(
        "backend.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
