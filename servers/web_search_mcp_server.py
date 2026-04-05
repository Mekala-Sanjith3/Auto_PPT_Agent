"""
MCP server: lightweight web search for presentation research.
This server exposes a single MCP tool called search_topic() that Claude Desktop
calls during the agentic loop to fetch real facts before writing slide bullet points.
"""

#allow using newer type hint syntax (e.g. list[str]) on older Python versions
from __future__ import annotations

import json            #used to parse JSON responses from web APIs
import sys             # needed to modify sys.path so we can import from the project root
import urllib.parse    # Used to URL-encode query strings before sending HTTP requests
import urllib.request  #built in HTTP client - avoids needing the 'requests' package
from pathlib import Path  # cross-platform file paths

#add the project root folder to Python's module search path.
# this lets us do 'from config import Config' even when running this script
# directly from the servers/ subfolder rather than the project root.
ROOT = Path(__file__).resolve().parent.parent   # Go up two levels: servers/ → Agent_PPT/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))   #tnsert at position 0 so our config.py takes priority

#import FastMCP - the framework that turns Python functions into MCP tools
from mcp.server.fastmcp import FastMCP

#import our shared config (output dir, search result count, etc.)
from config import Config

#create the MCP server instance.
# the 'instructions' string is shown to the LLM so it knows how and when
# to call the tools this server exposes.
mcp = FastMCP(
    "AutoPPTWebSearch",   # Internal name used in Claude Desktop config
    instructions=(
        "Use search_topic(query) to gather facts before writing slide bullets. "
        "If results are thin, paraphrase safely or use general knowledge."
    ),
)

# HTTP User Agent header sent with all requests so APIs know who is calling
USER_AGENT = "AutoPPT-MCP/1.0 (educational research)"


# private helper: fetch DuckDuckGo Instant Answer (summary + related topics)
# this is the first fallback when the duckduckgo_search package fails.
# Uses the free DDG JSON API - no key required.
def _ddg_instant_answer(query: str) -> list[str]:
    """
    Calls the DuckDuckGo Instant Answer API and returns a list of text snippets.
    returns an empty list if the call fails or returns no useful content.
    """
    lines: list[str] = []   # accumulate result strings here
    try:
        # build the full API URL with URL-encoded query parameters
        url = (
            "https://api.duckduckgo.com/?"
            + urllib.parse.urlencode(
                {
                    "q": query,            # the search query
                    "format": "json",      # We want JSON back, not HTML
                    "no_html": "1",        # Strip HTML tags from the text fields
                    "skip_disambig": "1",  # Skip disambiguation pages, go straight to results
                }
            )
        )
        # create the HTTP GET request with our User-Agent header
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        # send the request and read the response (12-second timeout to avoid hanging)
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))  # Decode bytes → JSON dict

        # Extract the abstract summary text if available
        ab = data.get("AbstractText") or ""
        if ab:
            lines.append(f"DuckDuckGo summary:\n{ab}")  # Add summary as first result

        # extract up to 5 related topic snippets
        for t in data.get("RelatedTopics", [])[:5]:
            if isinstance(t, dict) and t.get("Text"):  # Only take items that have a text field
                lines.append(f"- {t['Text'][:400]}")   # Trim to 400 chars to keep it concise

    except Exception:
        pass   # Silently ignore any network error or JSON parse failure — we have other fallbacks

    return lines


