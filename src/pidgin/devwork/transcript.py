"""Turns a run's Claude Code stream-json into a terminal-style transcript.

The owner watches workers in Pidgin the way they'd watch Claude Code in a
terminal: what it says, each tool call with its argument, a few lines of each
result, its todo list, and how it finished. Parsing is incremental and cached
per file, so many terminals polling every second or two stay cheap.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

MAX_OUT_LINES = 4
# How the runner words a forwarded Linear comment (runner._forward_comments).
_PIDGIN_RE = re.compile(r"^(?P<who>.+?) wrote in Pidgin:\s*(?P<body>.*)$", re.S)
_COMMENT_RE = re.compile(r"^(?P<who>.+?) commented on (?P<key>[A-Z][A-Z0-9]*-\d+) \((?P<url>[^)]*)\):\s*(?P<body>.*)$", re.S)
_cache: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _short_path(value: str, cwd: str | None) -> str:
    if cwd and value:
        try:
            rel = os.path.relpath(value, cwd)
            if not rel.startswith(".."):
                return rel.replace("\\", "/")
        except ValueError:
            pass
    return value


def _tool_label(name: str, inp: dict[str, Any], cwd: str | None) -> tuple[str, str]:
    """(display name, argument) the way Claude Code prints a tool call."""
    if name.startswith("mcp__ticket__"):
        action = name.removeprefix("mcp__ticket__")
        arg = (
            inp.get("body")
            or inp.get("summary")
            or inp.get("question")
            or inp.get("done")
            or inp.get("title")
            or ""
        )
        return f"ticket.{action}", str(arg).splitlines()[0][:160] if arg else ""
    if name == "Bash":
        return "Bash", str(inp.get("command") or "")
    if name in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
        return name, _short_path(str(inp.get("file_path") or inp.get("notebook_path") or ""), cwd)
    if name in ("Grep", "Glob"):
        arg = str(inp.get("pattern") or "")
        if inp.get("path"):
            arg += f", in {_short_path(str(inp['path']), cwd)}"
        return name, arg
    if name == "WebFetch":
        return "Fetch", str(inp.get("url") or "")
    if name == "Task" or name == "Agent":
        return "Agent", str(inp.get("description") or "")
    for key in ("command", "file_path", "pattern", "description", "query", "url"):
        if inp.get(key):
            return name, str(inp[key])
    return name, ""


def _result_lines(block: dict[str, Any], tool: dict[str, Any] | None) -> tuple[list[str], int]:
    content = block.get("content")
    if isinstance(content, list):
        text = "\n".join(
            str(c.get("text", "")) for c in content if isinstance(c, dict) and c.get("type") == "text"
        )
    else:
        text = str(content or "")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    name = (tool or {}).get("name", "")
    if not block.get("is_error"):
        if name == "Read":
            return [f"Read {len(text.splitlines())} lines"], 0
        if name in ("Write", "Edit", "MultiEdit"):
            return [lines[0][:200] if lines else "Updated"], 0
        if name in ("Grep", "Glob") and lines:
            return lines[:MAX_OUT_LINES], max(0, len(lines) - MAX_OUT_LINES)
    if not lines:
        return ["(no output)"], 0
    return [ln[:240] for ln in lines[:MAX_OUT_LINES]], max(0, len(lines) - MAX_OUT_LINES)


def _user_text(content: Any) -> str | None:
    """The text of a user message, or None when it carries tool results."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list) or any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    ):
        return None
    return "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict))


