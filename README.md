# Auto-PPT Agent

> An AI agent that autonomously researches, plans, and generates PowerPoint presentations from a single sentence prompt — powered by a custom MCP (Model Context Protocol) architecture.

---

## Overview

Auto-PPT Agent is a full-stack application built for the **AI Agents & MCP Architecture** course. Given a prompt like *"Create a 10-slide presentation on Quantum Computing"*, the agent:

1. **Plans** the slide outline using an LLM (Groq / HuggingFace)
2. **Researches** each slide topic via DuckDuckGo / Wikipedia
3. **Generates** a relevant AI image per slide (HuggingFace / Pollinations)
4. **Builds** the `.pptx` file slide-by-slide through MCP tool calls
5. **Streams** real-time progress to a React frontend over WebSocket

All of this happens without the user doing anything after clicking **Generate Deck**.

---

## Architecture

The agent follows a deterministic agentic loop — it must explicitly plan before it can execute. This is enforced by the `submit_slide_plan` gate in the PPTX MCP server.

```
User Prompt
    │
    ▼
FastAPI Backend (WebSocket)
    │
    ├─► LLM (Groq / HuggingFace)
    │       └─► Plan N slide titles
    │
    └─► MCP Agentic Loop
            │
            ├─► MCP #1: pptx_mcp_server
            │       create_presentation → submit_slide_plan (gate)
            │       add_slide_with_image / add_slide (per slide)
            │       save_presentation
            │
            ├─► MCP #2: web_search_mcp_server
            │       search_topic (DuckDuckGo + Wikipedia fallback)
            │
            └─► MCP #3: hf_image_mcp_server
                    get_image_for_slide (HuggingFace → Pollinations → placeholder)
```

Each MCP server runs as a subprocess communicating over stdio — exactly as specified by the MCP protocol. The agent orchestrates all three in parallel sessions per presentation.

---

## Features

- **Dynamic slide count** — parses the prompt for numbers (`"10 slides"`, `"ten-slide"`, etc.)
- **3 MCP servers** — PPTX builder, web search, and AI image generation
- **Multi-LLM fallback chain** — Groq → HuggingFace (automatically switches if one fails)
- **Smart fallback content** — uses web search sentences as bullets if the LLM is unavailable
- **4 visual themes** — Napkin, Ocean, Dark Mode, Minimal
- **Real-time progress stream** — WebSocket pushes every agent step to the frontend
- **Save to custom folder** — copies the generated file to any path on the local machine
- **Graceful error handling** — never crashes; always produces a valid `.pptx`

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent Loop | Python `asyncio` + `mcp` SDK |
| LLM | Groq API (Llama 3.1) / HuggingFace Inference API |
| PPT Generation | `python-pptx` |
| Web Search | `duckduckgo-search` + Wikipedia fallback |
| Image Generation | HuggingFace `text_to_image` + Pollinations.ai fallback |
| Backend | FastAPI + Uvicorn + WebSockets |
| Frontend | React (Vite) + Lucide Icons |

---

## Project Structure

```
Agent_PPT/
├── backend/
│   ├── __init__.py
│   ├── agent_runner.py      # Main agentic loop — orchestrates all 3 MCP servers
│   └── server.py            # FastAPI app — WebSocket + REST endpoints
│
├── servers/
│   ├── pptx_mcp_server.py       # MCP #1 — builds the PowerPoint file
│   ├── web_search_mcp_server.py # MCP #2 — fetches real content per slide
│   └── hf_image_mcp_server.py   # MCP #3 — generates slide images
│
├── frontend/
│   └── src/
│       ├── App.jsx          # Main React UI — theme picker, live log, slide plan
│       └── index.css        # Glassmorphism dark UI
│
├── auto_ppt_output/         # All generated .pptx files saved here
├── config.py                # Reads .env and sets output paths
├── run_backend.py           # Entry point — starts the FastAPI server
├── requirements.txt
└── .env                     # API keys (not committed)
```

---

## Setup

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd Agent_PPT
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
pip install groq   # if using Groq (recommended)
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
# Groq — free API key, no credit card needed
# Sign up at https://console.groq.com
GROQ_API_KEY=gsk_your_key_here

# HuggingFace — needed for image generation
# Get your token at https://huggingface.co/settings/tokens
HUGGINGFACEHUB_API_TOKEN=hf_your_token_here

# Where generated PPT files are saved
AUTO_PPT_OUTPUT_DIR=C:/path/to/your/auto_ppt_output
```

> **Note:** Groq is recommended for text generation — it's free, fast, and works reliably. HuggingFace free-tier credits are used for image generation only.

### 5. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

---

## Running the Project

You need **two terminals** open simultaneously.

**Terminal 1 — Backend:**
```bash
python run_backend.py
```
Server starts at `http://localhost:8000`

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
```
UI opens at `http://localhost:5173`

---

## Usage

1. Open `http://localhost:5173` in your browser
2. Type a prompt — e.g. *"Create a 10-slide presentation on Machine Learning"*
3. Select a visual theme (Napkin, Ocean, Dark Mode, or Minimal)
4. Click **Generate Deck**
5. Watch the agent plan, research, generate images, and build the deck in real time
6. Click **Download** when complete, or use **Save to Folder** to copy it anywhere

---

## MCP Compliance

This project satisfies all MCP grading criteria:

| Requirement | Implementation |
|---|---|
| **≥ 2 MCP servers** | 3 servers: `pptx_mcp_server`, `web_search_mcp_server`, `hf_image_mcp_server` |
| **Planning gate** | `submit_slide_plan` must be called before any `add_slide` is allowed |
| **Agentic loop** | Per-slide loop: search → LLM → image → add_slide |
| **Graceful hallucination** | Falls back to web sentences if LLM unavailable; placeholder image if HF fails |
| **Valid `.pptx` output** | Professional themed slides with titles, bullets, images, and slide numbers |

---

## Assignment

**Course:** AI Agents & MCP Architecture  
**Assignment:** Auto-PPT Agent  
**Objective:** Build a functional agent that uses MCP servers to autonomously create a PowerPoint presentation from a single user prompt.
