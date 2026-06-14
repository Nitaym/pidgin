from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pidgin.util.ids import new_ulid, utc_now_iso

if TYPE_CHECKING:
    import sqlite3

    from pidgin.types.customization import HireCustomization

ContextType = Literal["hire", "agent", "template"]


class HrAssistError(Exception):
    pass


@dataclass
class HrAssistSession:
    session_id: str
    context_type: ContextType
    context_id: str
    created_at: str
    updated_at: str


def _sessions_root(workspace_root: Path) -> Path:
    return workspace_root / "hr-assist" / "sessions"


def _session_dir(workspace_root: Path, session_id: str) -> Path:
    return _sessions_root(workspace_root) / session_id


def create_session(
    workspace_root: Path,
    *,
    context_type: ContextType,
    context_id: str,
) -> HrAssistSession:
    session_id = new_ulid()
    now = utc_now_iso()
    session_dir = _session_dir(workspace_root, session_id)
    session_dir.mkdir(parents=True, exist_ok=False)
    meta = {
        "session_id": session_id,
        "context_type": context_type,
        "context_id": context_id,
        "created_at": now,
        "updated_at": now,
    }
    (session_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (session_dir / "messages.jsonl").touch()
    return HrAssistSession(
        session_id=session_id,
        context_type=context_type,
        context_id=context_id,
        created_at=now,
        updated_at=now,
    )


def get_session(workspace_root: Path, session_id: str) -> HrAssistSession:
    meta_path = _session_dir(workspace_root, session_id) / "meta.json"
    if not meta_path.is_file():
        raise HrAssistError(f"Session not found: {session_id}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return HrAssistSession(
        session_id=meta["session_id"],
        context_type=meta["context_type"],
        context_id=meta["context_id"],
        created_at=meta["created_at"],
        updated_at=meta["updated_at"],
    )


def list_messages(workspace_root: Path, session_id: str) -> list[dict[str, Any]]:
    messages_path = _session_dir(workspace_root, session_id) / "messages.jsonl"
    if not messages_path.is_file():
        raise HrAssistError(f"Session not found: {session_id}")
    messages: list[dict[str, Any]] = []
    for line in messages_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            messages.append(json.loads(line))
    return messages


def _append_message(
    workspace_root: Path,
    session_id: str,
    *,
    role: str,
    body_text: str,
    suggestion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session_dir = _session_dir(workspace_root, session_id)
    if not session_dir.is_dir():
        raise HrAssistError(f"Session not found: {session_id}")

    now = utc_now_iso()
    message: dict[str, Any] = {
        "id": new_ulid(),
        "role": role,
        "body_text": body_text,
        "created_at": now,
    }
    if suggestion is not None:
        message["suggestion"] = suggestion

    messages_path = session_dir / "messages.jsonl"
    with messages_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(message, separators=(",", ":")) + "\n")

    meta_path = session_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["updated_at"] = now
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return message


def stub_assist_reply(operator_message: str) -> tuple[str, dict[str, Any] | None]:
    text = operator_message.strip()
    lower = text.lower()
    if not text:
        return (
            "Tell me about the role you're hiring for — mission, responsibilities, "
            "or the kind of candidate you want.",
            None,
        )
    if "mission" in lower or "purpose" in lower:
        suggestion = {
            "action": "apply",
            "targets": {
                "job_requirements.mission": (
                    "Help customers succeed with our product through clear, timely support."
                ),
            },
        }
        reply = (
            "A strong mission states who you serve and what success looks like. "
            "Here's a draft you can apply to the mission field."
        )
        return reply, suggestion
    if "tone" in lower or "candidate" in lower:
        suggestion = {
            "action": "apply",
            "targets": {
                "ideal_candidate.tone": "Professional, empathetic, and concise.",
            },
        }
        return (
            "For ideal candidate tone, aim for 1–2 sentences on communication style. "
            "I drafted one you can apply.",
            suggestion,
        )
    if "append" in lower or "note" in lower:
        suggestion = {
            "action": "append_your_take",
            "targets": {
                "your_take": "Consider adding examples of great vs. poor responses.",
            },
        }
        return (
            "I can append a note to **Your take** without overwriting other fields.",
            suggestion,
        )
    return (
        "Got it. Can you clarify whether you're tuning job requirements, "
        "ideal candidate profile, or your take?",
        None,
    )


def send_operator_message(
    workspace_root: Path,
    session_id: str,
    *,
    body_text: str,
    conn: sqlite3.Connection | None = None,
    draft_customization: HireCustomization | None = None,
) -> dict[str, Any]:
    history = list_messages(workspace_root, session_id)
    operator_msg = _append_message(
        workspace_root,
        session_id,
        role="operator",
        body_text=body_text,
    )

    reply: tuple[str, dict[str, Any] | None] | None = None
    if conn is not None:
        from pidgin.hr_assist.coach import generate_coach_reply

        reply = generate_coach_reply(
            conn,
            history=history,
            operator_message=body_text,
            draft_customization=draft_customization,
        )
    if reply is None:
        reply_text, suggestion = stub_assist_reply(body_text)
    else:
        reply_text, suggestion = reply

    assist_msg = _append_message(
        workspace_root,
        session_id,
        role="assist",
        body_text=reply_text,
        suggestion=suggestion,
    )
    return {
        "operator_message": operator_msg,
        "assist_message": assist_msg,
        "suggestion": suggestion,
    }
