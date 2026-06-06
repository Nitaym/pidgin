from __future__ import annotations

import json
from pathlib import Path

import pytest

from pidgin.db import apply_migrations, connect, init_workspace_db, insert_inbound_event
from pidgin.gate import gate
from pidgin.knowledge import recall_tail, remember
from pidgin.runtime import run_once
from pidgin.types import (
    ActionType,
    GateOutcome,
    GateRequest,
    InboundEventCreate,
    PermissionProfile,
    PolicyDecision,
    ProposedAction,
    TriggerType,
    TrustLabel,
)
from pidgin.util.slug import slugify
from pidgin.workspace import InvalidPasswordError, create_workspace, open_workspace_path


@pytest.fixture
def pidgin_home(tmp_path: Path) -> Path:
    return tmp_path / ".pidgin"


def test_create_and_open_workspace(pidgin_home: Path) -> None:
    paths = create_workspace("Test Co", "secret123", slugify("Test Co"), home=pidgin_home)
    auth = json.loads(paths.auth_json.read_text(encoding="utf-8"))
    assert paths.db_sqlite.exists() is False  # DB created on first open via admin/API

    opened = open_workspace_path(auth["workspace_id"], "secret123", home=pidgin_home)
    assert opened.root == paths.root

    with pytest.raises(InvalidPasswordError):
        open_workspace_path(auth["workspace_id"], "wrong", home=pidgin_home)


def test_migrations_and_event_processing(pidgin_home: Path) -> None:
    paths = create_workspace("Acme", "pw", slugify("Acme"), home=pidgin_home)
    auth = json.loads(paths.auth_json.read_text(encoding="utf-8"))
    conn = connect(paths.db_sqlite)
    apply_migrations(conn)
    init_workspace_db(conn, auth["workspace_id"], "Acme")

    event_id = insert_inbound_event(
        conn,
        InboundEventCreate(
            trigger_type=TriggerType.DIRECT_ADDRESS,
            trust_label=TrustLabel.INTERNAL_AUTHENTICATED,
            payload={"message": "hello"},
        ),
    )
    assert event_id

    processed = run_once(conn)
    assert processed == 1

    row = conn.execute(
        "SELECT processing_status FROM inbound_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    assert row is not None
    assert row["processing_status"] == "done"


def test_gate_blocked_action() -> None:
    result = gate(
        GateRequest(
            trust_label=TrustLabel.INTERNAL_AUTHENTICATED,
            action=ProposedAction(action_type=ActionType.EXECUTE),
            permission_profile=PermissionProfile(blocked=["execute"]),
        )
    )
    assert result.outcome == GateOutcome.REFUSED
    assert result.policy_decision == PolicyDecision.REFUSED_BY_POLICY


def test_gate_requires_approval() -> None:
    result = gate(
        GateRequest(
            trust_label=TrustLabel.INTERNAL_AUTHENTICATED,
            action=ProposedAction(action_type=ActionType.EXECUTE),
            permission_profile=PermissionProfile(requires_approval=["execute"]),
        )
    )
    assert result.outcome == GateOutcome.STAGED
    assert result.policy_decision == PolicyDecision.AWAITING_HUMAN_APPROVAL


def test_remember_and_recall(pidgin_home: Path) -> None:
    paths = create_workspace("Mem", "pw", slugify("Mem"), home=pidgin_home)
    remember(paths, "support", "Customer prefers email follow-up.")
    tail = recall_tail(paths, "support")
    assert "email follow-up" in tail
