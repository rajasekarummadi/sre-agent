"""
Anchor main agent: LangGraph implementation of
  catalog resolve -> forced planning (todo_write) -> tool loop -> gate/review -> answer

Pairs with anchor_system_prompt.md (loaded at startup).

Install:
  pip install langgraph langchain-core langchain-openai langchain-mcp-adapters httpx pydantic

Env:
  OPENAI_API_KEY, ANCHOR_MODEL (default gpt-5.1)
  CATALOG_URL            REST endpoint of your service catalog (optional; stub used if unset)
  SKILLS_DIR             git-synced folder of <skill-name>/SKILL.md
  SKILLS_GIT_PULL_SECS   how often to `git pull` the skills dir (default 300)
  SPILL_DIR              where oversized tool outputs are written
  ANCHOR_MCP_SERVERS     JSON dict of MCP servers (see DEFAULT_MCP_SERVERS)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

import httpx
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

log = logging.getLogger("anchor")

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
MODEL = os.getenv("ANCHOR_MODEL", "gpt-5.1")
PROMPT_FILE = Path(os.getenv("ANCHOR_PROMPT_FILE", "anchor_system_prompt.md"))
SKILLS_DIR = Path(os.getenv("SKILLS_DIR", "./skills"))
SPILL_DIR = Path(os.getenv("SPILL_DIR", "/tmp/anchor_spill"))
CATALOG_URL = os.getenv("CATALOG_URL", "")

MAX_STEPS = int(os.getenv("ANCHOR_MAX_STEPS", "40"))        # LLM calls per run
MAX_GATE_ROUNDS = int(os.getenv("ANCHOR_MAX_GATE_ROUNDS", "2"))
MAX_NUDGES = int(os.getenv("ANCHOR_MAX_NUDGES", "3"))
# Plan is enforced only for real investigations: incident/webhook intake, or
# once the run has made this many data-gathering tool calls. Simple questions
# answered with 1-2 calls are never nudged or reviewed.
PLAN_REQUIRED_SOURCES = {x.strip() for x in os.getenv("ANCHOR_PLAN_REQUIRED_SOURCES", "incident,webhook").split(",") if x.strip()}
PLAN_REQUIRED_AFTER_CALLS = int(os.getenv("ANCHOR_PLAN_REQUIRED_AFTER_CALLS", "3"))
# Tools allowed to repeat with identical args (e.g. polling status after a change).
REPEAT_EXEMPT_TOOLS = {x.strip() for x in os.getenv("ANCHOR_REPEAT_EXEMPT_TOOLS", "").split(",") if x.strip()}
TOOL_MAX_CHARS = int(os.getenv("ANCHOR_TOOL_MAX_CHARS", "20000"))  # spill above this
SPILL_PREVIEW_CHARS = 2000
MAX_PARALLEL_TOOLS = int(os.getenv("ANCHOR_MAX_PARALLEL_TOOLS", "6"))  # protect cluster/API load

# Placeholders: replace URLs / transports with your real MCP servers.
DEFAULT_MCP_SERVERS: dict[str, dict] = {
    "anchor-kube": {"url": "http://localhost:8001/mcp", "transport": "streamable_http"},
    "anchor-gitlab": {"url": "http://localhost:8002/mcp", "transport": "streamable_http"},
    "anchor-panorama": {"url": "http://localhost:8003/mcp", "transport": "streamable_http"},
    "anchor-kibana": {"url": "http://localhost:8004/mcp", "transport": "streamable_http"},
    "anchor-now": {"url": "http://localhost:8005/mcp", "transport": "streamable_http"},
}

NUDGE_TEXT = (
    "Finish or close the remaining tasks before answering. "
    "If there is no plan yet, call `todo_write` now."
)
REVIEW_TEXT = (
    "Review before answering:\n"
    "1. Does your draft answer the original question?\n"
    "2. Does the why-chain end at an actionable cause, not a symptom? "
    "If not, ask 'why?' once more about the last link and add a task.\n"
    "3. Is every link backed by specific tool output or marked as a hypothesis?\n"
    "4. Did you check other plausible causes, or list them as unchecked?\n"
    "If gaps remain, call `todo_write` with the next phase of tasks and continue. "
    "Otherwise give the final answer in the required format."
)
FINALIZE_TEXT = (
    "Step limit reached. Give your best final answer now using only what you "
    "have verified. Mark unverified links as hypotheses and list what was not checked."
)


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    request: str
    catalog_context: str
    todos: list[dict]
    steps: int
    gate_rounds: int
    nudges: int
    reviewed: bool
    gate_action: str          # "continue" | "done"
    seen_calls: list[str]     # repeat-call guard
    source: str               # "chat" | "incident" | "webhook" | "api"
    tool_calls_made: int      # data-gathering calls (excludes todo_write)


# --------------------------------------------------------------------------- #
# Prompt loading
# --------------------------------------------------------------------------- #
def load_system_template() -> str:
    text = PROMPT_FILE.read_text()
    start = text.index("## SYSTEM PROMPT") + len("## SYSTEM PROMPT")
    end = text.index("## GATE PROMPT")
    body = text[start:end].strip()
    return body.rstrip("-").strip()  # drop the trailing '---' separator


_last_good_template: str = load_system_template()  # fail fast at startup


def current_template() -> str:
    """Re-read the prompt file per run so edits apply without a restart.
    A broken edit (missing section headers, unreadable file) falls back to the
    last good version instead of failing investigations."""
    global _last_good_template
    try:
        _last_good_template = load_system_template()
    except Exception:
        log.exception("prompt file invalid; using last good version")
    return _last_good_template


def render_plan(todos: list[dict]) -> str:
    if not todos:
        return "(no plan yet - call todo_write FIRST)"
    return "\n".join(f"[{t['status']}] {t['id']}: {t['content']}" for t in todos)


def build_system_prompt(state: State) -> str:
    prompt = current_template().replace(
        "{{catalog_context}}", state.get("catalog_context") or "(catalog not queried)"
    ).replace("{{skill_catalog}}", skills.catalog_text())
    return f"{prompt}\n\n## Current plan\n{render_plan(state.get('todos', []))}"


# --------------------------------------------------------------------------- #
# Service catalog (stub: swap in your real API shape)
# --------------------------------------------------------------------------- #
HOST_RE = re.compile(r"\b[a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+)+\b", re.I)
NS_RE = re.compile(r"(?:namespace|ns|-n)\s*[=:]?\s*([a-z0-9\-]+)", re.I)
ERR_RE = re.compile(r"\b(?:[45]\d\d|x509[^\s]*|ECONN\w+|OOMKilled|CrashLoopBackOff)\b", re.I)
SVC_RE = re.compile(r"\b([a-z][a-z0-9]+(?:-[a-z0-9]+)+)\b", re.I)  # kebab-case names


def extract_hints(request: str) -> dict[str, list[str]]:
    uniq = lambda xs: sorted(set(x.lower() for x in xs))
    return {
        "hosts": uniq(HOST_RE.findall(request)),
        "namespaces": uniq(NS_RE.findall(request)),
        "service_candidates": uniq(SVC_RE.findall(request)),
        "errors": uniq(ERR_RE.findall(request)),
    }


class CatalogClient:
    """Replace `lookup` with your catalog's real call (REST or MCP)."""

    async def lookup(self, request: str, hints: dict) -> list[dict]:
        if not CATALOG_URL:
            log.warning("CATALOG_URL not set; returning empty catalog result (stub)")
            return []
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(CATALOG_URL, json={"text": request, "hints": hints})
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else data.get("matches", [])


