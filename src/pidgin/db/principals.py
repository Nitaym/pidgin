from __future__ import annotations

import sqlite3

from pidgin.util.ids import new_ulid, utc_now_iso

OPERATOR_PRINCIPAL_ID = "000000000000000000000001"


def get_or_create_operator_principal(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT id FROM principals WHERE id = ?",
        (OPERATOR_PRINCIPAL_ID,),
    ).fetchone()
    if row is not None:
        return row["id"]

    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO principals (
          id, type, display_name, email_address, slack_user_id,
          google_subject_id, ai_employee_id, allowlist_pattern,
          is_active, metadata_json, created_at, updated_at
        ) VALUES (?, 'workspace_member', 'Operator', NULL, NULL, NULL, NULL, NULL, 1, NULL, ?, ?)
        """,
        (OPERATOR_PRINCIPAL_ID, now, now),
    )
    conn.commit()
    return OPERATOR_PRINCIPAL_ID


def insert_agent_principal(
    conn: sqlite3.Connection,
    *,
    ai_employee_id: str,
    display_name: str,
) -> str:
    principal_id = new_ulid()
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO principals (
          id, type, display_name, email_address, slack_user_id,
          google_subject_id, ai_employee_id, allowlist_pattern,
          is_active, metadata_json, created_at, updated_at
        ) VALUES (?, 'pidgin_agent', ?, NULL, NULL, NULL, ?, NULL, 1, NULL, ?, ?)
        """,
        (principal_id, display_name, ai_employee_id, now, now),
    )
    return principal_id


def get_principal_by_email(conn: sqlite3.Connection, email: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM principals WHERE email_address = ? AND is_active = 1",
        (email,),
    ).fetchone()
    return dict(row) if row else None


def upsert_slack_principal(
    conn: sqlite3.Connection,
    *,
    slack_user_id: str,
    display_name: str,
) -> str:
    row = conn.execute(
        "SELECT id FROM principals WHERE slack_user_id = ?",
        (slack_user_id,),
    ).fetchone()
    now = utc_now_iso()
    if row is not None:
        conn.execute(
            "UPDATE principals SET display_name = ?, updated_at = ? WHERE id = ?",
            (display_name, now, row["id"]),
        )
        conn.commit()
        return row["id"]

    principal_id = new_ulid()
    conn.execute(
        """
        INSERT INTO principals (
          id, type, display_name, email_address, slack_user_id,
          google_subject_id, ai_employee_id, allowlist_pattern,
          is_active, metadata_json, created_at, updated_at
        ) VALUES (?, 'workspace_member', ?, NULL, ?, NULL, NULL, NULL, 1, NULL, ?, ?)
        """,
        (principal_id, display_name, slack_user_id, now, now),
    )
    conn.commit()
    return principal_id
