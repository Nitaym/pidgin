from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from pidgin.util.ids import new_ulid, utc_now_iso

# How long one approval authorizes an agent to keep creating for that initiative
# before it must ask again. Bounds the "session" so a grant can't erode the gate
# forever. Owner-revocable (deactivation revokes; see services/activation).
DEFAULT_GRANT_HOURS = 24


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def get_active_grant(
    conn: sqlite3.Connection, *, ai_employee_id: str
) -> dict[str, Any] | None:
    """The agent's current, unexpired execution grant, if any."""
    now = utc_now_iso()
    row = conn.execute(
        """
        SELECT * FROM agent_execution_grants
        WHERE ai_employee_id = ? AND status = 'active'
          AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY granted_at DESC
        LIMIT 1
        """,
        (ai_employee_id, now),
    ).fetchone()
    return dict(row) if row else None


def open_execution_grant(
    conn: sqlite3.Connection,
    *,
    ai_employee_id: str,
    granted_by_principal_id: str,
    origin_approval_id: str | None = None,
    hours: int = DEFAULT_GRANT_HOURS,
) -> str:
    """Open (or reuse) an active grant for the agent. Idempotent per session:
    an existing active grant is returned rather than stacking duplicates."""
    existing = get_active_grant(conn, ai_employee_id=ai_employee_id)
    if existing is not None:
        return str(existing["id"])
    grant_id = new_ulid()
    now = datetime.now(tz=UTC)
    conn.execute(
        """
        INSERT INTO agent_execution_grants (
          id, ai_employee_id, origin_approval_id, granted_by_principal_id,
          status, granted_at, expires_at
        ) VALUES (?, ?, ?, ?, 'active', ?, ?)
        """,
        (
            grant_id,
            ai_employee_id,
            origin_approval_id,
            granted_by_principal_id,
            _iso(now),
            _iso(now + timedelta(hours=hours)),
        ),
    )
    conn.commit()
    return grant_id


def record_grant_resource(
    conn: sqlite3.Connection,
    *,
    ai_employee_id: str,
    resource_uri: str,
) -> None:
    """Record a resource the agent just created under its active grant, so a
    later edit/delete of it is recognised as the agent's own work."""
    grant = get_active_grant(conn, ai_employee_id=ai_employee_id)
    if grant is None or not resource_uri:
        return
    conn.execute(
        """
        INSERT INTO agent_grant_resources (
          id, grant_id, ai_employee_id, resource_uri, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (new_ulid(), grant["id"], ai_employee_id, resource_uri, utc_now_iso()),
    )
    conn.commit()


def is_granted_resource(
    conn: sqlite3.Connection, *, ai_employee_id: str, resource_uri: str
) -> bool:
    """True if the agent created this resource under an active grant this session."""
    if not resource_uri:
        return False
    row = conn.execute(
        """
        SELECT 1
        FROM agent_grant_resources r
        JOIN agent_execution_grants g ON g.id = r.grant_id
        WHERE r.ai_employee_id = ? AND r.resource_uri = ?
          AND g.status = 'active' AND (g.expires_at IS NULL OR g.expires_at > ?)
        LIMIT 1
        """,
        (ai_employee_id, resource_uri, utc_now_iso()),
    ).fetchone()
    return row is not None


def revoke_agent_grants(conn: sqlite3.Connection, *, ai_employee_id: str) -> int:
    """Revoke all active grants for an agent (e.g. on deactivation)."""
    cur = conn.execute(
        "UPDATE agent_execution_grants SET status = 'revoked' "
        "WHERE ai_employee_id = ? AND status = 'active'",
        (ai_employee_id,),
    )
    conn.commit()
    return cur.rowcount
