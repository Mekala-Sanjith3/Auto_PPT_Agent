"""
MCP server: slide images via Hugging Face Inference,with fallbacks when HF errors (401/404).
saves generated images under AUTO_PPT_OUTPUT_DIR/images/ so pptx_mcp_server can embed them.
the tool tries three methods in order: HF API - Pollinations (free) - PIL placeholder shape.
"""

#allow newer type hint syntax on older Python versions e.g: str | None
from __future__ import annotations

import io          #used to wrap raw bytes in a file-like object for PIL to open
import logging     # Standard Python logging - lets us print status messages to stderr
import sys         # needed for sys.path manipulation and logging to stderr
import urllib.parse    # URL-encodes the image prompt for the Pollinations API call
import urllib.request  # Built in HTTP client for downloading images
import uuid        # Generates random unique filenames so slide images never overwrite each other
from pathlib import Path  # cross platform path handling

#add project root to Python path so we can import config.py from here
ROOT = Path(__file__).resolve().parent.parent   # Navigate up:servers/ → Agent_PPT/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))   #Ensure project root is first in path

# FastMCP: the framework that makes Python functions into MCP-callable tools
from mcp.server.fastmcp import FastMCP

# PIL (Pillow): used to open/save images and draw placeholder shapes
from PIL import Image, ImageDraw

# Shared config: output directory path,HF token,fallback mode, etc.
from config import Config

# Set up a module level logger so we can write status messages to stderr
# without interfering with the MCP stdio protocol on stdout.
logger = logging.getLogger("hf_image_mcp")   # Named logger for this module

# Only add a handler if none have been added yet (avoids duplicate log lines on reload)
if not logger.handlers:
    h = logging.StreamHandler(sys.stderr)    #write log output to stderr (not stdout)
    h.setFormatter(logging.Formatter("[hf-image] %(message)s"))  # Simple prefix format
    logger.addHandler(h)

logger.setLevel(logging.INFO)   # Log INFO-level messages and above


# create the MCP server. The 'instructions' string tells the LLM when/how
# to use this server's tools and what to do if the token is missing.

mcp = FastMCP(
    "AutoPPTHFImage",   # Server identifier used in Claude Desktop config
    instructions=(
        "Call get_image_for_slide(prompt) per slide; pass the returned file path to AutoPPT add_slide_with_image. "
        "If Hugging Face returns 401, set a valid HUGGINGFACEHUB_API_TOKEN (read + Inference access). "
        "When HF is unavailable, the server falls back to Pollinations (free images) or a clean placeholder — "
        "never raw API errors on slides."
    ),
)

# HTTP User Agent header for all outgoing requests (polite identification)
USER_AGENT = "AutoPPT-MCP/1.0 (educational; +https://huggingface.co)"


def _hf_token_ok(token: str | None) -> bool:
    """
    Validates that the HF token looks like a real token before attempting API calls.
    Returns False if the token is missing, too short, or still the placeholder value.
    This avoids wasting time on an API call we know will fail with 401.
    """
    if not token:
        return False       # No token provided at all
    t = token.strip()
    if len(t) < 8:
        return False       # Suspiciously short - not a real HF token
    if "replace" in t.lower() or t.startswith("hf_xxx"):
        return False       # User forgot to swap out the example placeholder token
    return True            # Token looks plausible - proceed with the API call



# Default style suffix appended to every image prompt.
# This guides the AI model toward producing clean images
_DEFAULT_STYLE = (
    "flat vector infographic, soft pastel colors, friendly modern napkin-style illustration, "
    "clean light background, no text or letters in the image, educational poster look"
)


