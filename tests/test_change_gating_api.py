from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import create_workspace


def test_change_gating_defaults_and_update(client: TestClient) -> None:
    slug = create_workspace(client, "Gating Co")
    handle = client.post(f"/{slug}/api/hire").json()["handle"]

    # Defaults: gating on, one 09:00 wake, all five sources.
    got = client.get(f"/{slug}/api/agents/{handle}/change-gating")
    assert got.status_code == 200
    cfg = got.json()
    assert cfg["change_gating_enabled"] is True
    assert cfg["guaranteed_wake_times"] == ["09:00"]
    assert len(cfg["change_sources"]) == 5
    assert {s["key"] for s in cfg["all_sources"]} == set(cfg["change_sources"])

    # Update: disable gating, three wake times, drop one source.
    put = client.put(
        f"/{slug}/api/agents/{handle}/change-gating",
        json={
            "change_gating_enabled": False,
            "guaranteed_wake_times": ["17:00", "9:00", "13:00"],  # unsorted, sloppy HH
            "change_sources": ["inbound_events", "approvals"],
        },
    )
    assert put.status_code == 200
    saved = put.json()
    assert saved["change_gating_enabled"] is False
    assert saved["guaranteed_wake_times"] == ["09:00", "13:00", "17:00"]  # normalized + sorted
    assert saved["change_sources"] == ["inbound_events", "approvals"]

    # Persisted and reflected in the dashboard inspect payload.
    inspect = client.get(f"/{slug}/api/agents/{handle}/inspect").json()
    assert inspect["change_gating"]["change_gating_enabled"] is False
    assert inspect["change_gating"]["guaranteed_wake_times"] == ["09:00", "13:00", "17:00"]


def test_change_gating_resyncs_floor_when_active(client: TestClient) -> None:
    slug = create_workspace(client, "Gating Active Co")
    handle = client.post(f"/{slug}/api/hire").json()["handle"]
    client.post(f"/{slug}/api/agents/{handle}/activate")

    client.put(
        f"/{slug}/api/agents/{handle}/change-gating",
        json={
            "change_gating_enabled": True,
            "guaranteed_wake_times": ["08:00", "20:00"],
            "change_sources": ["inbound_events", "task_state", "approvals",
                               "watched_resources", "delegated_returns"],
        },
    )
    # The ungated daily floor re-armed to the two new times.
    timers = client.get(f"/{slug}/api/agents/{handle}/inspect").json()["timers"]
    daily = [t for t in timers if (t.get("recurrence") or {}).get("kind") == "daily"]
    times = {t["recurrence"]["at_local_time"] for t in daily}
    assert times == {"08:00", "20:00"}


def test_change_gating_unknown_agent_404(client: TestClient) -> None:
    slug = create_workspace(client, "Gating Missing Co")
    assert client.get(f"/{slug}/api/agents/nobody/change-gating").status_code == 404