catalog = CatalogClient()


def format_catalog(matches: list[dict], hints: dict) -> str:
    hint_line = f"Hints extracted from request: {json.dumps(hints)}"
    if len(matches) == 1:
        return (
            "STATUS: single match. Treat as starting scope; verify against live data.\n"
            f"{json.dumps(matches[0], indent=2)}\n{hint_line}"
        )
    if len(matches) > 1:
        return (
            f"STATUS: {len(matches)} possible matches. Your FIRST task is to disambiguate.\n"
            f"{json.dumps(matches[:10], indent=2)}\n{hint_line}"
        )
    return (
        "STATUS: no match. Your FIRST task is to retry catalog_lookup with spelling "
        "variations, substrings and hostnames, then ask the user one specific question.\n"
        + hint_line
    )


async def catalog_lookup_impl(query: str) -> str:
    """Tool form of the catalog, so the model can retry/disambiguate."""
    matches = await catalog.lookup(query, extract_hints(query))
    return json.dumps(matches[:10], indent=2) if matches else "No matches."


# --------------------------------------------------------------------------- #
# Skills (git-synced SKILL.md folders)
# --------------------------------------------------------------------------- #
class Skills:
    def __init__(self, root: Path):
        self.root = root
        self.index: dict[str, tuple[str, Path]] = {}
        self.refresh_index()

    def refresh_index(self) -> None:
        index = {}
        for md in self.root.glob("*/SKILL.md"):
            text = md.read_text()
            fm = re.match(r"^---\n(.*?)\n---", text, re.S)
            meta = fm.group(1) if fm else ""
            name = (re.search(r"^name:\s*(.+)$", meta, re.M) or [None, md.parent.name])[1].strip()
            desc = (re.search(r"^description:\s*(.+)$", meta, re.M) or [None, ""])[1].strip()
            index[name] = (desc, md)
        self.index = index

    def catalog_text(self) -> str:
        if not self.index:
            return "(no skills available)"
        return "\n".join(f"- {n}: {d}" for n, (d, _) in sorted(self.index.items()))

    def fetch(self, name: str) -> str:
        item = self.index.get(name)
        if not item:
            return f"Unknown skill '{name}'. Available: {', '.join(sorted(self.index))}"
        return item[1].read_text()

    async def sync_loop(self, every: int) -> None:
        """Periodic git pull so pushed skill changes reach a running agent."""
        while True:
            await asyncio.sleep(every)
            try:
                if (self.root / ".git").exists():
                    subprocess.run(
                        ["git", "-C", str(self.root), "pull", "--ff-only"],
                        check=True, capture_output=True, timeout=60,
                    )
                self.refresh_index()
            except Exception:
                log.exception("skill sync failed; keeping last good index")


