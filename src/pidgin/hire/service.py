from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pidgin.db.chat import create_agent_conversation
from pidgin.db.employees import HiredAgent, insert_ai_employee, insert_recipe_snapshot
from pidgin.db.principals import get_or_create_operator_principal, insert_agent_principal
from pidgin.recipes.catalog import UnknownRecipeError, bundled_recipe_path, load_bundled_recipe
from pidgin.recipes.loader import load_role_recipe
from pidgin.recipes.models import RoleRecipe
from pidgin.types.customization import HireCustomization
from pidgin.util.ids import new_ulid
from pidgin.workspace.manager import WorkspacePaths

DEFAULT_SUPPORT_RECIPE = (
    Path(__file__).resolve().parents[3] / "recipes" / "support-agent-v0.1.json"
)
SUPPORT_RECIPE_ID = "support-agent"
HR_RECIPE_ID = "hr-onboarding"
ENABLEMENT_RECIPE_ID = "enablement"

# Roles that may exist at most once per workspace, mapped to a human label for errors.
SINGLETON_RECIPES: dict[str, str] = {
    SUPPORT_RECIPE_ID: "Support agent",
    HR_RECIPE_ID: "HR agent",
    ENABLEMENT_RECIPE_ID: "Enablement agent",
}


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
    manager_principal_id: str | None = None
    hire_customization_json: str | None = None
    # Operator-set job title; falls back to the recipe's role_title when empty.
    role_title: str | None = None


@dataclass
class TemplateHireRequest:
    template_source: Literal["bundled", "workspace"]
    template_id: str | None = None
    slug: str | None = None
    workspace_version: int | None = None
    customization: HireCustomization | None = None
    display_name: str = ""
    handle: str | None = None
    manager_principal_id: str | None = None


def _ensure_singleton(conn: sqlite3.Connection, recipe_id: str) -> None:
    label = SINGLETON_RECIPES.get(recipe_id)
    if label is None:
        return
    existing = conn.execute(
        """
        SELECT e.id
        FROM ai_employees e
        JOIN ai_employee_recipe_snapshots s ON s.id = e.recipe_snapshot_id
        WHERE s.recipe_id = ?
          AND e.current_status != 'offboarded'
        LIMIT 1
        """,
        (recipe_id,),
    ).fetchone()
    if existing is not None:
        raise HireError(f"{label} is already hired")


def hire_from_recipe(
    conn: sqlite3.Connection,
    paths: WorkspacePaths | None,
    request: HireRequest,
) -> HiredAgent:
    if not request.recipe_path.is_file():
        raise HireError(f"Recipe file not found: {request.recipe_path}")

    recipe = load_role_recipe(request.recipe_path)
    _ensure_singleton(conn, recipe.recipe_id)
    handle = request.handle or derive_handle(request.display_name)

    existing = conn.execute(
        "SELECT id FROM ai_employees WHERE handle = ?",
        (handle,),
    ).fetchone()
    if existing is not None:
        raise HireError(f"Handle already in use: {handle}")

    owner_id = request.owner_principal_id or get_or_create_operator_principal(conn)
    manager_id = request.manager_principal_id or owner_id
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
        role_title=(request.role_title or "").strip() or recipe.role_title,
        handle=handle,
        recipe_snapshot_id=snapshot_id,
        human_owner_principal_id=owner_id,
        manager_principal_id=manager_id,
        default_channels=recipe.default_channels,
        hire_customization_json=request.hire_customization_json,
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


def _resolve_bundled_hire(
    request: TemplateHireRequest,
) -> tuple[Path, RoleRecipe, HireCustomization]:
    if not request.template_id:
        raise HireError("template_id is required for bundled hire")
    try:
        recipe_path = bundled_recipe_path(request.template_id)
        recipe = load_bundled_recipe(request.template_id)
    except UnknownRecipeError as exc:
        raise HireError(str(exc)) from exc
    customization = request.customization or HireCustomization.from_recipe_defaults(recipe)
    return recipe_path, recipe, customization


