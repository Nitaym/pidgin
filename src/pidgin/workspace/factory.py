from __future__ import annotations

import sqlite3

from pidgin.db.connection import apply_migrations, connect
from pidgin.llm.config import load_llm_config
from pidgin.llm.providers.anthropic import AnthropicLLMProvider
from pidgin.llm.providers.litellm import LiteLLMProvider
from pidgin.llm.registry import register_provider
from pidgin.runtime.context import WorkspaceContext
from pidgin.storage.sqlite.conversation_store import SqliteConversationStore
from pidgin.storage.sqlite.turn_store import SqliteTurnStore
from pidgin.workspace.manager import WorkspacePaths


def build_workspace_context(
    *,
    workspace_id: str,
    paths: WorkspacePaths,
) -> WorkspaceContext:
    conn = connect(paths.db_sqlite)
    apply_migrations(conn)
    return build_workspace_context_from_conn(
        workspace_id=workspace_id,
        paths=paths,
        conn=conn,
    )


def build_workspace_context_from_conn(
    *,
    workspace_id: str,
    paths: WorkspacePaths,
    conn: sqlite3.Connection,
) -> WorkspaceContext:
    settings_row = conn.execute("SELECT settings_json FROM workspace LIMIT 1").fetchone()
    settings_json = settings_row["settings_json"] if settings_row else None
    _ensure_llm_providers()
    return WorkspaceContext(
        workspace_id=workspace_id,
        paths=paths,
        turn_store=SqliteTurnStore(conn),
        conversation_store=SqliteConversationStore(conn),
        llm_config=load_llm_config(settings_json),
        db_bridge=conn,
    )


_providers_initialized = False


def _ensure_llm_providers() -> None:
    global _providers_initialized
    if _providers_initialized:
        return
    from pidgin.llm.providers.stub import StubLLMProvider

    register_provider("stub", StubLLMProvider())
    register_provider("litellm", LiteLLMProvider())
    try:
        register_provider("anthropic", AnthropicLLMProvider())
    except ValueError:
        pass
    _providers_initialized = True