skills = Skills(SKILLS_DIR)


# --------------------------------------------------------------------------- #
# Tools owned by anchor-main
# --------------------------------------------------------------------------- #
class TodoItem(BaseModel):
    id: str
    content: str
    status: Literal["pending", "in_progress", "completed"]
    priority: Literal["high", "medium", "low"] = "medium"


class TodoWriteArgs(BaseModel):
    todos: list[TodoItem] = Field(description="Complete task list (replaces the previous one).")


def _noop(**_: Any) -> str:  # todo_write is intercepted in tools_node
    return "ok"


todo_write = StructuredTool.from_function(
    func=_noop,
    name="todo_write",
    description=(
        "Create/update the investigation task list. MUST be called FIRST for any "
        "investigation of 3+ steps. Send the complete list each time. Mark tasks "
        "in_progress before starting and completed immediately when done. Add a "
        "follow-up task for every finding ('why did this happen?')."
    ),
    args_schema=TodoWriteArgs,
)


async def _catalog_tool(query: str) -> str:
    return await catalog_lookup_impl(query)


catalog_lookup_tool = StructuredTool.from_function(
    coroutine=_catalog_tool,
    name="catalog_lookup",
    description="Look up microservices in the service catalog by name, host, namespace or error text.",
)


def _fetch_skill(name: str) -> str:
    return skills.fetch(name)


fetch_skill = StructuredTool.from_function(
    func=_fetch_skill,
    name="fetch_skill",
    description="Fetch a skill's full steps by name. Only when it clearly matches the issue.",
)


def _read_spilled(path: str, grep: str = "", offset: int = 0, limit: int = 8000) -> str:
    p = Path(path).resolve()
    if SPILL_DIR.resolve() not in p.parents:
        return "Error: path is outside the spill directory."
    text = p.read_text(errors="replace")
    if grep:
        rx = re.compile(grep, re.I)
        lines = [l for l in text.splitlines() if rx.search(l)]
        text = "\n".join(lines)
    return text[offset : offset + limit] or "(empty)"


read_spilled_output = StructuredTool.from_function(
    func=_read_spilled,
    name="read_spilled_output",
    description=(
        "Read a large tool output that was saved to disk. Use `grep` (regex) to "
        "filter lines, or `offset`/`limit` to page through it."
    ),
)

LOCAL_TOOLS = [todo_write, catalog_lookup_tool, fetch_skill, read_spilled_output]


# --------------------------------------------------------------------------- #
# Tool execution helpers: spill + repeat guard
# --------------------------------------------------------------------------- #
def stringify(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list):  # MCP content blocks
        parts = []
        for item in result:
            parts.append(item.get("text", json.dumps(item)) if isinstance(item, dict) else str(item))
        return "\n".join(parts)
    try:
        return json.dumps(result, default=str)
    except Exception:
        return str(result)


def spill_if_large(tool_name: str, text: str) -> str:
    if len(text) <= TOOL_MAX_CHARS:
        return text
    SPILL_DIR.mkdir(parents=True, exist_ok=True)
    path = SPILL_DIR / f"{tool_name}-{int(time.time())}-{uuid.uuid4().hex[:6]}.txt"
    path.write_text(text)
    return (
        f"[Output too large ({len(text)} chars); saved to {path}]\n"
        f"Preview:\n{text[:SPILL_PREVIEW_CHARS]}\n...\n"
        f"Use read_spilled_output(path='{path}', grep='<regex>') to inspect it."
    )


