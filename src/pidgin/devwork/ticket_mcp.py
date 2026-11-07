"""Ticket tools for one Claude Code run: a tiny stdio MCP server (spec §5.6).

Launched by Claude Code from the run's mcp.json:
    python -m pidgin.devwork.ticket_mcp --db <workspace db> --run <run id>

Scoped to the run's single ticket. Reads the Linear key from the workspace DB
itself, so the key never appears in the run's environment, prompt or config.
Every call is recorded on the run's timeline.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from pidgin.db import connect
from pidgin.devwork import store
from pidgin.devwork.linear_api import LinearClient, LinearError
from pidgin.util.ids import utc_now_iso

PROTOCOL_VERSION = "2025-06-18"
MAX_COMMENTS = 12
MIN_COMMENT_GAP_S = 120

_READ_TOOL: dict[str, Any] = {
    "name": "read",
    "description": "Re-read this ticket: description, status and all comments (to see replies mid-run).",
    "inputSchema": {"type": "object", "properties": {}},
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "read",
        "description": "Re-read this ticket: description, status and all comments (to see replies mid-run).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "comment",
        "description": "Post a progress comment on this ticket (markdown). Only when something real happens.",
        "inputSchema": {
            "type": "object",
            "properties": {"body": {"type": "string"}},
            "required": ["body"],
        },
    },
    {
        "name": "in_review",
        "description": "Finish: the work is done and checked. Comments what changed and what to check, sets In Review and assigns the owner. Ends the run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "What changed, the commits, how you checked it.",
                },
                "check": {
                    "type": "string",
                    "description": "What the owner should check and exactly how.",
                },
            },
            "required": ["summary", "check"],
        },
    },
    {
        "name": "hand_off",
        "description": "Hand off to the owner (status unchanged, assigned to the owner) with a self-contained comment. Ends the run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "done": {"type": "string", "description": "What was done."},
                "check": {
                    "type": "string",
                    "description": "What the owner should check and exactly how.",
                },
                "decide": {
                    "type": "string",
                    "description": "Decisions for the owner, with the options and what each costs. Optional.",
                },
                "not_done": {"type": "string", "description": "What is not done. Optional."},
            },
            "required": ["done", "check"],
        },
    },
    {
        "name": "blocked",
        "description": "Can't go on without an answer: ask one clear question; the ticket goes to the owner. Ends the run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "context": {
                    "type": "string",
                    "description": "What you found so far, self-contained. Optional.",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "file_triage",
        "description": "File new work you noticed (out of this ticket's scope) as a new ticket in Triage.",
        "inputSchema": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
            "required": ["title", "body"],
        },
    },
]


class TicketTools:
    def __init__(self, db_path: Path, run_id: str) -> None:
        self.conn = connect(db_path)
        self.run_id = run_id
        run = store.get_run(self.conn, run_id)
        if run is None:
            raise SystemExit(f"unknown run {run_id}")
        self.run = run
        worker = store.get_worker(self.conn, run["ai_employee_id"])
        if worker is None:
            raise SystemExit("no developer config")
        self.worker = worker
        inst = self.conn.execute(
            "SELECT credentials_json FROM connector_installations WHERE id = ?",
            (worker["linear_installation_id"],),
        ).fetchone()
        key = (
            json.loads(inst["credentials_json"] or "{}").get("fields", {}).get("api_key", "")
            if inst
            else ""
        )
        self.linear = LinearClient(key)
        self._states: dict[str, str] | None = None
        self._last_comment = 0.0

    # -- helpers ------------------------------------------------------------
    def _state_id(self, role: str) -> str | None:
        if self._states is None:
            meta = self.linear.team_meta(self.worker["team_id"])
            self._states = {str(s["name"]).lower(): s["id"] for s in meta["states"]}
        name = str(self.worker["status_map"].get(role, "")).lower()
        return self._states.get(name)

    def _event(self, kind: str, message: str, data: dict[str, Any] | None = None) -> None:
        store.add_event(self.conn, self.run_id, kind, message, data)

    def _finish(self, outcome: str, summary: str) -> None:
        store.update_run(self.conn, self.run_id, outcome=outcome, outcome_summary=summary[:500])

    def _post(self, body: str) -> None:
        self.linear.comment(self.run["ticket_id"], body)
        self.conn.execute(
            "UPDATE code_runs SET comments_posted = comments_posted + 1 WHERE id = ?",
            (self.run_id,),
        )
        self.conn.commit()

    def _hand_to_owner(self, body: str, *, state: str | None = None) -> str:
        """Post the comment and assign the owner; the status changes only when asked."""
        owner_id = self.worker.get("owner_linear_id")
        self._post(body)
        state_id = self._state_id(state) if state else None
        self.linear.update_issue(self.run["ticket_id"], assignee_id=owner_id, state_id=state_id)
        where = f"set to {self.worker['status_map'].get(state)} and " if state_id else ""
        return f"Ticket {where}assigned to the owner."

    @property
    def tools(self) -> list[dict[str, Any]]:
        return ENRICH_TOOLS if self.run.get("kind") == "enrich" else TOOLS

    # -- tools --------------------------------------------------------------
    def call(self, name: str, args: dict[str, Any]) -> str:
        if name == "read":
            node = self.linear.issue_full(self.run["ticket_id"])
            comments = sorted(
                (node.get("comments") or {}).get("nodes", []), key=lambda c: c["createdAt"]
            )
            out = [
                f"{node['identifier']}: {node['title']} — status {(node.get('state') or {}).get('name')}",
                node.get("description") or "",
                "Comments:",
                *[
                    f"- {(c.get('user') or {}).get('name', '?')} ({c['createdAt'][:16]}): {c['body']}"
                    for c in comments
                ],
            ]
            return "\n".join(out)

        if name == "comment":
            run = store.get_run(self.conn, self.run_id) or self.run
            if int(run.get("comments_posted") or 0) >= MAX_COMMENTS:
                return "Comment limit for this run reached; save it for the final hand-off."
            gap = time.monotonic() - self._last_comment
            if self._last_comment and gap < MIN_COMMENT_GAP_S:
                return (
                    f"Too soon after the last comment ({int(gap)} s). Batch it into the next one."
                )
            body = str(args.get("body") or "").strip()
            if not body:
                return "Empty comment not posted."
            self._post(body)
            self._last_comment = time.monotonic()
            self._event("comment", body.splitlines()[0][:200])
            return "Comment posted."

        if name not in {t["name"] for t in self.tools}:
            raise ValueError(f"Unknown tool: {name}")

        if name == "in_review":
            summary = str(args.get("summary") or "").strip()
            body = f"**In review:** {summary}\n\n- **Check:** {str(args.get('check') or '').strip()}"
            run = store.get_run(self.conn, self.run_id) or self.run
            if run.get("branch"):
                body += f"\n- **Branch:** `{run['branch']}` (not pushed)."
            result = self._hand_to_owner(body, state="in_review")
            self._finish("in_review", summary)
            self._event("outcome", "In review: handed to the owner", {"summary": summary})
            return result + " You can stop now."

        if name == "update_description":
            new = str(args.get("description") or "").strip()
            if not new:
                return "Empty description not saved."
            current = self.linear.issue_full(self.run["ticket_id"]).get("description") or ""
            original = current.split(ORIGINAL_MARK, 1)[1] if ORIGINAL_MARK in current else current
            text = new
            if original.strip():
                text += f"\n\n---\n{ORIGINAL_MARK}\n**Original description:**\n\n{original.strip()}"
            self.linear.update_issue(self.run["ticket_id"], description=text)
            self._event("description", "Rewrote the description", {"length": len(new)})
            return "Description updated (the original is kept at the bottom)."

        if name == "ask_owner":
            parts = [f"**Questions before this is ready:**\n\n{str(args.get('questions') or '').strip()}"]
            if args.get("context"):
                parts += ["", str(args["context"]).strip()]
            parts += ["", "_Assign it back to me when you've answered._"]
            result = self._hand_to_owner("\n".join(parts))
            summary = "Asked the owner: " + str(args.get("questions") or "").strip()[:300]
            self._finish("blocked", summary)
            self._event("outcome", "Asked the owner", {"summary": summary})
            return result + " You can stop now."

        if name == "scoped":
            summary = str(args.get("summary") or "").strip()
            ready = self.worker["status_map"].get("ready", "Ready for Dev")
            result = self._hand_to_owner(
                f"**Scope ready for your review:**\n\n{summary}\n\n"
                f"_Set **{ready}** to start it, or comment and assign it back to me._"
            )
            self._finish("scoped", summary)
            self._event("outcome", "Scoped: handed to the owner to approve", {"summary": summary})
            return result + " You can stop now."

        if name in ("hand_off", "blocked"):
            if name == "hand_off":
                parts = [
                    f"**For you to check:** {args.get('done', '').strip()}",
                    "",
                    f"- **Check:** {args.get('check', '').strip()}",
                ]
                if args.get("decide"):
                    parts.append(f"- **Decide:** {str(args['decide']).strip()}")
                if args.get("not_done"):
                    parts.append(f"- **Not done:** {str(args['not_done']).strip()}")
                summary = str(args.get("done", ""))
            else:
                parts = [f"**Blocked, question for you:** {str(args.get('question', '')).strip()}"]
                if args.get("context"):
                    parts += ["", str(args["context"]).strip()]
                summary = "Blocked: " + str(args.get("question", ""))
            run = store.get_run(self.conn, self.run_id) or self.run
            if run.get("branch"):
                parts.append(
                    f"- **Branch:** `{run['branch']}` (not pushed). Worktree: `{run.get('worktree_path')}`"
                )
            result = self._hand_to_owner("\n".join(p for p in parts if p is not None))
            outcome = "needs_owner" if name == "hand_off" else "blocked"
            self._finish(outcome, summary)
            self._event(
                "outcome",
                "Handed off to the owner"
                if outcome == "needs_owner"
                else "Blocked: asked the owner",
                {"summary": summary},
            )
            return result + " You can stop now."

        if name == "file_triage":
            triage = self._state_id("triage")
            created = self.linear.create_issue(
                team_id=self.worker["team_id"],
                title=str(args.get("title", "")).strip(),
                description=f"{str(args.get('body', '')).strip()}\n\nFound while working {self.run['ticket_key']}.",
                state_id=triage,
            )
            self._event("triage", f"Filed {created['identifier']}: {args.get('title')}")
            return f"Filed {created['identifier']} ({created['url']})" + (
                "" if triage else " (no Triage status; it went to the team's default status)"
            )

        raise ValueError(f"Unknown tool: {name}")


def _send(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def serve(tools: TicketTools) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method = msg.get("method")
        mid = msg.get("id")
        if mid is None:
            continue  # notifications (initialized, cancelled) need no reply
        try:
            if method == "initialize":
                result: dict[str, Any] = {
                    "protocolVersion": (msg.get("params") or {}).get(
                        "protocolVersion", PROTOCOL_VERSION
                    ),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "pidgin-ticket", "version": "0.1.0"},
                }
            elif method == "tools/list":
                result = {"tools": tools.tools}
            elif method == "tools/call":
                params = msg.get("params") or {}
                try:
                    text = tools.call(str(params.get("name")), params.get("arguments") or {})
                    result = {"content": [{"type": "text", "text": text}]}
                except (LinearError, ValueError) as exc:
                    result = {
                        "content": [{"type": "text", "text": f"Error: {exc}"}],
                        "isError": True,
                    }
            elif method == "ping":
                result = {}
            else:
                _send(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "error": {"code": -32601, "message": f"Unknown method {method}"},
                    }
                )
                continue
            _send({"jsonrpc": "2.0", "id": mid, "result": result})
        except Exception as exc:  # noqa: BLE001 — never crash the run's tool server
            print(f"[ticket_mcp {utc_now_iso()}] {exc!r}", file=sys.stderr)
            _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(exc)}})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    serve(TicketTools(args.db, args.run))


if __name__ == "__main__":
    main()


ENRICH_TOOLS: list[dict[str, Any]] = [
    _READ_TOOL,
    TOOLS[1],  # comment
    {
        "name": "update_description",
        "description": "Rewrite the ticket's description into the self-contained version (the original is kept at the bottom).",
        "inputSchema": {
            "type": "object",
            "properties": {"description": {"type": "string", "description": "The full new description (markdown)."}},
            "required": ["description"],
        },
    },
    {
        "name": "ask_owner",
        "description": "Ask the owner what only they can answer; the ticket is assigned to them until they reply. Ends the run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "questions": {"type": "string", "description": "Numbered questions, each with the options and what each costs."},
                "context": {"type": "string", "description": "What you found so far, self-contained. Optional."},
            },
            "required": ["questions"],
        },
    },
    {
        "name": "scoped",
        "description": "The ticket is ready for development: summarise the scope; it goes to the owner to approve. Ends the run.",
        "inputSchema": {
            "type": "object",
            "properties": {"summary": {"type": "string", "description": "The scope in a few lines, and the Done when list."}},
            "required": ["summary"],
        },
    },
    TOOLS[-1],  # file_triage
]

ORIGINAL_MARK = "<!-- original description -->"
