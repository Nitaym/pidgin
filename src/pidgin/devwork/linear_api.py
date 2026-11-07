"""Minimal Linear GraphQL client (outbound HTTPS only; no webhooks).

Auth is a personal API key of the dedicated Linear member the worker acts as,
sent as the ``Authorization`` header. See specs/DEVELOPER_WORKER_SPEC.html §5.2.
"""

from __future__ import annotations

import hashlib
import time
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


@dataclass
class RateInfo:
    """Linear's rate-limit headers from the latest response for one API key.

    Linear allows 2,500 requests/hour per user (shared by every key acting as
    that user) and a complexity budget; resets are epoch seconds.
    """

    requests_limit: int | None = None
    requests_remaining: int | None = None
    requests_reset: float | None = None
    complexity_limit: int | None = None
    complexity_remaining: int | None = None
    complexity_reset: float | None = None
    last_complexity: int | None = None
    seen_at: float = 0.0


_RATES: dict[str, RateInfo] = {}


def _key_id(api_key: str) -> str:
    return hashlib.sha256(api_key.strip().encode()).hexdigest()[:16]


def rate_for(api_key: str) -> RateInfo | None:
    return _RATES.get(_key_id(api_key))


def _int(value: str | None) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except ValueError:
        return None


def _epoch(value: str | None) -> float | None:
    n = _int(value)
    if n is None:
        return None
    return n / 1000 if n > 10_000_000_000 else float(n)  # Linear sends milliseconds


def parse_rate_headers(headers: Any) -> RateInfo | None:
    if headers.get("x-ratelimit-requests-remaining") is None and headers.get(
        "x-ratelimit-complexity-remaining"
    ) is None:
        return None
    return RateInfo(
        requests_limit=_int(headers.get("x-ratelimit-requests-limit")),
        requests_remaining=_int(headers.get("x-ratelimit-requests-remaining")),
        requests_reset=_epoch(headers.get("x-ratelimit-requests-reset")),
        complexity_limit=_int(headers.get("x-ratelimit-complexity-limit")),
        complexity_remaining=_int(headers.get("x-ratelimit-complexity-remaining")),
        complexity_reset=_epoch(headers.get("x-ratelimit-complexity-reset")),
        last_complexity=_int(headers.get("x-complexity")),
        seen_at=time.time(),
    )


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
        rate = parse_rate_headers(resp.headers)
        if rate is not None:
            _RATES[_key_id(self._key)] = rate
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

    @property
    def rate(self) -> RateInfo | None:
        return _RATES.get(_key_id(self._key))

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
    def issue_lists(
        self, lists: dict[str, dict[str, Any]], *, first: int = 25, max_pages: int = 20
    ) -> dict[str, list[Issue]]:
        """The trigger check: several filtered lists in one request, filtered in Linear.

        Each list (name -> IssueFilter) is paginated on its own, so a long list
        never hides another and no ticket is missed past a page. Only the fields
        the rules need; blockers are looked up separately for the few tickets
        that come back. Each issue's ``raw["_list"]`` names its list.
        """
        fields = """pageInfo { hasNextPage endCursor }
                 nodes { id identifier title url priority createdAt updatedAt
                   assignee { id } labels(first: 8) { nodes { id name } } }"""
        out: dict[str, list[Issue]] = {name: [] for name in lists}
        cursors: dict[str, str | None] = {name: None for name in lists}
        pending = list(lists)
        for _ in range(max_pages):
            if not pending:
                break
            params = ["$first: Int!"]
            parts: list[str] = []
            variables: dict[str, Any] = {"first": first}
            for name in pending:
                params += [f"${name}: IssueFilter!", f"${name}After: String"]
                parts.append(
                    f"{name}: issues(first: $first, after: ${name}After, filter: ${name}) {{ {fields} }}"
                )
                variables[name] = lists[name]
                variables[f"{name}After"] = cursors[name]
            data = self.gql(f"query({', '.join(params)}) {{ {' '.join(parts)} }}", variables)
            still: list[str] = []
            for name in pending:
                page = data.get(name) or {}
                for node in page.get("nodes", []):
                    issue = _to_issue(node)
                    issue.raw["_list"] = name
                    out[name].append(issue)
                info = page.get("pageInfo") or {}
                if info.get("hasNextPage") and info.get("endCursor"):
                    cursors[name] = info["endCursor"]
                    still.append(name)
            pending = still
        return out

    def entered_state_at(self, issue_ids: list[str], state_id: str) -> dict[str, str]:
        """When each ticket last moved into ``state_id`` (its creation time if it was
        created there), from the issue history. One request."""
        if not issue_ids:
            return {}
        data = self.gql(
            """query($ids: [ID!]!, $first: Int!) { issues(first: $first, filter: { id: { in: $ids } }) {
                 nodes { id createdAt history(first: 30) { nodes { createdAt toState { id } } } } } }""",
            {"ids": issue_ids, "first": len(issue_ids)},
        )
        out: dict[str, str] = {}
        for node in (data.get("issues") or {}).get("nodes", []):
            moves = [
                str(h.get("createdAt"))
                for h in (node.get("history") or {}).get("nodes", [])
                if (h.get("toState") or {}).get("id") == state_id
            ]
            out[node["id"]] = max(moves) if moves else str(node.get("createdAt") or "")
        return out

    def blocked_ids(self, issue_ids: list[str]) -> set[str]:
        """Which of these tickets are blocked by an open ticket (one request)."""
        if not issue_ids:
            return set()
        data = self.gql(
            """query($ids: [ID!]!, $first: Int!) { issues(first: $first, filter: { id: { in: $ids } }) {
                 nodes { id inverseRelations(first: 10) { nodes { type issue { state { type } } } } } } }""",
            {"ids": issue_ids, "first": len(issue_ids)},
        )
        return {
            node["id"]
            for node in (data.get("issues") or {}).get("nodes", [])
            if _to_issue({"identifier": "", **node}).blocked
        }

    def running_check(
        self, issue_ids: list[str], *, since: str, owner_id: str | None
    ) -> list[Issue]:
        """Status, assignee and the owner's new comments for running tickets, in one request.

        Comments are those created after ``since`` by ``owner_id`` (never the
        worker's own); they come back in ``issue.raw["comments"]["nodes"]``.
        """
        if not issue_ids:
            return []
        comment_filter: dict[str, Any] = {"createdAt": {"gt": since}}
        if owner_id:
            comment_filter["user"] = {"id": {"eq": owner_id}}
        else:
            comment_filter["id"] = {"eq": "none"}  # no owner set: forward nothing
        data = self.gql(
            """query($ids: [ID!]!, $first: Int!, $comments: CommentFilter!) {
                 issues(first: $first, filter: { id: { in: $ids } }) {
                   nodes { id identifier title url updatedAt state { id name type } assignee { id name }
                     comments(first: 20, filter: $comments) {
                       nodes { id body url createdAt user { id name displayName } } } } } }""",
            {"ids": issue_ids, "first": len(issue_ids), "comments": comment_filter},
        )
        return [_to_issue(n) for n in (data.get("issues") or {}).get("nodes", [])]

    @staticmethod
    def as_issue(node: dict[str, Any]) -> Issue:
        return _to_issue(node)

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
        description: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {}
        if description is not None:
            payload["description"] = description
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
