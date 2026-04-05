import json
import os
import re
from fastapi import WebSocket
from huggingface_hub import AsyncInferenceClient
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from dotenv import load_dotenv

load_dotenv()

# Word numbers so the user can say "ten slides" and we understand it
_WORD_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "twenty": 20,
}


def _parse_slide_count(prompt: str, default: int = 5) -> int:
    """Pull out how many slides the user asked for from their prompt.
    Handles '10 slides', 'ten-slide', '7 slide deck' etc.
    Caps at 20 so the loop doesn't run forever. Defaults to 5."""
    text = prompt.lower()

    # digit before 'slide' — e.g. "10 slides", "10-slide"
    m = re.search(r'(\d+)\s*[-\s]?slides?', text)
    if m:
        return max(1, min(int(m.group(1)), 20))

    # word number before 'slide' — e.g. "ten slides", "five-slide"
    words = '|'.join(_WORD_NUMS.keys())
    m = re.search(rf'({words})\s*[-\s]?slides?', text)
    if m:
        return max(1, min(_WORD_NUMS[m.group(1)], 20))

    return default


def _extract_json(text: str):
    """Pull the first JSON array out of an LLM reply.
    Handles markdown fences like ```json ... ```."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    return json.loads(text)


async def run_agent(prompt: str, websocket: WebSocket, theme: str = "ocean"):
    await websocket.send_json({"type": "status", "message": "Starting planning phase..."})

    # --- LLM Setup ---
    # We try Groq first because it's free and fast.
    # If no Groq key, we fall back to HuggingFace Inference API.
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    hf_token  = os.getenv("HUGGINGFACEHUB_API_TOKEN", "").strip() or \
                os.getenv("HF_TOKEN", "").strip()

    if not groq_key and not hf_token:
        await websocket.send_json({
            "type": "error",
            "message": "No API key found. Add GROQ_API_KEY or HUGGINGFACEHUB_API_TOKEN to .env"
        })
        return

    # HF models to try in order (many require paid credits now)
    _env_hf_model = os.getenv("HF_TEXT_MODEL", "").strip()
    _HF_MODELS = [m for m in [
        _env_hf_model,
        "mistralai/Mistral-7B-Instruct-v0.3",
        "HuggingFaceH4/zephyr-7b-beta",
        "Qwen/Qwen2.5-72B-Instruct",
    ] if m]

    # Groq free-tier models, fastest first
    _GROQ_MODELS = [
        "llama-3.1-8b-instant",
        "llama3-8b-8192",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
    ]

    async def _llm_chat(messages: list, max_tokens: int = 400,
                        temperature: float = 0.4) -> str | None:
        """Call the LLM. Tries Groq first, falls back to HuggingFace."""

        # Strategy 1 — Groq (get free API key at console.groq.com)
        if groq_key:
            try:
                from groq import AsyncGroq
                groq_client = AsyncGroq(api_key=groq_key)
                for gm in _GROQ_MODELS:
                    try:
                        resp = await groq_client.chat.completions.create(
                            messages=messages, model=gm,
                            max_tokens=max_tokens, temperature=temperature,
                        )
                        return resp.choices[0].message.content
                    except Exception as ge:
                        err = str(ge).lower()
                        if "rate_limit" in err or "429" in err:
                            print(f"  Groq rate-limited on {gm}, trying next...")
                            continue
                        print(f"  Groq {gm} error: {ge}")
                        continue
            except ImportError:
                print("  groq package not installed — run: pip install groq")

        # Strategy 2 — HuggingFace Inference API
        if hf_token:
            for model_id in _HF_MODELS:
                try:
                    client = AsyncInferenceClient(model=model_id, token=hf_token)
                    resp = await client.chat_completion(
                        messages=messages, max_tokens=max_tokens, temperature=temperature
                    )
                    return resp.choices[0].message.content
                except Exception as e:
                    err = str(e).lower()
                    if "not supported" in err or "402" in err or "payment" in err:
                        print(f"  HF {model_id} not available: skipping")
                    else:
                        print(f"  HF {model_id} error: {e}")
                    continue

        return None  # all strategies failed

    # --- Step 1: Figure out how many slides to make ---
    slide_count = _parse_slide_count(prompt)
    await websocket.send_json({
        "type": "status",
        "message": f"Detected slide count: {slide_count} slides"
    })

    # --- Step 2: Ask LLM to plan the slide titles ---
    await websocket.send_json({"type": "status", "message": f"Planning {slide_count} slides..."})
    plan_prompt = (
        f'You are a presentation planner.\n'
        f'Generate a list of exactly {slide_count} slide titles for a PowerPoint about:\n'
        f'"{prompt}"\n\n'
        f'Rules:\n'
        f'- Return ONLY a raw JSON array of exactly {slide_count} strings\n'
        f'- No markdown, no backticks, no explanation\n'
        f'- Example: ["Title 1", "Title 2", ..., "Title {slide_count}"]\n'
    )

    # Generic fallback titles in case the LLM is unavailable
    _fallback_base = [
        "Introduction", "Background & Context", "Key Concepts", "Core Principles",
        "Deep Dive", "Case Studies", "Real-World Applications", "Challenges & Limitations",
        "Future Outlook", "Summary & Next Steps", "References", "Q&A",
    ]
    fallback_titles = [
        _fallback_base[i] if i < len(_fallback_base) else f"Section {i + 1}"
        for i in range(slide_count)
    ]

    try:
        reply = await _llm_chat(
            messages=[{"role": "user", "content": plan_prompt}],
            max_tokens=max(300, slide_count * 30),
            temperature=0.3,
        )
        if reply:
            titles = _extract_json(reply)
            if not isinstance(titles, list) or not titles:
                raise ValueError("LLM did not return a list")
            titles = [str(t).strip() for t in titles]
            if len(titles) < slide_count:
                titles += fallback_titles[len(titles):slide_count]
            titles = titles[:slide_count]
        else:
            raise ValueError("No reply from any model")
    except Exception as e:
        print(f"Planning failed ({e}), using generic titles.")
        titles = fallback_titles

    await websocket.send_json({"type": "plan", "slides": titles})

    # --- Step 3: Start MCP servers and build the PPTX ---
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ppt_params = StdioServerParameters(
        command="python", args=[os.path.join(root, "servers", "pptx_mcp_server.py")])
    web_params = StdioServerParameters(
        command="python", args=[os.path.join(root, "servers", "web_search_mcp_server.py")])
    img_params = StdioServerParameters(
        command="python", args=[os.path.join(root, "servers", "hf_image_mcp_server.py")])

    topic_base = re.sub(r"[^\w\-]", "_", prompt[:20].strip()) or "presentation"
    filename = f"{topic_base}.pptx"

    slide_plan_json = json.dumps([{"title": t, "bullets": ["TBD"]} for t in titles])

    try:
        async with (
            stdio_client(ppt_params) as (pr, pw),
            stdio_client(web_params) as (wr, ww),
            stdio_client(img_params) as (ir, iw),
        ):
            async with (
                ClientSession(pr, pw) as ppt,
                ClientSession(wr, ww) as web,
                ClientSession(ir, iw) as img,
            ):
                await ppt.initialize()
                await web.initialize()
                await img.initialize()

                # Create the presentation file and lock in the slide plan
                await websocket.send_json({
                    "type": "status",
                    "message": f"Creating presentation with theme: {theme}"
                })
                await ppt.call_tool("create_presentation", arguments={
                    "topic": prompt[:60],
                    "filename_base": topic_base,
                    "theme_name": theme
                })

                await websocket.send_json({"type": "status", "message": "Submitting slide plan..."})
                await ppt.call_tool("submit_slide_plan", arguments={"plan_json": slide_plan_json})

                # Process each slide one by one
                for i, title in enumerate(titles):
                    slide_num = i + 1

                    await websocket.send_json({"type": "slide_active", "index": i})
                    await websocket.send_json({
                        "type": "progress",
                        "message": f"Processing slide {slide_num}/{len(titles)}: '{title}'"
                    })

                    # Search the web for content about this slide topic
                    await websocket.send_json({
                        "type": "status",
                        "message": f"[MCP web_search] Searching: '{title}'"
                    })
                    search_text = ""
                    try:
                        s_res = await web.call_tool("search_topic",
                                                    arguments={"query": f"{title} {prompt}"})
                        search_text = s_res.content[0].text if s_res.content else ""
                    except Exception as e:
                        print(f"  Search error slide {slide_num}: {e}")

                    # Ask LLM to write bullet points using the search context
                    bullet_prompt = (
                        f'You are writing slide {slide_num} of {len(titles)} '
                        f'for a presentation about: "{prompt}"\n'
                        f'Slide title: "{title}"\n'
                        f'Context from web: {search_text[:800] if search_text else "Use your own knowledge."}\n\n'
                        f'Generate exactly 4 concise, factual bullet points (max 18 words each).\n'
                        f'Each bullet must be SPECIFIC to "{title}" — no generic filler.\n'
                        f'Return ONLY a raw JSON array of 4 strings. No markdown, no explanation.\n'
                    )

                    # If LLM fails, extract real sentences from the web search results
                    def _search_fallback(text: str, slide_title: str, n: int = 4) -> list:
                        if not text:
                            return [
                                f"{slide_title} is a fundamental concept in this field",
                                f"{slide_title} plays an important role in modern applications",
                                f"Research on {slide_title} is growing rapidly",
                                f"{slide_title} has practical implications across industries",
                            ]
                        sentences = re.split(r'(?<=[.!?])\s+', text)
                        cleaned = [
                            s.strip().lstrip('- \u2022\u25cf')
                            for s in sentences
                            if 10 < len(s.strip()) < 120 and not s.strip().startswith('http')
                        ]
                        result = cleaned[:n]
                        while len(result) < n:
                            result.append(f"{slide_title} — further reading recommended")
                        return result

                    bullets = _search_fallback(search_text, title)

                    try:
                        reply = await _llm_chat(
                            messages=[{"role": "user", "content": bullet_prompt}],
                            max_tokens=400, temperature=0.4
                        )
                        if reply:
                            parsed = _extract_json(reply)
                            if isinstance(parsed, list) and parsed:
                                bullets = [str(b).strip() for b in parsed[:5]]
                        else:
                            await websocket.send_json({
                                "type": "status",
                                "message": f"  ⚠ Using web research for slide {slide_num}"
                            })
                    except Exception as e:
                        print(f"  Bullet generation failed slide {slide_num}: {e}")

                    # Generate an image for this slide
                    await websocket.send_json({
                        "type": "status",
                        "message": f"[MCP hf_image] Generating image for '{title}'"
                    })
                    image_path = None
                    try:
                        img_res = await img.call_tool("get_image_for_slide", arguments={
                            "prompt": f"{title} illustration for a presentation about {prompt}"
                        })
                        image_path = img_res.content[0].text if img_res.content else None
                        if image_path:
                            await websocket.send_json({
                                "type": "status",
                                "message": f"  ✓ Image ready for slide {slide_num}"
                            })
                    except Exception as e:
                        print(f"  Image generation failed slide {slide_num}: {e}")

                    # Add the slide to the PPTX
                    await websocket.send_json({
                        "type": "status",
                        "message": f"[MCP pptx] Inserting slide {slide_num}"
                    })
                    bullets_json = json.dumps(bullets)
                    if image_path:
                        await ppt.call_tool("add_slide_with_image", arguments={
                            "title": title,
                            "bullets_json": bullets_json,
                            "image_path": image_path
                        })
                    else:
                        # Falls back to text-only if image generation failed
                        await ppt.call_tool("add_slide", arguments={
                            "title": title,
                            "bullets_json": bullets_json
                        })

                # Save the final file
                await websocket.send_json({"type": "status", "message": "Saving presentation..."})
                await ppt.call_tool("save_presentation", arguments={})
                await websocket.send_json({"type": "done", "file": filename})

    except Exception as e:
        print(f"Agent error: {e}")
        await websocket.send_json({"type": "error", "message": f"Agent error: {str(e)}"})
