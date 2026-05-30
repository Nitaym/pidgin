from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import bcrypt

from pidgin.util.ids import new_ulid, utc_now_iso


class WorkspaceError(Exception):
    pass


class InvalidPasswordError(WorkspaceError):
    pass


@dataclass
class AuthSidecar:
    workspace_id: str
    password_hash: str
    created_at: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "workspace_id": self.workspace_id,
                "password_hash": self.password_hash,
                "created_at": self.created_at,
            },
            indent=2,
        )

    @classmethod
    def from_file(cls, path: Path) -> AuthSidecar:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            workspace_id=data["workspace_id"],
            password_hash=data["password_hash"],
            created_at=data["created_at"],
        )


@dataclass
class WorkspacePaths:
    root: Path

    @property
    def auth_json(self) -> Path:
        return self.root / "auth.json"

    @property
    def db_sqlite(self) -> Path:
        return self.root / "db.sqlite"

    @property
    def memory_dir(self) -> Path:
        return self.root / "memory"

    @property
    def docs_dir(self) -> Path:
        return self.root / "docs"

    @property
    def blobs_dir(self) -> Path:
        return self.root / "blobs"

    @property
    def debug_dir(self) -> Path:
        return self.root / "_debug"

    def agent_memory_dir(self, handle: str) -> Path:
        return self.memory_dir / handle

    def agent_journal(self, handle: str) -> Path:
        return self.agent_memory_dir(handle) / "journal.md"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def default_pidgin_home() -> Path:
    return Path.home() / ".pidgin"


def workspaces_root(home: Path | None = None) -> Path:
    return (home or default_pidgin_home()) / "workspaces"


def registry_path(home: Path | None = None) -> Path:
    return (home or default_pidgin_home()) / "workspaces_registry.json"


def ensure_home(home: Path | None = None) -> Path:
    root = home or default_pidgin_home()
    root.mkdir(parents=True, exist_ok=True)
    reg = registry_path(root)
    if not reg.exists():
        reg.write_text(json.dumps({"workspaces": []}, indent=2), encoding="utf-8")
    return root


def register_workspace(
    workspace_id: str,
    display_name: str,
    slug: str,
    path: Path,
    home: Path | None = None,
) -> None:
    ensure_home(home)
    reg_file = registry_path(home)
    data = json.loads(reg_file.read_text(encoding="utf-8"))
    workspaces: list[dict[str, str]] = data.setdefault("workspaces", [])
    workspaces = [w for w in workspaces if w["id"] != workspace_id]
    workspaces.append(
        {
            "id": workspace_id,
            "display_name": display_name,
            "slug": slug,
            "path": str(path),
        }
    )
    data["workspaces"] = workspaces
    reg_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def create_workspace_layout(root: Path) -> WorkspacePaths:
    paths = WorkspacePaths(root=root)
    paths.memory_dir.mkdir(parents=True, exist_ok=True)
    paths.docs_dir.mkdir(parents=True, exist_ok=True)
    paths.blobs_dir.mkdir(parents=True, exist_ok=True)
    return paths


def create_workspace(display_name: str, password: str, slug: str, home: Path | None = None) -> WorkspacePaths:
    ensure_home(home)
    workspace_id = new_ulid()
    root = workspaces_root(home) / workspace_id
    if root.exists():
        raise WorkspaceError(f"Workspace directory already exists: {root}")

    root.mkdir(parents=True)
    paths = create_workspace_layout(root)

    auth = AuthSidecar(
        workspace_id=workspace_id,
        password_hash=hash_password(password),
        created_at=datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    )
    paths.auth_json.write_text(auth.to_json(), encoding="utf-8")
    register_workspace(workspace_id, display_name, slug, root, home=home)
    return paths


def resolve_workspace_paths_by_slug(slug: str, home: Path | None = None) -> WorkspacePaths:
    reg = json.loads(registry_path(home).read_text(encoding="utf-8"))
    entry = next((w for w in reg.get("workspaces", []) if w.get("slug") == slug), None)
    if entry is None:
        raise WorkspaceError(f"Unknown workspace: {slug}")

    paths = WorkspacePaths(root=Path(entry["path"]))
    if not paths.auth_json.exists():
        raise WorkspaceError(f"Missing auth.json for workspace {slug}")
    return paths


def resolve_workspace_paths(workspace_id: str, home: Path | None = None) -> WorkspacePaths:
    """Open workspace directory without password (operator auth is Google session)."""
    reg = json.loads(registry_path(home).read_text(encoding="utf-8"))
    entry = next((w for w in reg.get("workspaces", []) if w["id"] == workspace_id), None)
    if entry is None:
        raise WorkspaceError(f"Unknown workspace: {workspace_id}")

    paths = WorkspacePaths(root=Path(entry["path"]))
    if not paths.auth_json.exists():
        raise WorkspaceError(f"Missing auth.json for workspace {workspace_id}")
    return paths


def open_workspace_path(workspace_id: str, password: str, home: Path | None = None) -> WorkspacePaths:
    reg = json.loads(registry_path(home).read_text(encoding="utf-8"))
    entry = next((w for w in reg.get("workspaces", []) if w["id"] == workspace_id), None)
    if entry is None:
        raise WorkspaceError(f"Unknown workspace: {workspace_id}")

    paths = WorkspacePaths(root=Path(entry["path"]))
    if not paths.auth_json.exists():
        raise WorkspaceError(f"Missing auth.json for workspace {workspace_id}")

    auth = AuthSidecar.from_file(paths.auth_json)
    if not verify_password(password, auth.password_hash):
        raise InvalidPasswordError("Invalid workspace password")

    return paths
