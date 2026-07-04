from __future__ import annotations

import sqlite3

import pytest

from pidgin.db.connection import apply_migrations
from pidgin.db.grants import (
    get_active_grant,
    is_granted_resource,
    open_execution_grant,
    record_grant_resource,
    revoke_agent_grants,
)
from pidgin.gate.policy import gate
from pidgin.types import (
    ActionType,
    GateOutcome,
    GateRequest,
    PermissionProfile,
    ProposedAction,
    TrustLabel,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    apply_migrations(c)
    return c


def _enablement_profile() -> PermissionProfile:
    # Mirrors the enablement recipe: execute is owner-approved.
    return PermissionProfile(
        can_read=["read"],
        can_write=["say"],
        requires_approval=["execute"],
        blocked=[],
    )


def _gate(uri: str) -> GateOutcome:
    return gate(
        GateRequest(
            trust_label=TrustLabel.INTERNAL_AUTHENTICATED,
            action=ProposedAction(action_type=ActionType.EXECUTE, params={"resource_uri": uri}),
            permission_profile=_enablement_profile(),
            is_direct_commander=True,
        )
    ).outcome


def test_execute_stages_without_a_grant(conn: sqlite3.Connection) -> None:
    # Baseline: the pure gate stages every execute for this profile.
    assert _gate("gdrive:folder/root") == GateOutcome.STAGED
    assert get_active_grant(conn, ai_employee_id="a1") is None


def test_grant_opens_and_is_idempotent(conn: sqlite3.Connection) -> None:
    g1 = open_execution_grant(conn, ai_employee_id="a1", granted_by_principal_id="op")
    g2 = open_execution_grant(conn, ai_employee_id="a1", granted_by_principal_id="op")
    assert g1 == g2  # reused, not stacked
    assert get_active_grant(conn, ai_employee_id="a1") is not None


def test_created_resource_is_recognised_only_this_session(conn: sqlite3.Connection) -> None:
    open_execution_grant(conn, ai_employee_id="a1", granted_by_principal_id="op")
    record_grant_resource(conn, ai_employee_id="a1", resource_uri="gdrive:file/doc1")

    # A resource the agent created this session is its own work.
    assert is_granted_resource(conn, ai_employee_id="a1", resource_uri="gdrive:file/doc1")
    # A pre-existing resource it did not create is not.
    assert not is_granted_resource(conn, ai_employee_id="a1", resource_uri="gdrive:file/other")
    # Another agent's grant doesn't cover it.
    assert not is_granted_resource(conn, ai_employee_id="a2", resource_uri="gdrive:file/doc1")


def _ctx(conn: sqlite3.Connection, agent_id: str = "a1"):
    from types import SimpleNamespace

    return SimpleNamespace(
        workspace=SimpleNamespace(db_bridge=conn),
        agent=SimpleNamespace(agent_id=agent_id, permission_profile=_enablement_profile()),
        event=SimpleNamespace(trust_label=TrustLabel.INTERNAL_AUTHENTICATED),
    )


def test_gate_action_auto_approves_under_grant(conn: sqlite3.Connection) -> None:
    from pidgin.runtime.actions import gate_action

    ctx = _ctx(conn)
    create = ProposedAction(
        action_type=ActionType.EXECUTE, params={"resource_uri": "gdrive:folder/root"}
    )
    # No grant yet → the create stages for approval.
    assert gate_action(ctx, create).outcome == GateOutcome.STAGED

    open_execution_grant(conn, ai_employee_id="a1", granted_by_principal_id="op")
    # With the grant, subsequent creates auto-approve — no more prompts.
    assert gate_action(ctx, create).outcome == GateOutcome.EXECUTED

    # Editing a pre-existing file it did not create still stages.
    edit_other = ProposedAction(
        action_type=ActionType.EXECUTE, params={"resource_uri": "gdrive:file/preexisting"}
    )
    assert gate_action(ctx, edit_other).outcome == GateOutcome.STAGED

    # Editing something it created this session auto-approves.
    record_grant_resource(conn, ai_employee_id="a1", resource_uri="gdrive:file/mine")
    edit_mine = ProposedAction(
        action_type=ActionType.EXECUTE, params={"resource_uri": "gdrive:file/mine"}
    )
    assert gate_action(ctx, edit_mine).outcome == GateOutcome.EXECUTED


def test_revoke_ends_the_session(conn: sqlite3.Connection) -> None:
    open_execution_grant(conn, ai_employee_id="a1", granted_by_principal_id="op")
    record_grant_resource(conn, ai_employee_id="a1", resource_uri="gdrive:file/doc1")

    revoked = revoke_agent_grants(conn, ai_employee_id="a1")
    assert revoked == 1
    assert get_active_grant(conn, ai_employee_id="a1") is None
    # With no active grant, the created resource is no longer "this session".
    assert not is_granted_resource(conn, ai_employee_id="a1", resource_uri="gdrive:file/doc1")
