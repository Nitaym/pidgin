from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from pidgin.services.workspace import get_singleton_workspace
from tests.conftest import create_workspace


def test_common_instructions_seed_and_version(client: TestClient, pidgin_home: Path) -> None:
    slug = create_workspace(client, "Common Co")

    got = client.get(f"/{slug}/api/common-instructions")
    assert got.status_code == 200
    data = got.json()
    assert data["current_version"] == 1
    assert data["is_default"] is True
    assert "untrusted" in data["body_markdown"].lower()

    saved = client.put(
        f"/{slug}/api/common-instructions",
        json={"body_markdown": "Always greet customers in French."},
    )
    assert saved.status_code == 200
    assert saved.json()["current_version"] == 2
    assert saved.json()["is_default"] is False
    assert saved.json()["body_markdown"] == "Always greet customers in French."

    workspace = get_singleton_workspace(home=pidgin_home)
    assert workspace is not None
    audit = (
        Path(workspace.path) / "audit" / "common-instructions" / "common-instructions.jsonl"
    )
    assert audit.is_file()
    lines = audit.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2  # seed + save


def test_empty_common_instructions_rejected(client: TestClient) -> None:
    slug = create_workspace(client, "Empty Co")
    # Missing field -> 422 from Pydantic; whitespace-only -> 400 from the service.
    assert client.put(f"/{slug}/api/common-instructions", json={}).status_code == 422
    resp = client.put(f"/{slug}/api/common-instructions", json={"body_markdown": "   "})
    assert resp.status_code == 400


def test_effective_prompt_includes_all_layers(client: TestClient) -> None:
    slug = create_workspace(client, "Layers Co")

    client.put(
        f"/{slug}/api/common-instructions",
        json={"body_markdown": "GLOBAL-RULE-XYZ applies to every agent."},
    )
    hire = client.post(
        f"/{slug}/api/hire",
        json={
            "template_source": "bundled",
            "template_id": "executive-assistant",
            "display_name": "Pat",
            "handle": "pat",
            "customization": {
                "job_requirements": {"mission": "TRIAGE-MISSION-ABC"},
                "ideal_candidate": {},
                "your_take": "",
            },
        },
    )
    assert hire.status_code == 200

    resp = client.get(f"/{slug}/api/agents/pat/effective-prompt")
    assert resp.status_code == 200
    prompt = resp.json()["system_prompt"]

    # Layer 1: common instructions
    assert "Workspace common instructions" in prompt
    assert "GLOBAL-RULE-XYZ" in prompt
    # Layer 2: role prompt
    assert "Executive Assistant" in prompt
    # Layer 3: per-agent brief
    assert "TRIAGE-MISSION-ABC" in prompt
    # Common layer comes first
    assert prompt.index("GLOBAL-RULE-XYZ") < prompt.index("TRIAGE-MISSION-ABC")