def call_key(call: dict) -> str:
    return f"{call['name']}:{json.dumps(call.get('args', {}), sort_keys=True, default=str)}"


# --------------------------------------------------------------------------- #
# Graph nodes
# --------------------------------------------------------------------------- #
llm: ChatOpenAI
llm_with_tools: Any
tools_by_name: dict[str, StructuredTool] = {}


async def catalog_node(state: State) -> dict:
    request = state["request"]
    hints = extract_hints(request)
    try:
        matches = await catalog.lookup(request, hints)
    except Exception as e:
        log.exception("catalog lookup failed")
        return {"catalog_context": f"STATUS: catalog unavailable ({e}). Proceed without it and say so."}
    return {"catalog_context": format_catalog(matches, hints)}


async def agent_node(state: State) -> dict:
    messages = [SystemMessage(build_system_prompt(state))] + state["messages"]
    resp = await llm_with_tools.ainvoke(messages)
    return {"messages": [resp], "steps": state["steps"] + 1}


def route_after_agent(state: State) -> Literal["tools", "gate", "finalize"]:
    last = state["messages"][-1]
    has_calls = isinstance(last, AIMessage) and bool(last.tool_calls)
    if has_calls:
        return "finalize" if state["steps"] >= MAX_STEPS else "tools"
    return "gate"


_tool_sem: asyncio.Semaphore | None = None


async def _run_tool(call: dict) -> str:
    global _tool_sem
    if _tool_sem is None:
        _tool_sem = asyncio.Semaphore(MAX_PARALLEL_TOOLS)
    async with _tool_sem:
        return await _run_tool_inner(call)


async def _run_tool_inner(call: dict) -> str:
    tool = tools_by_name.get(call["name"])
    if tool is None:
        return f"Error: unknown tool '{call['name']}'."
    try:
        result = await tool.ainvoke(call.get("args", {}))
        return spill_if_large(call["name"], stringify(result))
    except Exception as e:  # return errors to the model as evidence
        return f"Error running {call['name']}: {e}"


async def tools_node(state: State) -> dict:
    last = state["messages"][-1]
    todos, reviewed = state["todos"], state["reviewed"]
    seen = list(state["seen_calls"])
    outputs: dict[str, str] = {}
    to_run: list[dict] = []

    for call in last.tool_calls:
        if call["name"] == "todo_write":
            raw = call.get("args", {}).get("todos", [])
            try:
                todos = [TodoItem(**t).model_dump() if isinstance(t, dict) else dict(t) for t in raw]
            except Exception as e:  # bad args go back to the model, never crash the run
                outputs[call["id"]] = f"Error: invalid todo list ({e}). Send id, content, status."
                continue
            if any(t["status"] != "completed" for t in todos):
                reviewed = False  # new work was added; review again when done
            outputs[call["id"]] = "Plan updated:\n" + render_plan(todos)
            continue
        key = call_key(call)
        if key in seen and call["name"] not in REPEAT_EXEMPT_TOOLS:
            outputs[call["id"]] = (
                "Refusing: this exact call was already made this session. "
                "Use a different tool or change the parameters."
            )
            continue
        seen.append(key)
        to_run.append(call)

    results = await asyncio.gather(*(_run_tool(c) for c in to_run))  # parallel
    for call, text in zip(to_run, results):
        outputs[call["id"]] = text

    msgs = [
        ToolMessage(content=outputs[c["id"]], tool_call_id=c["id"], name=c["name"])
        for c in last.tool_calls
    ]
    return {
        "messages": msgs, "todos": todos, "reviewed": reviewed, "seen_calls": seen,
        "tool_calls_made": state["tool_calls_made"] + len(to_run),
    }


async def gate_node(state: State) -> dict:
    """Runs when the model produced an answer (no tool calls)."""
    if state["steps"] >= MAX_STEPS:
        return {"gate_action": "done"}

    todos = state["todos"]
    open_tasks = [t for t in todos if t["status"] != "completed"]
    needs_plan = (
        state["source"] in PLAN_REQUIRED_SOURCES
        or state["tool_calls_made"] >= PLAN_REQUIRED_AFTER_CALLS
    )
    if not todos and not needs_plan:
        return {"gate_action": "done"}  # simple question: answer as before

    if (not todos or open_tasks) and state["nudges"] < MAX_NUDGES:
        return {
            "messages": [HumanMessage(NUDGE_TEXT)],
            "nudges": state["nudges"] + 1,
            "gate_action": "continue",
        }
    if todos and not open_tasks and not state["reviewed"] and state["gate_rounds"] < MAX_GATE_ROUNDS:
        return {
            "messages": [HumanMessage(REVIEW_TEXT)],
            "reviewed": True,
            "gate_rounds": state["gate_rounds"] + 1,
            "gate_action": "continue",
        }
    return {"gate_action": "done"}


