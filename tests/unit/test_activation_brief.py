from __future__ import annotations

from pidgin.recipes.catalog import load_bundled_recipe
from pidgin.services.activation import _bootstrap_brief, _effective_work_heartbeat


def test_operating_partner_bootstrap_is_daily_change_gated() -> None:
    op = load_bundled_recipe("operating-partner")
    hb = _effective_work_heartbeat(op, None)
    assert hb.kind == "daily"
    brief = _bootstrap_brief(op)
    # Daily wake, not the 30-minute interval.
    assert '"kind": "daily"' in brief
    assert "every_minutes" not in brief
    # Role-specific cadence guidance (reconcile the plan) is folded in.
    assert "reconcile" in brief.lower()
    # Weekly supervisor report.
    assert "weekly" in brief.lower()


def test_default_recipe_keeps_30_minute_heartbeat() -> None:
    ea = load_bundled_recipe("executive-assistant")
    hb = _effective_work_heartbeat(ea, None)
    assert hb.kind == "interval"
    assert hb.every_minutes == 30
    assert '"every_minutes": 30' in _bootstrap_brief(ea)
