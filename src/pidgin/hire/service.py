from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pidgin.db.chat import create_room, ensure_room_member, get_room_by_name
from pidgin.db.employees import HiredAgent, insert_ai_employee, insert_recipe_snapshot
from pidgin.db.principals import get_or_create_operator_principal, insert_agent_principal
from pidgin.recipes.loader import load_role_recipe
from pidgin.util.ids import new_ulid
from pidgin.workspace.manager import WorkspacePaths

DEFAULT_SUPPORT_RECIPE = (
    Path(__file__).resolve().parents[3] / "recipes" / "support-agent-v0.1.json"
)
DEFAULT_SUPPORT_ROOM = "#support"


class HireError(Exception):
    pass


_HANDLE_PATTERN = re.compile(r"[^a-z0-9]+")


def derive_handle(display_name: str) -> str:
    handle = _HANDLE_PATTERN.sub("-", display_name.strip().lower()).strip("-")
    if not handle:
        raise HireError("Could not derive handle from display name")
    return handle


@dataclass
class HireRequest:
    display_name: str
    recipe_path: Path
    handle: str | None = None
    owner_principal_id: str | None = None


def hire_from_recipe(
    conn: sqlite3.Connection,
    paths: WorkspacePaths | None,
    request: HireRequest,
) -> HiredAgent:
    if not request.recipe_path.is_file():
        raise HireError(f"Recipe file not found: {request.recipe_path}")

    recipe = load_role_recipe(request.recipe_path)
    handle = request.handle or derive_handle(request.display_name)

    existing = conn.execute(
        "SELECT id FROM ai_employees WHERE handle = ?",
        (handle,),
    ).fetchone()
    if existing is not None:
        raise HireError(f"Handle already in use: {handle}")

    owner_id = request.owner_principal_id or get_or_create_operator_principal(conn)
    employee_id = new_ulid()
    snapshot_id = new_ulid()
    source_url = request.recipe_path.resolve().as_uri()

    insert_recipe_snapshot(
        conn,
        snapshot_id=snapshot_id,
        ai_employee_id=employee_id,
        source_url=source_url,
        recipe=recipe,
    )
    insert_ai_employee(
        conn,
        employee_id=employee_id,
        display_name=request.display_name,
        role_title=recipe.role_title,
        handle=handle,
        recipe_snapshot_id=snapshot_id,
        human_owner_principal_id=owner_id,
        default_channels=recipe.default_channels,
        actor_principal_id=owner_id,
    )
    principal_id = insert_agent_principal(
        conn,
        ai_employee_id=employee_id,
        display_name=request.display_name,
    )

    if paths is not None:
        paths.agent_memory_dir(handle).mkdir(parents=True, exist_ok=True)

    conn.commit()

    return HiredAgent(
        ai_employee_id=employee_id,
        principal_id=principal_id,
        recipe_snapshot_id=snapshot_id,
        handle=handle,
    )


def hire_support_agent(
    conn: sqlite3.Connection,
    *,
    paths_root: Path | str | None = None,
    recipe_path: Path | None = None,
) -> dict[str, str]:
    existing = conn.execute(
        "SELECT id, display_name FROM ai_employees WHERE handle = 'support' LIMIT 1"
    ).fetchone()
    if existing is not None:
        raise HireError("Support agent is already hired")

    recipe_file = recipe_path or DEFAULT_SUPPORT_RECIPE
    recipe = load_role_recipe(recipe_file)
    paths = WorkspacePaths(root=Path(paths_root)) if paths_root else None

    hired = hire_from_recipe(
        conn,
        paths,
        HireRequest(display_name=recipe.display_name, recipe_path=recipe_file, handle="support"),
    )

    room = get_room_by_name(conn, DEFAULT_SUPPORT_ROOM)
    if room is None:
        room_id = create_room(
            conn,
            name=DEFAULT_SUPPORT_ROOM,
            purpose="Customer support conversations",
        )
    else:
        room_id = room["id"]

    operator_id = get_or_create_operator_principal(conn)
    ensure_room_member(conn, room_id, operator_id)
    ensure_room_member(conn, room_id, hired.principal_id)

    return {
        "ai_employee_id": hired.ai_employee_id,
        "display_name": recipe.display_name,
        "room_id": room_id,
        "room_name": DEFAULT_SUPPORT_ROOM,
        "handle": hired.handle,
    }
