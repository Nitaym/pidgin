"""Acceptance coverage for US-6, US-8, US-9, US-10 (Phase 1B–1B3).

Test names map to user story IDs for traceability in PID-12.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pidgin.services.workspace import get_singleton_workspace
from tests.conftest import create_workspace


@pytest.fixture
def slug(client: TestClient) -> str:
    return create_workspace(client, "Acceptance Co")


# --- US-6: Hire from role template with customizable brief ---


def test_us6_lists_pidgin_and_workspace_templates(client: TestClient, slug: str) -> None:
    response = client.get(f"/{slug}/api/role-templates")
    assert response.status_code == 200
    data = response.json()
    assert any(t["template_id"] == "support-agent" for t in data["bundled"])
    assert data["workspace"] == []


def test_us6_bundled_template_includes_prefill_defaults(client: TestClient, slug: str) -> None:
    response = client.get(f"/{slug}/api/role-templates/bundled/support-agent")
    assert response.status_code == 200
    body = response.json()
    assert body["default_job_requirements"]["mission"]
    assert body["default_ideal_candidate"]["tone"]


def test_us6_hire_persists_customization_separate_from_snapshot(
    client: TestClient,
    slug: str,
    pidgin_home: Path,
) -> None:
    hire = client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "bundled",
            "template_id": "executive-assistant",
            "display_name": "Taylor",
            "handle": "taylor",
            "customization": {
                "job_requirements": {"mission": "US-6 acceptance mission"},
                "ideal_candidate": {"tone": "Crisp"},
                "your_take": "Acceptance your take",
            },
        },
    )
    assert hire.status_code == 200
    employee_id = hire.json()["ai_employee_id"]

    brief = client.get(f"/{slug}/api/agents/taylor/brief").json()
    assert brief["customization"]["job_requirements"]["mission"] == "US-6 acceptance mission"

    agents = client.get(f"/{slug}/api/agents").json()
    agent = next(a for a in agents if a["id"] == employee_id)
    assert agent["current_status"] == "draft"
    assert agent["display_name"] == "Taylor"

    workspace = get_singleton_workspace(home=pidgin_home)
    assert workspace is not None
    row = (
        Path(workspace.path) / "db.sqlite"
    )
    import sqlite3

    conn = sqlite3.connect(row)
    conn.row_factory = sqlite3.Row
    snap = conn.execute(
        """
        SELECT s.bundle_json
        FROM ai_employee_recipe_snapshots s
        JOIN ai_employees e ON e.recipe_snapshot_id = s.id
        WHERE e.id = ?
        """,
        (employee_id,),
    ).fetchone()
    conn.close()
    assert "US-6 acceptance mission" not in snap["bundle_json"]


def test_us6_duplicate_handle_returns_clear_error(client: TestClient, slug: str) -> None:
    body = {
        "template_source": "bundled",
        "template_id": "executive-assistant",
        "display_name": "One",
        "handle": "dup-me",
    }
    assert client.post(f"/{slug}/api/hire", json=body).status_code == 200
    second = client.post(f"/{slug}/api/hire", json={**body, "display_name": "Two"})
    assert second.status_code == 400
    assert "Handle already in use" in second.json()["detail"]


def test_us6_support_agent_singleton(client: TestClient, slug: str) -> None:
    assert client.post(f"/{slug}/api/hire").status_code == 200
    second = client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "bundled",
            "template_id": "support-agent",
            "display_name": "Support Two",
            "handle": "support-2",
        },
    )
    assert second.status_code == 400
    assert "Support agent is already hired" in second.json()["detail"]


# --- US-8: Your role templates ---


def test_us8_duplicate_creates_files_on_disk(
    client: TestClient,
    slug: str,
    pidgin_home: Path,
) -> None:
    response = client.post(
        f"/{slug}/api/role-templates/workspace",
        json={"name": "Playbook", "slug": "playbook", "duplicate_from_recipe_id": "support-agent"},
    )
    assert response.status_code == 200

    workspace = get_singleton_workspace(home=pidgin_home)
    assert workspace is not None
    root = Path(workspace.path) / "role-templates" / "playbook"
    assert (root / "manifest.json").is_file()
    assert (root / "v1.md").is_file()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["current_version"] == 1


def test_us8_save_promotes_version_and_keeps_prior_file(
    client: TestClient,
    slug: str,
    pidgin_home: Path,
) -> None:
    client.post(
        f"/{slug}/api/role-templates/workspace",
        json={"name": "Evolve", "slug": "evolve", "duplicate_from_recipe_id": "support-agent"},
    )
    client.patch(
        f"/{slug}/api/role-templates/workspace/evolve",
        json={
            "customization": {
                "job_requirements": {"mission": "Version 2 mission"},
                "ideal_candidate": {},
                "your_take": "",
            }
        },
    )

    workspace = get_singleton_workspace(home=pidgin_home)
    root = Path(workspace.path) / "role-templates" / "evolve"
    assert (root / "v1.md").is_file()
    assert (root / "v2.md").is_file()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["current_version"] == 2

    listed = client.get(f"/{slug}/api/role-templates").json()
    ws = next(t for t in listed["workspace"] if t["slug"] == "evolve")
    assert ws["current_version"] == 2

    history = client.get(f"/{slug}/api/role-templates/workspace/evolve/versions/1")
    assert history.status_code == 200
    assert "Version 2 mission" not in history.json()["body_markdown"]


def test_us8_delete_removes_template_folder(
    client: TestClient,
    slug: str,
    pidgin_home: Path,
) -> None:
    client.post(
        f"/{slug}/api/role-templates/workspace",
        json={"name": "Temp", "slug": "temp-del", "duplicate_from_recipe_id": "support-agent"},
    )
    assert client.delete(f"/{slug}/api/role-templates/workspace/temp-del").status_code == 200

    workspace = get_singleton_workspace(home=pidgin_home)
    assert not (Path(workspace.path) / "role-templates" / "temp-del").exists()


# --- US-9: Edit agent brief after hire ---


def test_us9_patch_brief_persists_and_writes_audit(
    client: TestClient,
    slug: str,
    pidgin_home: Path,
) -> None:
    hire = client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "bundled",
            "template_id": "executive-assistant",
            "display_name": "Sam",
            "handle": "sam",
        },
    )
    employee_id = hire.json()["ai_employee_id"]

    patch = client.patch(
        f"/{slug}/api/agents/sam/brief",
        json={
            "job_requirements": {"mission": "Updated after hire"},
            "ideal_candidate": {"tone": "Warm"},
            "your_take": "Post-hire note",
        },
    )
    assert patch.status_code == 200

    brief = client.get(f"/{slug}/api/agents/sam/brief").json()
    assert brief["customization"]["job_requirements"]["mission"] == "Updated after hire"

    workspace = get_singleton_workspace(home=pidgin_home)
    audit_path = Path(workspace.path) / "audit" / "brief-edits" / f"{employee_id}.jsonl"
    assert audit_path.is_file()
    entry = json.loads(audit_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert entry["action"] == "brief_edit"
    assert "changes_json" in entry


# --- US-10: Create template from agent ---


def test_us10_create_template_from_agent_with_lineage(
    client: TestClient,
    slug: str,
    pidgin_home: Path,
) -> None:
    client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "bundled",
            "template_id": "executive-assistant",
            "display_name": "Alex",
            "handle": "alex",
            "customization": {
                "job_requirements": {"mission": "From Alex"},
                "ideal_candidate": {},
                "your_take": "Alex take",
            },
        },
    )

    created = client.post(
        f"/{slug}/api/agents/alex/create-template",
        json={"name": "Alex Template", "slug": "alex-template"},
    )
    assert created.status_code == 200
    assert created.json()["current_version"] == 1
    assert created.json()["customization"]["your_take"] == "Alex take"

    workspace = get_singleton_workspace(home=pidgin_home)
    manifest = json.loads(
        (Path(workspace.path) / "role-templates" / "alex-template" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["lineage"]["derived_from_agent_handle"] == "alex"
    assert manifest["lineage"]["source_recipe_id"] == "executive-assistant"
    assert "Alex" not in json.dumps(manifest.get("lineage", {}))

    listed = client.get(f"/{slug}/api/role-templates").json()
    assert any(t["slug"] == "alex-template" for t in listed["workspace"])


def test_us6_hire_creates_draft_agent_conversation_and_memory(
    client: TestClient,
    slug: str,
    pidgin_home: Path,
) -> None:
    hire = client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "bundled",
            "template_id": "executive-assistant",
            "display_name": "Jordan",
            "handle": "jordan",
        },
    )
    assert hire.status_code == 200
    body = hire.json()
    assert body["conversation_id"]

    agents = client.get(f"/{slug}/api/agents").json()
    agent = next(a for a in agents if a["handle"] == "jordan")
    assert agent["current_status"] == "draft"

    workspace = get_singleton_workspace(home=pidgin_home)
    assert (Path(workspace.path) / "memory" / "jordan").is_dir()


def test_us8_create_blank_template(
    client: TestClient,
    slug: str,
    pidgin_home: Path,
) -> None:
    response = client.post(
        f"/{slug}/api/role-templates/workspace",
        json={
            "name": "Blank Playbook",
            "slug": "blank-playbook",
            "customization": {
                "job_requirements": {},
                "ideal_candidate": {},
                "your_take": "",
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["current_version"] == 1

    workspace = get_singleton_workspace(home=pidgin_home)
    root = Path(workspace.path) / "role-templates" / "blank-playbook"
    assert (root / "v1.md").is_file()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "Blank Playbook"