def route_after_gate(state: State) -> Literal["agent", "__end__"]:
    return "agent" if state["gate_action"] == "continue" else END


async def finalize_node(state: State) -> dict:
    # Drop the dangling tool-call message so the history stays valid.
    msgs = list(state["messages"])
    if msgs and isinstance(msgs[-1], AIMessage) and msgs[-1].tool_calls:
        msgs = msgs[:-1]
    resp = await llm.ainvoke(
        [SystemMessage(build_system_prompt(state))] + msgs + [HumanMessage(FINALIZE_TEXT)]
    )
    return {"messages": [resp]}


def build_graph():
    g = StateGraph(State)
    g.add_node("catalog", catalog_node)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_node("gate", gate_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "catalog")
    g.add_edge("catalog", "agent")
    g.add_conditional_edges("agent", route_after_agent, ["tools", "gate", "finalize"])
    g.add_edge("tools", "agent")
    g.add_conditional_edges("gate", route_after_gate, ["agent", END])
    g.add_edge("finalize", END)
    return g.compile()


# --------------------------------------------------------------------------- #
# Setup + run
# --------------------------------------------------------------------------- #
async def setup() -> Any:
    """Load MCP tools, bind the LLM, start the skill sync task, return the graph."""
    global llm, llm_with_tools, tools_by_name
    from langchain_mcp_adapters.client import MultiServerMCPClient

    servers = json.loads(os.getenv("ANCHOR_MCP_SERVERS", "null")) or DEFAULT_MCP_SERVERS
    mcp_tools = await MultiServerMCPClient(servers).get_tools()
    all_tools = LOCAL_TOOLS + mcp_tools
    names = [t.name for t in all_tools]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:  # an MCP tool silently shadowing a local one would change behavior
        raise RuntimeError(f"Duplicate tool names: {dupes}. Rename before starting.")
    tools_by_name = {t.name: t for t in all_tools}

    llm = ChatOpenAI(model=MODEL)
    llm_with_tools = llm.bind_tools(all_tools)

    asyncio.create_task(skills.sync_loop(int(os.getenv("SKILLS_GIT_PULL_SECS", "300"))))
    return build_graph()


def initial_state(request: str, source: str = "chat") -> State:
    return {
        "messages": [HumanMessage(request)],
        "request": request,
        "catalog_context": "",
        "todos": [],
        "steps": 0,
        "gate_rounds": 0,
        "nudges": 0,
        "reviewed": False,
        "gate_action": "",
        "seen_calls": [],
        "source": source,
        "tool_calls_made": 0,
    }


async def investigate(graph, request: str, source: str = "chat") -> tuple[str, State]:
    final = await graph.ainvoke(initial_state(request, source), {"recursion_limit": 120})
    answer = next(
        (m.content for m in reversed(final["messages"])
         if isinstance(m, AIMessage) and not m.tool_calls),
        "(no answer)",
    )
    return answer, final


# --------------------------------------------------------------------------- #
# Minimal eval harness (extend with real incidents)
# --------------------------------------------------------------------------- #
EVAL_CASES = [
    {
        "name": "vault-static-secret-ownerref",
        "source": "incident",
        "request": (
            "Secret for <service> in <namespace> on <cluster> is not being synced from "
            "Vault; the VaultStaticSecret target Secret has no ownerReference. Why?"
        ),
        # TODO: fill with the real root-cause keywords once you know the answer.
        "must_mention": ["VaultStaticSecret", "operator"],
        "min_plan_tasks": 3,
    },
]


async def run_evals() -> None:
    graph = await setup()
    for case in EVAL_CASES:
        answer, final = await investigate(graph, case["request"], case.get("source", "incident"))
        missing = [k for k in case["must_mention"] if k.lower() not in answer.lower()]
        planned = len(final["todos"]) >= case["min_plan_tasks"]
        status = "PASS" if not missing and planned else "FAIL"
        print(f"[{status}] {case['name']} steps={final['steps']} "
              f"todos={len(final['todos'])} missing={missing}")


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    async def _main() -> None:
        if len(sys.argv) > 1 and sys.argv[1] == "eval":
            await run_evals()
            return
        graph = await setup()
        request = " ".join(sys.argv[1:]) or input("Describe the issue: ")
        answer, _ = await investigate(graph, request)
        print(answer)

    asyncio.run(_main())
