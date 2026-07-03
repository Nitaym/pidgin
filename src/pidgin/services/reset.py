"""Full workspace memory reset — wipe agents, conversations, tasks, and agent
journals so onboarding can run again from a clean slate.

Workspace identity (slug, login, display name) and connector installations
(Google Drive, Slack, etc.) are intentionally left untouched, so the reset
doesn't force re-authenticating every integration.
"""

from __future__ import annotations

import shutil
import sqlite3

from pidgin.workspace.manager import WorkspacePaths

# Cleared on reset. connector_installations, connector_event_dedup, workspace,
# and schema_migrations are deliberately excluded.
_TABLES_TO_CLEAR = (
    "agent_action_log",
    "quarantined_items",
    "external_intake_items",
    "pending_approvals_status_log",
    "pending_approvals",
    "agent_watchers",
    "agent_timers",
    "messages",
    "model_invocations",
    "turns_status_log",
    "turns",
    "inbound_events",
    "conversations",
    "document_access_grants",
    "ingested_documents",
    "tasks_status_log",
    "tasks",
    "ai_employee_recipe_snapshots",
    "ai_employees_status_log",
    "ai_employees",
)


def reset_workspace_memory(conn: sqlite3.Connection, paths: WorkspacePaths) -> list[str]:
    """Wipe agents/conversations/tasks/journals, then re-seed the starting team.

    Returns the handles re-seeded (e.g. ["hr", "enablement"]).
    """
    from pidgin.hire import seed_workspace_agents

    for table in _TABLES_TO_CLEAR:
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM principals WHERE type != 'workspace_member'")
    conn.commit()

    for directory in (paths.memory_dir, paths.docs_dir, paths.blobs_dir, paths.debug_dir):
        shutil.rmtree(directory, ignore_errors=True)
    paths.memory_dir.mkdir(parents=True, exist_ok=True)
    paths.docs_dir.mkdir(parents=True, exist_ok=True)
    paths.blobs_dir.mkdir(parents=True, exist_ok=True)

    return seed_workspace_agents(conn, paths_root=paths.root)
