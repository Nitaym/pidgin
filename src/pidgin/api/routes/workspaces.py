from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from pidgin.api.deps import get_google_user, get_pidgin_home, require_google_user
from pidgin.services.workspace import create_workspace_with_db, get_singleton_workspace

router = APIRouter(prefix="/api", tags=["global"])


class CreateWorkspaceBody(BaseModel):
    name: str = Field(min_length=1)
    slug: str = Field(min_length=1)


def _workspace_payload(workspace) -> dict[str, str]:
    return {
        "id": workspace.id,
        "slug": workspace.slug,
        "display_name": workspace.display_name,
        "path": workspace.path,
    }


@router.get("/bootstrap")
def api_bootstrap(request: Request) -> dict:
    user = get_google_user(request)
    workspace = get_singleton_workspace(home=get_pidgin_home(request))
    return {
        "user": user.to_session() if user else None,
        "workspace": _workspace_payload(workspace) if workspace else None,
    }


@router.post("/workspace", status_code=201)
def api_create_workspace(body: CreateWorkspaceBody, request: Request) -> dict[str, str]:
    require_google_user(request)
    ws = create_workspace_with_db(body.name, body.slug, home=get_pidgin_home(request))
    return _workspace_payload(ws)
