"""Minimal Linear GraphQL client (outbound HTTPS only; no webhooks).

Auth is a personal API key of the dedicated Linear member the worker acts as,
sent as the ``Authorization`` header. See specs/DEVELOPER_WORKER_SPEC.html §5.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"


class LinearError(Exception):
    pass


class LinearAuthError(LinearError):
    pass


class LinearRateLimited(LinearError):
    pass


_ISSUE_FIELDS = """
  id identifier title url branchName priority createdAt updatedAt
  state { id name type }
  assignee { id name email }
  creator { id name }
  labels { nodes { id name } }
  team { id key }
"""


@dataclass
class Issue:
    id: str
    key: str
    title: str
    url: str
    branch_name: str
    priority: int
    created_at: str
    updated_at: str
    state_id: str
    state_name: str
    state_type: str
    assignee_id: str | None
    assignee_name: str | None
    team_id: str
    label_ids: dict[str, str] = field(default_factory=dict)  # name(lower) -> id
    blocked: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def label_names(self) -> list[str]:
        return list(self.label_ids.keys())

    def has_label(self, name: str) -> bool:
        return name.lower() in self.label_ids


def _to_issue(node: dict[str, Any]) -> Issue:
    labels = {
        str(lbl["name"]).lower(): lbl["id"] for lbl in (node.get("labels") or {}).get("nodes", [])
    }
    blocked = False
    for rel in (node.get("inverseRelations") or {}).get("nodes", []):
        if rel.get("type") == "blocks":
            blocker_state = ((rel.get("issue") or {}).get("state") or {}).get("type")
            if blocker_state not in ("completed", "canceled"):
                blocked = True
    assignee = node.get("assignee") or {}
    state = node.get("state") or {}
    return Issue(
        id=node["id"],
        key=node["identifier"],
        title=node.get("title") or "",
        url=node.get("url") or "",
        branch_name=node.get("branchName") or "",
        priority=int(node.get("priority") or 0),
        created_at=node.get("createdAt") or "",
        updated_at=node.get("updatedAt") or "",
        state_id=state.get("id") or "",
        state_name=state.get("name") or "",
        state_type=state.get("type") or "",
        assignee_id=assignee.get("id"),
        assignee_name=assignee.get("name"),
        team_id=(node.get("team") or {}).get("id") or "",
        label_ids=labels,
        blocked=blocked,
        raw=node,
    )


class LinearClient:
    def __init__(self, api_key: str, *, timeout: float = 30.0) -> None:
        if not api_key:
            raise LinearAuthError("No Linear API key configured")
        self._key = api_key.strip()
        self._timeout = timeout

    # -- transport ---------------------------------------------------------
    def gql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            resp = httpx.post(
                LINEAR_GRAPHQL_URL,
                json={"query": query, "variables": variables or {}},
                headers={"Authorization": self._key, "Content-Type": "application/json"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise LinearError(f"Linear unreachable: {exc}") from exc
        if resp.status_code == 401:
            raise LinearAuthError("Linear rejected the API key (401)")
        if resp.status_code == 429:
            raise LinearRateLimited("Linear rate limit hit (429)")
        try:
            body = resp.json()
        except ValueError as exc:
            raise LinearError(f"Linear returned {resp.status_code}: {resp.text[:200]}") from exc
        errors = body.get("errors")
        if errors:
            msg = "; ".join(str(e.get("message")) for e in errors)
            codes = {str((e.get("extensions") or {}).get("code", "")) for e in errors}
            if "RATELIMITED" in codes:
                raise LinearRateLimited(msg)
            if "AUTHENTICATION_ERROR" in codes:
                raise LinearAuthError(msg)
            raise LinearError(msg)
        return body.get("data") or {}

    # -- identity / metadata ----------------------------------------------
    def viewer(self) -> dict[str, Any]:
        data = self.gql(
            """query { viewer { id name displayName email }
                       organization { name urlKey }
                       teams(first: 100) { nodes { id key name } } }"""
        )
        return {
            "viewer": data.get("viewer") or {},
            "organization": data.get("organization") or {},
            "teams": (data.get("teams") or {}).get("nodes", []),
        }

    def team_meta(self, team_id: str) -> dict[str, Any]:
        data = self.gql(
            """query($id: String!) { team(id: $id) {
                 id key name
                 states(first: 100) { nodes { id name type position } }
                 members(first: 200) { nodes { id name displayName email active } }
               } }""",
            {"id": team_id},
        )
        team = data.get("team") or {}
        return {
            "id": team.get("id"),
            "key": team.get("key"),
            "name": team.get("name"),
            "states": (team.get("states") or {}).get("nodes", []),
            "members": (team.get("members") or {}).get("nodes", []),
        }

    def find_label(self, name: str, team_id: str) -> str | None:
        data = self.gql(
            """query($name: String!) { issueLabels(first: 50, filter: { name: { eqIgnoreCase: $name } }) {
                 nodes { id name team { id } } } }""",
            {"name": name},
        )
        nodes = (data.get("issueLabels") or {}).get("nodes", [])
        # Prefer a team label, else a workspace label.
        for node in nodes:
            if (node.get("team") or {}).get("id") == team_id:
                return node["id"]
        for node in nodes:
            if not node.get("team"):
                return node["id"]
        return None

    def ensure_label(self, name: str, team_id: str, color: str = "#e5484d") -> str:
        found = self.find_label(name, team_id)
        if found:
            return found
        data = self.gql(
            """mutation($input: IssueLabelCreateInput!) { issueLabelCreate(input: $input) {
                 success issueLabel { id } } }""",
            {"input": {"name": name, "teamId": team_id, "color": color}},
        )
        return data["issueLabelCreate"]["issueLabel"]["id"]

    # -- issues ------------------------------------------------------------
    def todo_issues(self, team_id: str, todo_state_id: str) -> list[Issue]:
        data = self.gql(
            """query($team: ID!, $state: ID!) { issues(first: 100, filter: {
                   team: { id: { eq: $team } }, state: { id: { eq: $state } } }) {
                 nodes { """
            + _ISSUE_FIELDS
            + """ inverseRelations(first: 20) { nodes { type issue { state { type } } } } } } }""",
            {"team": team_id, "state": todo_state_id},
        )
        return [_to_issue(n) for n in (data.get("issues") or {}).get("nodes", [])]

    def issue(self, issue_id: str) -> Issue:
        data = self.gql(
            "query($id: String!) { issue(id: $id) { " + _ISSUE_FIELDS + " } }",
            {"id": issue_id},
        )
        node = data.get("issue")
        if not node:
            raise LinearError(f"Ticket not found: {issue_id}")
        return _to_issue(node)

    def issue_full(self, issue_id: str) -> dict[str, Any]:
        """Everything the prompt needs: description, comments, related titles."""
        data = self.gql(
            """query($id: String!) { issue(id: $id) { """
            + _ISSUE_FIELDS
            + """ description
                 project { name } projectMilestone { name }
                 parent { identifier title }
                 children(first: 30) { nodes { identifier title state { name } } }
                 relations(first: 20) { nodes { type relatedIssue { identifier title state { name } } } }
                 inverseRelations(first: 20) { nodes { type issue { identifier title state { name type } } } }
                 comments(first: 100) { nodes { id body createdAt user { id name } } }
               } }""",
            {"id": issue_id},
        )
        node = data.get("issue")
        if not node:
            raise LinearError(f"Ticket not found: {issue_id}")
        return node

    def update_issue(
        self,
        issue_id: str,
        *,
        state_id: str | None = None,
        assignee_id: str | None = None,
        unassign: bool = False,
        label_ids: list[str] | None = None,
    ) -> None:
        payload: dict[str, Any] = {}
        if state_id:
            payload["stateId"] = state_id
        if assignee_id:
            payload["assigneeId"] = assignee_id
        if unassign:
            payload["assigneeId"] = None
        if label_ids is not None:
            payload["labelIds"] = label_ids
        if not payload:
            return
        data = self.gql(
            """mutation($id: String!, $input: IssueUpdateInput!) {
                 issueUpdate(id: $id, input: $input) { success } }""",
            {"id": issue_id, "input": payload},
        )
        if not (data.get("issueUpdate") or {}).get("success"):
            raise LinearError("issueUpdate failed")

    def add_label(self, issue: Issue, label_id: str) -> None:
        ids = list(issue.label_ids.values())
        if label_id not in ids:
            self.update_issue(issue.id, label_ids=[*ids, label_id])

    def remove_label(self, issue: Issue, label_name: str) -> None:
        if not issue.has_label(label_name):
            return
        ids = [v for k, v in issue.label_ids.items() if k != label_name.lower()]
        self.update_issue(issue.id, label_ids=ids)

    def comment(self, issue_id: str, body: str) -> str:
        data = self.gql(
            """mutation($input: CommentCreateInput!) { commentCreate(input: $input) {
                 success comment { id } } }""",
            {"input": {"issueId": issue_id, "body": body}},
        )
        result = data.get("commentCreate") or {}
        if not result.get("success"):
            raise LinearError("commentCreate failed")
        return result["comment"]["id"]

    def create_issue(
        self,
        *,
        team_id: str,
        title: str,
        description: str,
        state_id: str | None = None,
        label_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"teamId": team_id, "title": title, "description": description}
        if state_id:
            payload["stateId"] = state_id
        if label_ids:
            payload["labelIds"] = label_ids
        data = self.gql(
            """mutation($input: IssueCreateInput!) { issueCreate(input: $input) {
                 success issue { id identifier url } } }""",
            {"input": payload},
        )
        result = data.get("issueCreate") or {}
        if not result.get("success"):
            raise LinearError("issueCreate failed")
        return result["issue"]
