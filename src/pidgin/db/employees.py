from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from pidgin.db.principals import get_or_create_operator_principal
from pidgin.recipes.loader import bundle_sha256, canonical_bundle_json
from pidgin.recipes.models import RoleRecipe
from pidgin.util.ids import new_ulid, utc_now_iso


@dataclass
class HiredAgent:
    ai_employee_id: str
    principal_id: str
    recipe_snapshot_id: str
    handle: str


def ensure_operator_principal(conn: sqlite3.Connection) -> str:
    return get_or_create_operator_principal(conn)


def get_agent(conn: sqlite3.Connection, agent_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM ai_employees WHERE id = ?", (agent_id,)).fetchone()


def get_agent_by_handle(conn: sqlite3.Connection, handle: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM ai_employees WHERE handle = ?", (handle,)).fetchone()
    return dict(row) if row else None


def list_agents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, display_name, role_title, handle, current_status, created_at
        FROM ai_employees
        ORDER BY created_at ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def insert_recipe_snapshot(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str,
    ai_employee_id: str,
    source_url: str,
    recipe: RoleRecipe,
) -> str:
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO ai_employee_recipe_snapshots (
          id, ai_employee_id, source_url, recipe_id, recipe_version,
          bundle_sha256, bundle_json, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            ai_employee_id,
            source_url,
            recipe.recipe_id,
            recipe.version,
            bundle_sha256(recipe),
            canonical_bundle_json(recipe),
            now,
        ),
    )
    return snapshot_id


def insert_ai_employee(
    conn: sqlite3.Connection,
    *,
    employee_id: str,
    display_name: str,
    role_title: str,
    handle: str,
    recipe_snapshot_id: str,
    human_owner_principal_id: str,
    default_channels: list[str],
    initial_status: str = "draft",
    actor_principal_id: str,
    manager_principal_id: str | None = None,
    hire_customization_json: str | None = None,
) -> str:
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO ai_employees (
          id, display_name, role_title, handle, recipe_snapshot_id,
          human_owner_principal_id, manager_principal_id, current_status,
          permission_overrides_json, default_channels_json, hire_customization_json,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
        """,
        (
            employee_id,
            display_name,
            role_title,
            handle,
            recipe_snapshot_id,
            human_owner_principal_id,
            manager_principal_id,
            initial_status,
            json.dumps(default_channels),
            hire_customization_json,
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO ai_employees_status_log (
          id, ai_employee_id, from_status, to_status,
          actor_principal_id, reason, occurred_at
        ) VALUES (?, ?, NULL, ?, ?, ?, ?)
        """,
        (
            new_ulid(),
            employee_id,
            initial_status,
            actor_principal_id,
            "Hired from recipe",
            now,
        ),
    )
    return employee_id


def fetch_ai_employee(conn: sqlite3.Connection, employee_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM ai_employees WHERE id = ?", (employee_id,)).fetchone()


def fetch_recipe_snapshot(
    conn: sqlite3.Connection,
    snapshot_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM ai_employee_recipe_snapshots WHERE id = ?",
        (snapshot_id,),
    ).fetchone()


def update_hire_customization(
    conn: sqlite3.Connection,
    *,
    employee_id: str,
    hire_customization_json: str,
) -> None:
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE ai_employees
        SET hire_customization_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (hire_customization_json, now, employee_id),
    )
    conn.commit()
