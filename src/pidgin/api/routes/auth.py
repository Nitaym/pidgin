from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from pidgin.api.deps import (
    OAUTH_STATE_SESSION_KEY,
    clear_google_user,
    get_google_user,
    require_google_user,
    set_google_user,
)
from pidgin.auth.google import GoogleSettings, exchange_code_for_user, google_login_url, new_oauth_state

router = APIRouter(prefix="/auth", tags=["auth"])


class DevLoginBody(BaseModel):
    email: str = Field(default="dev@pidgin.local")
    name: str = Field(default="Dev User")


@router.get("/config")
def auth_config(request: Request) -> dict[str, bool]:
    settings = GoogleSettings.from_env()
    return {
        "google_enabled": settings.configured,
        "dev_login_enabled": bool(getattr(request.app.state, "allow_dev_auth", False)),
    }


@router.get("/me")
def auth_me(request: Request) -> dict:
    user = get_google_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user.to_session()


@router.get("/google/login")
def google_login(request: Request) -> RedirectResponse:
    settings = GoogleSettings.from_env()
    if not settings.configured:
        raise HTTPException(status_code=503, detail="Google login is not configured")
    state = new_oauth_state()
    request.session[OAUTH_STATE_SESSION_KEY] = state
    return RedirectResponse(google_login_url(settings, state=state), status_code=307)


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    settings = GoogleSettings.from_env()
    frontend = settings.frontend_url.rstrip("/")

    if error:
        return RedirectResponse(f"{frontend}/login?error={error}", status_code=307)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth code or state")

    expected_state = request.session.pop(OAUTH_STATE_SESSION_KEY, None)
    if expected_state != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    profile = await exchange_code_for_user(settings, code)
    from pidgin.api.deps import GoogleUser

    set_google_user(request, GoogleUser.from_session(profile))
    return RedirectResponse(f"{frontend}/", status_code=307)


@router.post("/dev-login")
def dev_login(request: Request, body: DevLoginBody) -> dict[str, str]:
    if not getattr(request.app.state, "allow_dev_auth", False):
        raise HTTPException(status_code=404, detail="Not found")
    from pidgin.api.deps import GoogleUser

    set_google_user(
        request,
        GoogleUser(
            sub=f"dev:{body.email}",
            email=body.email,
            name=body.name,
            picture="",
        ),
    )
    return {"status": "ok"}


@router.post("/logout")
def logout(request: Request) -> dict[str, str]:
    clear_google_user(request)
    return {"status": "logged_out"}
