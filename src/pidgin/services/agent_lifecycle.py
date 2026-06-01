from __future__ import annotations

import sqlite3

from pidgin.db.employees import get_agent_by_handle, transition_employee_status
from pidgin.db.principals import get_or_create_operator_principal

ARCHIVED_STATUS = "offboarded"


class ArchiveError(Exception):
    pass


def archive_agent(
    conn: sqlite3.Connection,
    *,
    handle: str,
    actor_principal_id: str | None = None,
) -> dict[str, str]:
    agent = get_agent_by_handle(conn, handle)
    if agent is None:
        raise ArchiveError(f"Agent not found: {handle}")

    if agent["current_status"] == ARCHIVED_STATUS:
        raise ArchiveError(f"Agent is already archived: {handle}")

    actor_id = actor_principal_id or get_or_create_operator_principal(conn)
    transition_employee_status(
        conn,
        employee_id=agent["id"],
        to_status=ARCHIVED_STATUS,
        actor_principal_id=actor_id,
        reason="Archived by workspace operator",
    )
    return {"handle": handle, "current_status": ARCHIVED_STATUS}