def _placeholder_image(path: Path, label: str) -> None:
    """
    Creates a decorative placeholder PNG using PIL drawing primitives.
    Used when both HF and Pollinations are unavailable.
    The image is purely geometric/colorful - no words - so it still looks
    intentional on the slide rather than an obvious error state.
    """
    path.parent.mkdir(parents=True, exist_ok=True)  # Create images/folder if it doesn't exist

    # Square canvas (512×512) matches the image generation output
    # and fills the tall right column of the slide.
    w, h = 512, 512

    # Define colors that match the napkin theme palette
    cream = (252, 250, 247)    # Background - same warm off-white as the slides
    coral = (255, 107, 107)    # Accent color - matches the slide accent bar
    teal  = (0, 206, 172)      # Secondary accent - matches theme accent2
    mist  = (232, 236, 239)    # Light grey - used for the main inner rectangle

    # Create a new blank RGB image filled with the cream background
    img = Image.new("RGB", (w, h), color=cream)
    draw = ImageDraw.Draw(img)   # Drawing context for adding shapes on top

    # Left vertical accent bar
    draw.rectangle([0, 0, 28, h], fill=coral)

    # Rounded rectangle:the main visual element in the center of the image
    draw.rounded_rectangle(
        [80, 90, w - 80, h - 90],   # (x0, y0, x1, y1) with margins on all sides
        radius=36,                   # Corner radius in pixels
        fill=mist,
        outline=teal,
        width=3,
    )

    # Three decorative circles in the top-right area to add visual interest
    for cx, cy in [(w - 160, 120), (w - 90, 210), (w - 200, 280)]:
        draw.ellipse([cx, cy, cx + 56, cy + 56], fill=teal)  # Filled teal circles

    # One coral circle in the bottom-left for balance
    draw.ellipse([120, h - 200, 220, h - 100], fill=coral)

    img.save(path, format="PNG")   # Save the finished image as PNG


def _try_hf_text_to_image(prompt: str, out: Path) -> bool:
    """
    Attempts to generate an image using the Hugging Face Inference API.
    Tries multiple models in sequence; returns True if any model succeeds and saves a valid image.
    Returns False if the token is invalid, the package is missing, or all models fail.
    """
    token = Config.HUGGINGFACE_TOKEN   # Read token from environment/config

    # Validate the token before making any HTTP call - saves time on obvious failures
    if not _hf_token_ok(token):
        logger.info("Skipping HF: missing or placeholder HUGGINGFACEHUB_API_TOKEN")
        return False

    # Build a list of models to try, starting with the configured primary model
    models: list[str] = []
    primary = (Config.HF_IMAGE_MODEL or "").strip()
    if primary:
        models.append(primary)   # Put the user-configured model first

    # Append fallback models in order of preference
    for m in (
        "black-forest-labs/FLUX.1-schnell",     # Fast, high quality, free tier
        "stabilityai/stable-diffusion-2-1",      # Older model, sometimes more available
        "runwayml/stable-diffusion-v1-5",        # Classic SD 1.5 as last resort
    ):
        if m not in models:
            models.append(m)

    # Try to import the HF client library (only available if huggingface_hub is installed)
    try:
        from huggingface_hub import InferenceClient
    except ImportError:
        return False   # Package not installed — can't use HF API

    # Creating two client configurations:
    #1. With explicit provider="hf-inference" (matches the new serverless docs)
    #2. Without provider (uses the library's default routing logic)
    clients = [
        InferenceClient(token=token, provider="hf-inference"),  # Preferred: explicit routing
        InferenceClient(token=token),                            # Fallback: auto-routing
    ]

    #Try every combination of client and model until one works
    for client in clients:
        for model_id in models:
            try:
                # Call the text-to-image API
                # Square format (512×512) fills the tall right column in the slide perfectly.
                image = client.text_to_image(
                    prompt,
                    model=model_id,
                    height=512,   # square — scales nicely into the tall image column
                    width=512,
                )

                if image is None:
                    continue   # API returned nothing - try next model

                # Ensure the output images/ directory exists
                out.parent.mkdir(parents=True, exist_ok=True)

                #API may return bytes or a PIL Image object - handle both
                if isinstance(image, (bytes, bytearray)):
                    # Raw bytes: wrap in BytesIO, open with PIL, convert to RGB, save
                    Image.open(io.BytesIO(bytes(image))).convert("RGB").save(out, format="PNG")
                elif hasattr(image, "save"):
                    # PIL Image object: save directly
                    image.save(out)
                else:
                    continue   #unknown return type - skip this model

                #verify the saved file is a real image
                if out.is_file() and out.stat().st_size > 2000:   #> 2 KB is a reasonable minimum
                    logger.info("HF image OK model=%s", model_id)
                    return True   # Success! Valid image saved at out path

            except Exception as e:
                logger.info("HF model %s failed: %s", model_id, e)
                continue   # This model/client combination failed - try the next one

    return False   # All combinations failed - caller will try next fallback strategy


