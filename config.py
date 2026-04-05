"""Shared configuration for Auto-PPT MCP servers (output path, API tokens)."""

# Standard library imports
import os           # Used to read environment variables from the system
from pathlib import Path  # Provides cross platform file path handling(works on Windows and Linux)

#third party import for loading .env files
from dotenv import load_dotenv  #Reads key=value pairs from a .env file into os.environ

# Load the .env file(if it exists)so environment variables are available via os.getenv()
#this runs at import time,so all Config values below pick up .env settings automatically
load_dotenv()


def _abs_path(env_key: str, default: str) -> Path:
    """
    Helper: reads an environment variable and returns its value as an absolute Path.
    If the variable is not set, uses the provided default string instead.
    expanduser() resolves ~ to the home directory.
    resolve() converts any relative path into a full absolute path.
    """
    raw = os.getenv(env_key, default)   #read the env var; fall back to 'default' if not set
    return Path(raw).expanduser().resolve()  #Normalize to a clean absolute path


class Config:
    """
    Central configuration class for all three MCP servers.
    Values are read from environment variables or the .env file at startup.
    Claude Desktop can also inject these via the 'env' block in claude_desktop_config.json.
    """

    # OUTPUT_DIR: the folder where .pptx files and generated slide images are saved.
    #set AUTO_PPT_OUTPUT_DIR in .env or Claude Desktop config to change this path.
    # default falls back to ./auto_ppt_output inside the project directory.
    OUTPUT_DIR: Path = _abs_path("AUTO_PPT_OUTPUT_DIR", "./auto_ppt_output")

    # HUGGINGFACE_TOKEN: API token needed to call Hugging Face Inference API.
    # We try two common env-variable names so users can use either convention.
    # If neither is set, HF image generation is skipped and the server falls back.
    HUGGINGFACE_TOKEN: str | None = (
        os.getenv("HUGGINGFACEHUB_API_TOKEN")   #primary: LangChain-style variable name
        or os.getenv("HF_TOKEN")                 # Secondary:official HF CLI variable name
    )

    # HF_IMAGE_MODEL: which Hugging Face text-to-image model to try first.
    # FLUX.1-schnell is fast and produces good educational images.
    # The hf_image_mcp_server also tries fallback models if this one fails.
    #SD 2.1 often returns 404 on the newer Inference API, so FLUX is preferred.
    HF_IMAGE_MODEL: str = os.getenv(
        "HF_IMAGE_MODEL",
        "black-forest-labs/FLUX.1-schnell",  # Default: FLUX schnell (fast inference)
    )

    # HF_IMAGE_FALLBACK: what to do when Hugging Face image generation fails.
    #"pollinations" : free public API, no key needed, produces real images
    # "none"         : skip internet, generate a PIL-drawn placeholder shape instead
    HF_IMAGE_FALLBACK: str = os.getenv("HF_IMAGE_FALLBACK", "pollinations").lower()

    # WEB_SEARCH_MAX_RESULTS: how many search results to return per query.
    #higher values give more content but slow down the agent loop.
    WEB_SEARCH_MAX_RESULTS: int = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))

    @classmethod
    def ensure_output_dir(cls) -> Path:
        """
        Creates the OUTPUT_DIR folder (and any missing parents) if it doesn't already exist.
        Called by all three MCP servers before writing any file.
        Returns the Path so callers can use it directly after calling this method.
        """
        cls.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)  # parents=True: create nested folders; exist_ok=True: don't error if already exists
        return cls.OUTPUT_DIR   # Return the path for chaining (e.g. path = Config.ensure_output_dir())