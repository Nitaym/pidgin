from __future__ import annotations

from typing import Any, ClassVar


class FakeWebClient:
    """Stand-in for slack_sdk.WebClient — records calls class-wide so tests
    can assert on Slack traffic regardless of where the client was built."""

    calls: ClassVar[list[tuple[str, dict[str, Any]]]] = []
    team_id = "T123"
    users_by_email: ClassVar[dict[str, str]] = {"dana@example.com": "U777"}
    channels_by_name: ClassVar[dict[str, str]] = {"general": "CGEN"}

    def __init__(self, token: str | None = None, **kwargs: Any) -> None:
        self.token = token

    @classmethod
    def reset(cls) -> None:
        cls.calls = []

    @classmethod
    def calls_named(cls, method: str) -> list[dict[str, Any]]:
        return [kwargs for name, kwargs in cls.calls if name == method]

    def _record(self, method: str, kwargs: dict[str, Any]) -> None:
        type(self).calls.append((method, kwargs))

    def auth_test(self) -> dict[str, Any]:
        self._record("auth_test", {})
        return {"ok": True, "team": "Fake Team", "team_id": self.team_id}

    def chat_postMessage(self, **kwargs: Any) -> dict[str, Any]:  # noqa: N802
        self._record("chat_postMessage", kwargs)
        return {"ok": True, "ts": "1718000000.000100", "channel": kwargs.get("channel")}

    def conversations_open(self, **kwargs: Any) -> dict[str, Any]:
        self._record("conversations_open", kwargs)
        return {"ok": True, "channel": {"id": f"D-{kwargs.get('users')}"}}

    def conversations_list(self, **kwargs: Any) -> dict[str, Any]:
        self._record("conversations_list", kwargs)
        channels = [
            {"id": cid, "name": name} for name, cid in type(self).channels_by_name.items()
        ]
        return {"ok": True, "channels": channels, "response_metadata": {"next_cursor": ""}}

    def users_lookupByEmail(self, **kwargs: Any) -> dict[str, Any]:  # noqa: N802
        self._record("users_lookupByEmail", kwargs)
        email = str(kwargs.get("email") or "")
        user_id = type(self).users_by_email.get(email)
        if user_id is None:
            return {"ok": False, "user": None}
        return {"ok": True, "user": {"id": user_id}}

    def conversations_history(self, **kwargs: Any) -> dict[str, Any]:
        self._record("conversations_history", kwargs)
        return {"ok": True, "messages": []}

    def conversations_replies(self, **kwargs: Any) -> dict[str, Any]:
        self._record("conversations_replies", kwargs)
        return {"ok": True, "messages": []}
