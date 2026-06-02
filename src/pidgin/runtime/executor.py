from __future__ import annotations

import json
import sqlite3

from pidgin.connectors.pidgin_chat.connector import PidginChatConnector
from pidgin.connectors.pidgin_chat.ingress import conversation_resource_uri
from pidgin.connectors.registry import load_connector
from pidgin.connectors.types import PrincipalContext, WritePayload
from pidgin.db.employees import get_agent
from pidgin.llm import stub_chat_reply
from pidgin.recipes import RoleRecipe
from pidgin.runtime.turn import TurnContext, complete_turn, start_turn
from pidgin.types import TrustLabel
from pidgin.types.customization import HireCustomization
from pidgin.util.ids import new_ulid, utc_now_iso


def _is_pidgin_chat_event(payload: dict) -> bool:
    return (
        payload.get("connector_type", "pidgin_chat") == "pidgin_chat"
        and "conversation_id" in payload
    )


def _is_slack_event(payload: dict) -> bool:
    return payload.get("connector_type") == "slack"


def execute_turn(conn: sqlite3.Connection, event_row: sqlite3.Row) -> TurnContext:
    payload = json.loads(event_row["payload_json"] or "{}")
    if _is_pidgin_chat_event(payload):
        return _execute_pidgin_chat_turn(conn, event_row, payload)
    if _is_slack_event(payload):
        return _execute_slack_turn(conn, event_row, payload)
    return _execute_legacy_stub_turn(conn, event_row, payload)


def _execute_legacy_stub_turn(
    conn: sqlite3.Connection,
    event_row: sqlite3.Row,
    payload: dict,
) -> TurnContext:
    from pidgin.runtime.turn import execute_turn_stub

    _ = payload
    return execute_turn_stub(conn, event_row)


def _agent_context(
    conn: sqlite3.Connection,
    agent_id: str,
) -> tuple[dict, RoleRecipe, HireCustomization, str]:
    agent = get_agent(conn, agent_id)
    if agent is None:
        raise ValueError(f"Unknown agent: {agent_id}")

    snapshot = conn.execute(
        "SELECT bundle_json FROM ai_employee_recipe_snapshots WHERE id = ?",
        (agent["recipe_snapshot_id"],),
    ).fetchone()
    recipe = RoleRecipe.model_validate_json(snapshot["bundle_json"] if snapshot else "{}")
    customization = HireCustomization.from_json(agent["hire_customization_json"])

    agent_principal = conn.execute(
        "SELECT id FROM principals WHERE ai_employee_id = ? LIMIT 1",
        (agent_id,),
    ).fetchone()
    agent_principal_id = agent_principal["id"] if agent_principal else agent_id
    return agent, recipe, customization, agent_principal_id


def _log_say_action(
    conn: sqlite3.Connection,
    *,
    turn_id: str,
    agent: dict,
    event_row: sqlite3.Row,
    payload: dict,
    reply_text: str,
    action_type: str,
    technical_actor: str,
    extra_params: dict | None = None,
) -> None:
    params = {"text": reply_text, **(extra_params or {})}
    conn.execute(
        """
        INSERT INTO agent_action_log (
          id, turn_id, technical_actor, virtual_actor_ai_employee_id,
          virtual_actor_display_name, virtual_actor_role,
          requester_principal_id, requester_display_name,
          trust_label, policy_decision, action_type, action_params_json,
          outcome, occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_ulid(),
            turn_id,
            technical_actor,
            agent["id"],
            agent["display_name"],
            agent["role_title"],
            payload.get("sender_principal_id", "operator"),
            payload.get("sender_display_name", "You"),
            event_row["trust_label"],
            "accepted_as_instruction",
            action_type,
            json.dumps(params),
            "executed",
            utc_now_iso(),
        ),
    )


def _execute_pidgin_chat_turn(
    conn: sqlite3.Connection,
    event_row: sqlite3.Row,
    payload: dict,
) -> TurnContext:
    agent_id = event_row["target_ai_employee_id"]
    if not agent_id:
        raise ValueError("Chat event missing target_ai_employee_id")

    agent, recipe, customization, agent_principal_id = _agent_context(conn, agent_id)

    ctx = start_turn(conn, event_row)
    conn.execute(
        "UPDATE turns SET conversation_id = ? WHERE id = ?",
        (payload["conversation_id"], ctx.turn_id),
    )
    conn.commit()

    reply = stub_chat_reply(
        recipe=recipe,
        agent_display_name=agent["display_name"],
        user_message=payload["message_text"],
        customization=customization,
    )

    connector = PidginChatConnector()
    connector.write(
        conn,
        conversation_resource_uri(payload["conversation_id"]),
        WritePayload(
            text=reply.text,
            extra={"originating_turn_id": ctx.turn_id},
        ),
        principal=PrincipalContext(
            principal_id=agent_principal_id,
            display_name=agent["display_name"],
            trust_label=TrustLabel(event_row["trust_label"]),
        ),
        mode="execute",
    )

    _log_say_action(
        conn,
        turn_id=ctx.turn_id,
        agent=agent,
        event_row=event_row,
        payload=payload,
        reply_text=reply.text,
        action_type=reply.action_type,
        technical_actor="pidgin_chat",
        extra_params={"conversation_id": payload["conversation_id"]},
    )
    complete_turn(conn, ctx.turn_id, ctx.inbound_event_id)
    return ctx


def _execute_slack_turn(
    conn: sqlite3.Connection,
    event_row: sqlite3.Row,
    payload: dict,
) -> TurnContext:
    agent_id = event_row["target_ai_employee_id"]
    if not agent_id:
        raise ValueError("Slack event missing target_ai_employee_id")

    installation_id = payload.get("connector_installation_id")
    if not installation_id:
        raise ValueError("Slack event missing connector_installation_id")

    agent, recipe, customization, agent_principal_id = _agent_context(conn, agent_id)
    ctx = start_turn(conn, event_row)
    conn.commit()

    reply = stub_chat_reply(
        recipe=recipe,
        agent_display_name=agent["display_name"],
        user_message=payload["message_text"],
        customization=customization,
    )

    channel = payload.get("external_channel_id", "")
    thread_ts = payload.get("external_thread_id")
    resource_id = f"{channel}:{thread_ts}" if thread_ts else channel

    from pidgin.connectors.types import ResourceUri

    connector = load_connector(conn, str(installation_id))
    attribution = f"{agent['display_name']} · {agent['role_title']} via Pidgin\n\n"
    slack_resource = ResourceUri(
        prefix="slack",
        kind="thread" if thread_ts else "channel",
        resource_id=resource_id,
    )
    connector.write(
        conn,
        slack_resource,
        WritePayload(text=attribution + reply.text),
        principal=PrincipalContext(
            principal_id=agent_principal_id,
            display_name=agent["display_name"],
            trust_label=TrustLabel(event_row["trust_label"]),
        ),
        mode="execute",
    )

    _log_say_action(
        conn,
        turn_id=ctx.turn_id,
        agent=agent,
        event_row=event_row,
        payload=payload,
        reply_text=reply.text,
        action_type=reply.action_type,
        technical_actor=f"slack:{installation_id}",
        extra_params={"channel": channel},
    )
    complete_turn(conn, ctx.turn_id, ctx.inbound_event_id)
    return ctx