# private helper: fetch a Wikipedia article summary using the MediaWiki API.
# this is the second fallback when both DDGS and DuckDuckGo Instant Answer fail.
def _wikipedia_summary(query: str) -> list[str]:
    """
    Searches Wikipedia for the query, then fetches the plain-text summary of
    the top matching article. Returns a list with one string, or empty list on failure.
    """
    try:
        # step 1: use Wikipedia's opensearch API to find the best article title for the query
        api = (
            "https://en.wikipedia.org/w/api.php?"
            + urllib.parse.urlencode(
                {
                    "action": "opensearch",    # OpenSearch format returns [query, titles, descs, urls]
                    "search": query[:200],     # Limit query length to 200 chars (API limit)
                    "limit": 1,               # only return the top 1 result
                    "namespace": 0,           # Namespace 0 = main article space (not Talk, User, etc.)
                    "format": "json",         # response format
                }
            )
        )
        req = urllib.request.Request(api, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=12) as resp:
            op = json.loads(resp.read().decode("utf-8", errors="replace"))

        # the opensearch response is [query_string, [titles], [descriptions], [urls]]
        titles = op[1] if len(op) > 1 else []   # Extract the list of matching article titles
        if not titles:
            return []   # no article found - bail out early

        title = titles[0]   # Use only the top match

        # step 2: URL-encode the article title and fetch the full summary from REST API
        enc = urllib.parse.quote(title.replace(" ", "_"), safe="")  # Encode spaces as underscores
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{enc}"

        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))

        extract = data.get("extract") or ""   # 'extract' contains the plain-text summary
        if extract:
            #return the summary, capped at 1200 chars to keep the slide content manageable
            return [f"Wikipedia ({data.get('title', title)}):\n{extract[:1200]}"]

    except Exception:
        pass   # silently ignore any failure - we'll return empty and caller decides what to do

    return []   # return empty list if anything went wrong


# MCP tool: search_topic
# this is the only public tool this server exposes.
# Claude calls it during the agentic loop to gather real facts before writing bullets.
@mcp.tool()
def search_topic(query: str) -> str:
    """
    Search the web for facts and summaries to use in slides.
    Returns short snippets from multiple sources.
    If all searches fail, returns a graceful hint telling Claude to use general knowledge.

    Strategy (in priority order):
    1. duckduckgo_search package (full text search, best quality)
    2. DuckDuckGo Instant Answer API (summary + related topics, no key needed)
    3. Wikipedia REST API (article summary, always available)
    4. Fallback message asking Claude to hallucinate plausibly
    """
    q = (query or "").strip()   # sanitize: remove leading/trailing whitespace

    # if the query is empty, there's nothing to search - tell Claude to make something up
    if not q:
        return "Empty query; invent plausible educational content from the presentation topic."

    lines: list[str] = []   # will hold all result snippets before joining into one string

    # strategy 1: use the duckduckgo_search library (best quality results)
    try:
        from duckduckgo_search import DDGS   # Only import if installed (optional dependency)

        max_r = Config.WEB_SEARCH_MAX_RESULTS   # how many results to fetch (from config, default 5)

        with DDGS() as ddgs:   # open a DuckDuckGo search session (handles cookies/session internally)
            for r in ddgs.text(q, max_results=max_r):   # Run a text search and iterate results
                title = r.get("title", "")   # Page title
                body  = r.get("body", "")    # Snippet / excerpt from the page
                href  = r.get("href", "")    # URL of the source page
                if title or body:
                    # Format each result as a readable block with title, snippet, and URL
                    lines.append(f"- {title}\n  {body}\n  {href}")

    except Exception:
        pass   # if duckduckgo_search is not installed or fails, move to next strategy

    #strategy 2: DuckDuckGo Instant Answer API (no extra package needed)
    if not lines:
        lines.extend(_ddg_instant_answer(q))  # Try the free DDG JSON API as fallback

    # strategy 3: Wikipedia summary (very reliable, always available)
    if not lines:
        lines.extend(_wikipedia_summary(q))   # Try Wikipedia REST API as last resort

    #strategy 4: complete failure - ask Claude to use its own knowledge
    if not lines:
        return (
            "No web results returned. Use plausible, grade-appropriate content from general knowledge."
        )

    # return all collected snippets joined into one string
    # Prefix with a note reminding the LLM to paraphrase, not copy verbatim
    return "Search results (use to paraphrase; do not copy long passages):\n" + "\n".join(lines)


# entry point: when run directly, start the MCP server process. 
# Claude Desktop launches this via the command in claude_desktop_config.json
# and communicates with it over stdio (standard input/output).
if __name__ == "__main__":
    mcp.run()   #blocks indefinitely, waiting for tool call messages from the MCP client