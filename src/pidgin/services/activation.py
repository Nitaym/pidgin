"""Activation bootstrap — make an agent self-running the moment it goes active.

When an agent transitions to ``active`` it gets a single self-anchored bootstrap
timer that fires immediately. The bootstrap turn is where the agent reads company
context, turns its mission into a task backlog, and schedules its own recurring
check-ins and a periodic report to its supervisor — no human poke required.

See AUTONOMY_SPEC.md §4.
"""

from __future__ import annotations

import logging
import sqlite3

from pidgin.db.employees import get_agent_by_handle, transition_employee_status
from pidgin.db.principals import get_or_create_operator_principal
from pidgin.db.timers import cancel_agent_timers, create_timer
from pidgin.recipes.models import RoleRecipe
from pidgin.types import TrustLabel
from pidgin.util.ids import utc_now_iso

log = logging.getLogger(__name__)


class ActivationError(Exception):
    pass


def _load_recipe(conn: sqlite3.Connection, recipe_snapshot_id: str) -> RoleRecipe | None:
    row = conn.execute(
        "SELECT bundle_json FROM ai_employee_recipe_snapshots WHERE id = ?",
        (recipe_snapshot_id,),
    ).fetchone()
    if row is None:
        return None
    return RoleRecipe.model_validate_json(row["bundle_json"])


def _bootstrap_brief(recipe: RoleRecipe | None) -> str:
    """The verbatim instruction delivered when the bootstrap timer fires."""
    lines = [
        "[Activation] You are now active. This is your first turn — nobody is "
        "waiting on a reply. Set yourself up to run independently, then go quiet:",
        "",
        "1. Read the company onboarding context first and remember the parts "
        "relevant to your role.",
        "2. Turn your mission and responsibilities into a backlog: open_task one "
        "durable task per standing responsibility you own.",
        "3. Schedule your own recurring check-ins with schedule_self (use a "
        "recurrence) so you act on that work without being prompted.",
        "4. Schedule a recurring status report to your operator via schedule_self "
        "+ escalate — this is a standing rule for every agent.",
        "5. If anything blocks you from starting (a missing tool or unclear "
        "scope), escalate it now, then stop.",
    ]
    autonomy = recipe.autonomy if recipe else None
    if autonomy and autonomy.cadence_guidance:
        lines += ["", "Suggested cadence for your role (you decide the exact timing):"]
        lines += [f"  - {g}" for g in autonomy.cadence_guidance]
    if autonomy and autonomy.supervisor_report:
        rep = autonomy.supervisor_report
        when = rep.weekday if rep.cadence == "weekly" else "each day"
        lines.append(
            f"  - Report to your operator {rep.cadence} ({when} ~{rep.at_local_time} UTC)."
        )
    else:
        lines.append("  - Default: a brief daily review and a weekly report to your operator.")
    return "\n".join(lines)


def deactivate_agent(
    conn: sqlite3.Connection,
    *,
    handle: str,
    actor_principal_id: str | None = None,
) -> dict[str, str]:
    """Stop a running agent: transition active → draft and cancel its timers.

    The scheduler doesn't gate on status, so flipping the status alone would
    leave the agent's self-scheduled wakeups firing. We cancel all pending
    timers, and clear ``bootstrapped_at`` so a later activate cleanly
    re-bootstraps (rebuilds the backlog and re-arms its check-ins) rather than
    resuming with no timers.
    """
    agent = get_agent_by_handle(conn, handle)
    if agent is None:
        raise ActivationError(f"Agent not found: {handle}")
    if agent["current_status"] != "active":
        raise ActivationError(f"Agent is not active: {handle}")

    actor_id = actor_principal_id or get_or_create_operator_principal(conn)
    transition_employee_status(
        conn,
        employee_id=agent["id"],
        to_status="draft",
        actor_principal_id=actor_id,
        reason="Deactivated by workspace operator",
    )
    cancelled = cancel_agent_timers(conn, ai_employee_id=agent["id"])
    conn.execute(
        "UPDATE ai_employees SET bootstrapped_at = NULL, updated_at = ? WHERE id = ?",
        (utc_now_iso(), agent["id"]),
    )
    conn.commit()
    log.info(
        "[activation] %s deactivated — %d pending timer(s) cancelled", handle, cancelled
    )
    return {
        "handle": handle,
        "current_status": "draft",
        "timers_cancelled": str(cancelled),
    }


def activate_agent(
    conn: sqlite3.Connection,
    *,
    handle: str,
    actor_principal_id: str | None = None,
) -> dict[str, str]:
    """Transition an agent to active and (once) enqueue its bootstrap wake-up."""
    agent = get_agent_by_handle(conn, handle)
    if agent is None:
        raise ActivationError(f"Agent not found: {handle}")
    if agent["current_status"] == "offboarded":
        raise ActivationError(f"Agent is archived: {handle}")

    actor_id = actor_principal_id or get_or_create_operator_principal(conn)
    transition_employee_status(
        conn,
        employee_id=agent["id"],
        to_status="active",
        actor_principal_id=actor_id,
        reason="Activated by workspace operator",
    )

    already = agent["bootstrapped_at"] if "bootstrapped_at" in agent.keys() else None
    if already:
        log.info("[activation] %s already bootstrapped at %s — resume, no re-bootstrap", handle, already)
        return {"handle": handle, "current_status": "active", "bootstrapped": "false"}

    recipe = _load_recipe(conn, agent["recipe_snapshot_id"])
    timer_id = create_timer(
        conn,
        ai_employee_id=agent["id"],
        scheduled_at=utc_now_iso(),  # fire on the next worker tick
        reason=_bootstrap_brief(recipe),
        inherited_trust_label=TrustLabel.INTERNAL_AUTHENTICATED.value,
        originating_turn_id=None,  # self-anchored: no conversation
        kind="bootstrap",
    )
    conn.execute(
        "UPDATE ai_employees SET bootstrapped_at = ?, updated_at = ? WHERE id = ?",
        (utc_now_iso(), utc_now_iso(), agent["id"]),
    )
    conn.commit()
    log.info("[activation] %s activated + bootstrap timer %s enqueued", handle, timer_id)
    return {"handle": handle, "current_status": "active", "bootstrapped": "true"}