def _feed(state: dict[str, Any], evt: dict[str, Any]) -> None:
    entries: list[dict[str, Any]] = state["entries"]
    tools: dict[str, dict[str, Any]] = state["tools"]
    cwd = state.get("cwd")
    kind = evt.get("type")
    if kind == "system" and evt.get("subtype") == "init":
        if evt.get("cwd"):
            state["cwd"] = evt["cwd"]
        # A live session re-announces itself on every turn; show it once per session.
        if evt.get("session_id") and evt.get("session_id") == state.get("session"):
            return
        state["session"] = evt.get("session_id")
        entries.append(
            {
                "k": "init",
                "text": f"Claude Code · {evt.get('model', '?')} · session {str(evt.get('session_id', ''))[:8]}",
            }
        )
    elif kind == "assistant":
        for block in (evt.get("message") or {}).get("content", []) or []:
            btype = block.get("type")
            if btype == "text" and str(block.get("text", "")).strip():
                entries.append({"k": "say", "text": block["text"].strip()})
            elif btype == "tool_use":
                inp = block.get("input") or {}
                name = str(block.get("name", ""))
                if name == "TodoWrite":
                    entries.append(
                        {
                            "k": "todos",
                            "items": [
                                {"text": t.get("content", ""), "status": t.get("status", "pending")}
                                for t in inp.get("todos", [])
                            ],
                        }
                    )
                    continue
                label, arg = _tool_label(name, inp, cwd)
                entry = {"k": "tool", "name": label, "arg": arg, "status": "pending", "out": [], "more": 0}
                tools[str(block.get("id"))] = {"entry": entry, "name": name}
                entries.append(entry)
    elif kind == "user":
        content = (evt.get("message") or {}).get("content")
        text = _user_text(content)
        if text is not None:
            # Messages sent into the session, echoed back by Claude Code. The first
            # is the ticket prompt (shown at the top already); later ones are
            # forwarded comments.
            state["user_seen"] = state.get("user_seen", 0) + 1
            if state["user_seen"] > 1:
                m = _COMMENT_RE.match(text.strip())
                p = None if m else _PIDGIN_RE.match(text.strip())
                entries.append(
                    {
                        "k": "user",
                        "via": "linear" if m else "pidgin" if p else None,
                        "who": m.group("who") if m else p.group("who") if p else None,
                        "url": m.group("url") if m else None,
                        "text": (m.group("body") if m else p.group("body") if p else text).strip(),
                    }
                )
            return
        for block in content if isinstance(content, list) else []:
            if block.get("type") != "tool_result":
                continue
            tool = tools.pop(str(block.get("tool_use_id")), None)
            if tool is None:
                continue
            out, more = _result_lines(block, tool)
            tool["entry"].update(
                status="error" if block.get("is_error") else "ok", out=out, more=more
            )
    elif kind == "result":
        cost = evt.get("total_cost_usd")
        entries.append(
            {
                "k": "end",
                "ok": evt.get("subtype") == "success" and not evt.get("is_error"),
                "text": f"{'error' if evt.get('is_error') else evt.get('subtype', 'ended')} · {evt.get('num_turns', '?')} turns"
                + (f" · {int((evt.get('duration_ms') or 0) / 60000)} min" if evt.get("duration_ms") else "")
                + (f" · ≈${cost:.2f} at API prices" if cost else ""),
            }
        )


def transcript(log_dir: str | None, worktree: str | None = None, limit: int = 300) -> dict[str, Any]:
    """{prompt, entries, total} for one run; entries are the last ``limit``."""
    if not log_dir:
        return {"prompt": "", "entries": [], "total": 0}
    path = Path(log_dir) / "stream.jsonl"
    key = str(path)
    with _lock:
        state = _cache.get(key)
        if state is None:
            prompt = ""
            prompt_file = Path(log_dir) / "prompt.md"
            if prompt_file.exists():
                first = prompt_file.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                prompt = first[0].lstrip("# ").strip() if first else ""
            state = {"offset": 0, "rest": b"", "entries": [], "tools": {}, "cwd": worktree, "prompt": prompt}
            _cache[key] = state
        if path.exists():
            size = path.stat().st_size
            if size < state["offset"]:  # file replaced; start over
                state.update(offset=0, rest=b"", entries=[], tools={})
            if size > state["offset"]:
                with open(path, "rb") as fh:
                    fh.seek(state["offset"])
                    chunk = fh.read(size - state["offset"])
                state["offset"] = size
                data = state["rest"] + chunk
                *complete, state["rest"] = data.split(b"\n")
                for raw in complete:
                    try:
                        evt = json.loads(raw.decode("utf-8", errors="replace"))
                    except ValueError:
                        continue
                    if isinstance(evt, dict):
                        _feed(state, evt)
        entries = state["entries"]
        return {
            "prompt": state["prompt"],
            "entries": [dict(e) for e in entries[-limit:]],
            "total": len(entries),
        }