def _setup_default_conversation(
    conn: sqlite3.Connection,
    *,
    hired: HiredAgent,
    recipe: RoleRecipe,
) -> str:
    _ = recipe
    return create_agent_conversation(conn, hired.ai_employee_id)


def _resolve_workspace_hire(
    request: TemplateHireRequest,
    paths: WorkspacePaths,
) -> tuple[Path, RoleRecipe, HireCustomization]:
    from pidgin.templates.workspace import (
        TemplateError,
        customization_from_template,
        get_workspace_template,
    )

    if not request.slug:
        raise HireError("slug is required for workspace template hire")
    try:
        detail = get_workspace_template(
            paths.root,
            request.slug,
            version=request.workspace_version,
        )
    except TemplateError as exc:
        raise HireError(str(exc)) from exc

    lineage = detail.get("lineage") or {}
    recipe_id = lineage.get("source_recipe_id")
    if not recipe_id:
        raise HireError("Workspace template missing source_recipe_id lineage")
    try:
        recipe_path = bundled_recipe_path(recipe_id)
        recipe = load_bundled_recipe(recipe_id)
    except UnknownRecipeError as exc:
        raise HireError(str(exc)) from exc

    customization = request.customization or customization_from_template(
        paths.root,
        request.slug,
        version=request.workspace_version,
    )
    return recipe_path, recipe, customization


def hire_with_template(
    conn: sqlite3.Connection,
    *,
    paths_root: Path | str | None,
    request: TemplateHireRequest,
) -> dict[str, str]:
    paths = WorkspacePaths(root=Path(paths_root)) if paths_root else None

    if request.template_source == "workspace":
        if paths is None:
            raise HireError("Workspace paths required for workspace template hire")
        recipe_path, recipe, customization = _resolve_workspace_hire(request, paths)
    else:
        recipe_path, recipe, customization = _resolve_bundled_hire(request)

    display_name = request.display_name.strip() or recipe.display_name

    hired = hire_from_recipe(
        conn,
        paths,
        HireRequest(
            display_name=display_name,
            recipe_path=recipe_path,
            handle=request.handle,
            manager_principal_id=request.manager_principal_id,
            hire_customization_json=customization.to_json(),
            role_title=customization.role_title or None,
        ),
    )
    conversation_id = _setup_default_conversation(conn, hired=hired, recipe=recipe)

    return {
        "ai_employee_id": hired.ai_employee_id,
        "display_name": display_name,
        "conversation_id": conversation_id,
        "handle": hired.handle,
        "recipe_id": recipe.recipe_id,
    }


def get_hr_agent(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Return the active HR agent row, or None if not hired.

    Looked up by role (recipe_id), not handle, so it stays correct regardless of
    the handle the seed manifest assigns.
    """
    row = conn.execute(
        """
        SELECT e.*
        FROM ai_employees e
        JOIN ai_employee_recipe_snapshots s ON s.id = e.recipe_snapshot_id
        WHERE s.recipe_id = ?
          AND e.current_status != 'offboarded'
        LIMIT 1
        """,
        (HR_RECIPE_ID,),
    ).fetchone()
    return dict(row) if row else None


def hire_support_agent(
    conn: sqlite3.Connection,
    *,
    paths_root: Path | str | None = None,
    recipe_path: Path | None = None,
) -> dict[str, str]:
    recipe_file = recipe_path or DEFAULT_SUPPORT_RECIPE
    recipe = load_role_recipe(recipe_file)
    customization = HireCustomization.from_recipe_defaults(recipe)
    return hire_with_template(
        conn,
        paths_root=paths_root,
        request=TemplateHireRequest(
            template_source="bundled",
            template_id=recipe.recipe_id,
            customization=customization,
            display_name=recipe.display_name,
            handle="support",
        ),
    )
