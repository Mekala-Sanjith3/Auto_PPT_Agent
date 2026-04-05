
# Assignment: The "Auto-PPT" Agent

**Course:** AI Agents & MCP Architecture
**Objective:** To design and implement a functional agent that uses MCP servers to autonomously create a PowerPoint presentation based on a user's single-sentence prompt.

## The Challenge
Build an agent that accepts a prompt like *"Create a 5-slide presentation on the life cycle of a star for a 6th-grade class"* and outputs a **functional `.pptx` file** without the user touching the mouse.

## Requirements (Core Functionality)

| Feature | Requirement |
| :--- | :--- |
| **MCP Integration** | Must use at least 1 MCP Server (e.g., Filesystem, Web Search, or a custom PPT tool). |
| **Agentic Loop** | The agent must plan the slide structure before writing content. |
| **Content Generation** | Each slide must have a title and 3-5 bullet points (or an image placeholder). |
| **Output** | Saves a valid `.pptx` file to the local disk. |
| **Error Handling** | If the agent cannot find data, it must generate plausible content (hallucinate gracefully) rather than crashing. |

## Architecture Hints (Provide to Students)

You cannot use a single LLM call. You need a loop like this:

Prompt template=
User Input -> Agent Brain (LLM) -> Decision: "Write Slide 1"
             -> Tool Call (MCP: write_slide)
             -> Agent Brain -> Decision: "Write Slide 2"
             -> Tool Call...
             -> Agent Brain -> Decision: "Save File" -> FINISH
```

### Suggested MCP Tools to Build/Use:
1.  **`create_presentation`** – Initializes a new PPT file.
2.  **`add_slide`** – Adds a slide with a given layout.
3.  **`write_text`** – Fills title and body.
4.  **`search_web`** (optional) – Fetches real data for the topic.

## Deliverables
1.  **Code Repository** – All agent and MCP server code.
2.  **Video Demo (2 min)** – Showing the agent creating a PPT from scratch.
3.  **Reflection Document** – Answering:
    - Where did your agent fail its first attempt?
    - How did MCP prevent you from writing hardcoded scripts?

## Grading Rubric (100 pts)

| Criteria | Excellent (25) | Satisfactory (15) | Poor (5) |
| :--- | :--- | :--- | :--- |
| **Agentic Planning** | Agent explicitly plans outline before executing any slide tool. | Agent writes slides sequentially without a global plan. | Agent hardcodes slide order. |
| **MCP Usage** | Uses ≥2 MCP servers (e.g., filesystem + web search). | Uses 1 MCP server correctly. | Calls LLM directly without MCP. |
| **PPT Quality** | Slides are coherent, formatted, and error-free. | Slides exist but have formatting issues or repetition. | Output is corrupted or plain text. |
| **Robustness** | Handles vague prompts ("make a good ppt") and missing data. | Works only for exact, pre-tested prompts. | Crashes on any unexpected input. |

## Starter Code (Pseudocode – Provide This)

```python
# agent_ppt.py
import asyncio
from mcp import ClientSession, StdioServerParameters
from langchain.agents import create_react_agent

async def run_ppt_agent(user_request: str):
    # 1. Connect to MCP Servers
    ppt_server = await connect_mcp("python-pptx-mcp")  # Hypothetical
    search_server = await connect_mcp("web-search-mcp")
    
    # 2. Define Agent's Tools
    tools = [
        Tool(name="create_pptx", func=ppt_server.create_file),
        Tool(name="add_slide", func=ppt_server.insert_slide),
        Tool(name="search_topic", func=search_server.query)
    ]
    
    # 3. Agent Prompt (Crucial for planning)
    system_prompt = """
    You are a Presentation Agent.
    Step 1: Plan slide titles as an array.
    Step 2: For each title, call 'add_slide'.
    Step 3: Fill content using 'search_topic' or your own knowledge.
    Step 4: Never skip the planning step.
    """
    
    # 4. Run
    agent = create_react_agent(tools, system_prompt)
    result = await agent.arun(user_request)
    return result
```

