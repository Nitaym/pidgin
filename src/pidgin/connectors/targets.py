from __future__ import annotations

import re
import sqlite3

from pidgin.connectors.resources import ResourceUriError, parse_resource_uri
from pidgin.connectors.types import ResourceUri

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def resolve_post_target(conn: sqlite3.Connection, target: str) -> ResourceUri:
    """Turn an agent-supplied `post` target into a ResourceUri.

    Accepted forms:
    - full resource URI: ``slack:channel/C0123``, ``slack:user/U0123``,
      ``slack:thread/C0123:171234.5678``, ``pidgin_chat:conversation/<id>``
    - email address: resolved to a Slack user via the principals table when
      known, otherwise passed through for the connector to resolve
      (users.lookupByEmail)
    - ``#channel-name``: a Slack channel by name, resolved by the connector
    """
    target = target.strip()
    if not target:
        raise ValueError("Empty post target")

    if target.startswith("#"):
        return ResourceUri(prefix="slack", kind="channel", resource_id=target)

    if _EMAIL.match(target):
        from pidgin.db.principals import get_principal_by_email

        principal = get_principal_by_email(conn, target)
        if principal and principal.get("slack_user_id"):
            return ResourceUri(
                prefix="slack", kind="user", resource_id=str(principal["slack_user_id"])
            )
        # Unknown locally — let the Slack connector try users.lookupByEmail.
        return ResourceUri(prefix="slack", kind="user", resource_id=target)

    try:
        return parse_resource_uri(target)
    except ResourceUriError as exc:
        raise ValueError(
            f"Cannot resolve post target {target!r} — use a resource URI "
            "(slack:channel/C0123, slack:user/U0123), an email address, "
            "or a #channel-name"
        ) from exc