def _try_pollinations(prompt: str, out_png: Path) -> bool:
    """
    Downloads a free AI-generated image from Pollinations.ai (no API key required).
    Used as the second fallback when Hugging Face is unavailable.
    Returns True if a valid image was downloaded and saved, False otherwise.
    """
    # Skip if the user configured a different fallback mode
    if Config.HF_IMAGE_FALLBACK != "pollinations":
        return False

    try:
        # Clean up the prompt: collapse whitespace and truncate to 400 chars (URL length limit)
        safe = " ".join(prompt.split())[:400]

        # URL-encode the prompt for safe inclusion in the query string
        q = urllib.parse.quote(safe)

        # Square image (512×512) — fills tall right column on slides
        url = (
            f"https://image.pollinations.ai/prompt/{q}"
            "?width=512&height=512"
            "&nologo=true"
            "&enhance=false"
        )

        # Create the HTTP GET request
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")

        # Download the image with a generous 120-second timeout (Pollinations can be slow)
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()   # Read all bytes (the full PNG/JPEG image data)

        # Sanity check: reject suspiciously small responses (probably an error page, not an image)
        if len(data) < 2000:
            return False

        # Open the downloaded bytes with PIL, convert to RGB (standardize format), and save as PNG
        im = Image.open(io.BytesIO(data)).convert("RGB")
        out_png.parent.mkdir(parents=True, exist_ok=True)   # Ensure output directory exists
        im.save(out_png, format="PNG")

        # Final check: confirm the file was actually written and has content
        return out_png.is_file() and out_png.stat().st_size > 2000

    except Exception as e:
        logger.info("Pollinations fallback failed: %s", e)
        return False   # Network error or PIL failure - signal caller to use placeholder


# MCP tool: get_image_for_slide
# The single public tool this server exposes.
# Called by Claude once per slide in the agentic loop.
@mcp.tool()
def get_image_for_slide(prompt: str, style_hint: str = _DEFAULT_STYLE) -> str:
    """
    Generates or retrieves an image for a presentation slide and saves it to disk.
    Always returns a valid file path - never raises an error - by falling through
    three strategies until one succeeds.

    Strategy order:
    1.Hugging Face Inference API (best quality, requires HF token)
    2.pollinations.ai (free, no key, real AI images, may be slow)
    3. PIL-drawn placeholder (geometric shapes, always works, offline)

    Returns the absolute path to the saved PNG file.
    """
    # make sure the base output directory exists (creates it if missing)
    Config.ensure_output_dir()

    #create the images/ subfolder inside the output directory
    img_dir = Config.OUTPUT_DIR / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    #generate a unique filename using a random UUID to avoid overwriting previous slide images
    # hex[:12] gives us 12 hex chars (e.g. "3f7a9c1b04e2") - enough uniqueness for a deck
    out_png = img_dir / f"slide_{uuid.uuid4().hex[:12]}.png"

    #combine the slide-specific prompt with the style guidance for better results
    full_prompt = f"{prompt}. {style_hint}".strip()

    #attempt 1: Hugging Face text-to-image
    if _try_hf_text_to_image(full_prompt, out_png):
        return str(out_png.resolve())   # Return the absolute path of the saved image

    # attempt 2: Pollinations free image API
    if _try_pollinations(full_prompt, out_png):
        logger.info("Using Pollinations fallback image")
        return str(out_png.resolve())   # Return the absolute path of the saved image

    #attempt 3: PIL-drawn geometric placeholder (always succeeds)
    logger.info("Using clean PIL placeholder (no API errors shown)")
    _placeholder_image(out_png, prompt)  # Draw colored shapes onto a blank canvas
    return str(out_png.resolve())        # Return the path even for the placeholder


# Entry point: when this script is run directly, start the MCP server.
# Claude Desktop starts it via the command in claude_desktop_config.json
# and communicates using the stdio (standard input/output) MCP protocol.
if __name__ == "__main__":
    mcp.run()   #blocks indefinitely, listening for tool calls over stdio