from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from pidgin.llm.config import load_llm_config
from pidgin.runtime.context import WorkspaceContext
from pidgin.runtime.turn_dispatcher import dispatch_pending_turns
from pidgin.storage.sqlite.conversation_store import SqliteConversationStore
from pidgin.storage.sqlite.turn_store import SqliteTurnStore
from pidgin.workspace.factory import _ensure_llm_providers
from pidgin.workspace.manager import WorkspacePaths


def workspace_context_from_conn(conn: sqlite3.Connection) -> WorkspaceContext:
    _ensure_llm_providers()
    workspace = conn.execute("SELECT id, settings_json FROM workspace LIMIT 1").fetchone()
    workspace_id = workspace["id"] if workspace else "default"
    settings_json = workspace["settings_json"] if workspace else None
    db_list = conn.execute("PRAGMA database_list").fetchone()
    db_path = Path(db_list[2] if db_list else "db.sqlite")
    paths = WorkspacePaths(root=db_path.parent)
    return WorkspaceContext(
        workspace_id=workspace_id,
        paths=paths,
        turn_store=SqliteTurnStore(conn),
        conversation_store=SqliteConversationStore(conn),
        llm_config=load_llm_config(settings_json),
        db_bridge=conn,
    )


def run_once(
    conn: sqlite3.Connection | None = None,
    *,
    ctx: WorkspaceContext | None = None,
    batch_size: int = 10,
) -> int:
    if ctx is None:
        if conn is None:
            return 0
        ctx = workspace_context_from_conn(conn)
    return dispatch_pending_turns(ctx, batch_size=batch_size)


def run_loop(conn: sqlite3.Connection, poll_interval_seconds: float = 1.0) -> None:
    while True:
        processed = run_once(conn)
        if processed == 0:
            time.sleep(poll_interval_seconds)
