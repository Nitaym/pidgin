from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from pidgin.audit.brief_edits import append_brief_edit_audit
from pidgin.db.employees import (
    fetch_recipe_snapshot,
    get_agent_by_handle,
    update_hire_customization,
)
from pidgin.db.principals import get_or_create_operator_principal
from pidgin.templates.workspace import (
    TemplateError,
    create_workspace_template,
)
from pidgin.types.customization import HireCustomization


class BriefError(Exception):
    pass


def _customization_changes(
    before: HireCustomization | None,
    after: HireCustomization,
) -> dict[str, Any]:
    if before is None:
        return {"fields_set": list(after.model_dump().keys())}
    changes: dict[str, Any] = {}
    before_dump = before.model_dump()
    after_dump = after.model_dump()
    for key, new_value in after_dump.items():
        old_value = before_dump.get(key)
        if old_value != new_value:
            changes[key] = {"from": old_value, "to": new_value}
    return changes


def update_agent_brief(
    conn: sqlite3.Connection,
    workspace_root: Path,
    *,
    handle: str,
    customization: HireCustomization,
    actor_principal_id: str | None = None,
) -> dict[str, Any]:
    agent = get_agent_by_handle(conn, handle)
    if agent is None:
        raise BriefError(f"Agent not found: {handle}")

    actor_id = actor_principal_id or get_or_create_operator_principal(conn)
    before = HireCustomization.from_json(agent.get("hire_customization_json"))
    update_hire_customization(
        conn,
        employee_id=agent["id"],
        hire_customization_json=customization.to_json(),
    )
    changes = _customization_changes(before, customization)
    append_brief_edit_audit(
        workspace_root,
        employee_id=agent["id"],
        actor_principal_id=actor_id,
        summary=f"Updated brief for @{handle}",
        changes=changes,
    )
    return {"handle": handle, "customization": customization.model_dump()}


def create_template_from_agent(
    conn: sqlite3.Connection,
    workspace_root: Path,
    *,
    handle: str,
    name: str,
    slug: str | None,
    actor_principal_id: str | None = None,
) -> dict[str, Any]:
    agent = get_agent_by_handle(conn, handle)
    if agent is None:
        raise BriefError(f"Agent not found: {handle}")

    customization = HireCustomization.from_json(agent.get("hire_customization_json"))
    if customization is None:
        customization = HireCustomization()

    snapshot = fetch_recipe_snapshot(conn, agent["recipe_snapshot_id"])
    lineage: dict[str, Any] = {
        "derived_from_agent_id": agent["id"],
        "derived_from_agent_handle": handle,
    }
    if snapshot is not None:
        lineage["source_recipe_id"] = snapshot["recipe_id"]
        lineage["source_recipe_version"] = snapshot["recipe_version"]

    actor_id = actor_principal_id or get_or_create_operator_principal(conn)
    try:
        return create_workspace_template(
            workspace_root,
            name=name,
            slug=slug,
            customization=customization,
            actor_principal_id=actor_id,
            lineage=lineage,
        )
    except TemplateError as exc:
        raise BriefError(str(exc)) from exc


def duplicate_bundled_template(
    workspace_root: Path,
    *,
    name: str,
    slug: str | None,
    recipe_id: str,
    customization: HireCustomization | None,
    actor_principal_id: str,
) -> dict[str, Any]:
    from pidgin.recipes.catalog import load_bundled_recipe

    recipe = load_bundled_recipe(recipe_id)
    resolved_customization = customization or HireCustomization.from_recipe_defaults(recipe)
    lineage = {
        "source_recipe_id": recipe.recipe_id,
        "source_recipe_version": recipe.version,
    }
    try:
        return create_workspace_template(
            workspace_root,
            name=name,
            slug=slug,
            customization=resolved_customization,
            actor_principal_id=actor_principal_id,
            lineage=lineage,
        )
    except TemplateError as exc:
        raise BriefError(str(exc)) from exc
