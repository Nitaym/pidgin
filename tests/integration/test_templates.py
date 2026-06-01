from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from pidgin.services.workspace import get_singleton_workspace
from tests.conftest import create_workspace


def test_duplicate_bundled_template_persists_files(client: TestClient, pidgin_home: Path) -> None:
    slug = create_workspace(client, "Template Co")
    response = client.post(
        f"/{slug}/api/role-templates/workspace",
        json={
            "name": "Our Support Playbook",
            "slug": "our-support",
            "duplicate_from_recipe_id": "support-agent",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["slug"] == "our-support"
    assert data["current_version"] == 1
    assert data["customization"]["job_requirements"]["mission"]

    workspace = get_singleton_workspace(home=pidgin_home)
    assert workspace is not None
    manifest_path = Path(workspace.path) / "role-templates" / "our-support" / "manifest.json"
    v1_path = Path(workspace.path) / "role-templates" / "our-support" / "v1.md"
    assert manifest_path.is_file()
    assert v1_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["lineage"]["source_recipe_id"] == "support-agent"


def test_template_version_promotion(client: TestClient, pidgin_home: Path) -> None:
    slug = create_workspace(client, "Version Co")
    client.post(
        f"/{slug}/api/role-templates/workspace",
        json={
            "name": "Playbook",
            "slug": "playbook",
            "duplicate_from_recipe_id": "support-agent",
        },
    )

    patch = client.patch(
        f"/{slug}/api/role-templates/workspace/playbook",
        json={
            "customization": {
                "job_requirements": {"mission": "Updated mission for v2"},
                "ideal_candidate": {},
                "your_take": "",
            }
        },
    )
    assert patch.status_code == 200
    assert patch.json()["current_version"] == 2
    assert patch.json()["customization"]["job_requirements"]["mission"] == "Updated mission for v2"

    workspace = get_singleton_workspace(home=pidgin_home)
    assert workspace is not None
    root = Path(workspace.path) / "role-templates" / "playbook"
    assert (root / "v1.md").is_file()
    assert (root / "v2.md").is_file()
    v1_text = (root / "v1.md").read_text(encoding="utf-8")
    v2_text = (root / "v2.md").read_text(encoding="utf-8")
    assert "Updated mission for v2" in v2_text
    assert "Updated mission for v2" not in v1_text

    audit_path = Path(workspace.path) / "audit" / "template-versions" / "playbook.jsonl"
    assert audit_path.is_file()
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2


def test_patch_agent_brief_writes_audit(client: TestClient, pidgin_home: Path) -> None:
    slug = create_workspace(client, "Brief Co")
    hire = client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "bundled",
            "template_id": "executive-assistant",
            "display_name": "Pat",
            "handle": "pat",
        },
    )
    assert hire.status_code == 200

    patch = client.patch(
        f"/{slug}/api/agents/pat/brief",
        json={
            "job_requirements": {"mission": "New mission after hire"},
            "ideal_candidate": {"tone": "Direct"},
            "your_take": "Owner prefers bullet summaries.",
        },
    )
    assert patch.status_code == 200
    assert patch.json()["customization"]["job_requirements"]["mission"] == "New mission after hire"

    brief = client.get(f"/{slug}/api/agents/pat/brief")
    assert brief.json()["customization"]["your_take"] == "Owner prefers bullet summaries."

    workspace = get_singleton_workspace(home=pidgin_home)
    employee_id = hire.json()["ai_employee_id"]
    audit_path = Path(workspace.path) / "audit" / "brief-edits" / f"{employee_id}.jsonl"
    assert audit_path.is_file()


def test_create_template_from_agent(client: TestClient, pidgin_home: Path) -> None:
    slug = create_workspace(client, "From Agent Co")
    client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "bundled",
            "template_id": "executive-assistant",
            "display_name": "Alex",
            "handle": "alex",
            "customization": {
                "job_requirements": {"mission": "Triage inbox daily"},
                "ideal_candidate": {},
                "your_take": "Copied from Alex.",
            },
        },
    )

    created = client.post(
        f"/{slug}/api/agents/alex/create-template",
        json={"name": "Alex Playbook", "slug": "alex-playbook"},
    )
    assert created.status_code == 200
    assert created.json()["slug"] == "alex-playbook"
    assert created.json()["customization"]["your_take"] == "Copied from Alex."

    workspace = get_singleton_workspace(home=pidgin_home)
    manifest = json.loads(
        (Path(workspace.path) / "role-templates" / "alex-playbook" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["lineage"]["derived_from_agent_handle"] == "alex"
    assert manifest["lineage"]["source_recipe_id"] == "executive-assistant"


def test_hire_from_workspace_template(client: TestClient) -> None:
    slug = create_workspace(client, "Workspace Hire Co")
    client.post(
        f"/{slug}/api/role-templates/workspace",
        json={
            "name": "Custom EA",
            "slug": "custom-ea",
            "duplicate_from_recipe_id": "executive-assistant",
            "customization": {
                "job_requirements": {"mission": "Workspace-specific EA mission"},
                "ideal_candidate": {},
                "your_take": "",
            },
        },
    )

    hire = client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "workspace",
            "slug": "custom-ea",
            "display_name": "Jordan",
            "handle": "jordan",
        },
    )
    assert hire.status_code == 200
    brief = client.get(f"/{slug}/api/agents/jordan/brief")
    assert (
        brief.json()["customization"]["job_requirements"]["mission"]
        == "Workspace-specific EA mission"
    )
