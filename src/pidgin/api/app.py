from __future__ import annotations

import os

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from pidgin.api.routes import auth, workspace_api, workspaces


def frontend_dist() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(
    *,
    pidgin_home: Path | None = None,
    secret_key: str = "pidgin-dev-secret",
    cors_origins: list[str] | None = None,
    allow_dev_auth: bool | None = None,
) -> FastAPI:
    if allow_dev_auth is None:
        allow_dev_auth = os.getenv("PIDGIN_ALLOW_DEV_AUTH", "").lower() in {
            "1",
            "true",
            "yes",
        }
    app = FastAPI(title="Pidgin", description="AI workforce workspace API + UI")
    app.state.pidgin_home = str(pidgin_home) if pidgin_home else None
    app.state.allow_dev_auth = allow_dev_auth
    app.add_middleware(SessionMiddleware, secret_key=secret_key)

    origins = cors_origins or [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router, prefix="/api")
    app.include_router(workspaces.router)
    app.include_router(workspace_api.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/admin")
    def legacy_admin_root() -> RedirectResponse:
        return RedirectResponse("/", status_code=308)

    @app.get("/admin/{rest:path}")
    def legacy_admin_paths(rest: str) -> RedirectResponse:
        return RedirectResponse(f"/{rest}", status_code=308)

    dist = frontend_dist()
    if dist.is_dir() and (dist / "index.html").is_file():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        def spa_root() -> FileResponse:
            return FileResponse(dist / "index.html")

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str) -> FileResponse:
            if full_path.startswith("api/") or "/api/" in full_path or full_path in {
                "docs",
                "redoc",
                "openapi.json",
            }:
                raise HTTPException(status_code=404, detail="Not found")
            candidate = dist / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:

        @app.get("/", response_class=HTMLResponse)
        def root_placeholder() -> HTMLResponse:
            return HTMLResponse(
                "<h1>Pidgin API</h1>"
                "<p>Frontend not built. Run <code>npm install && npm run build</code> "
                "in <code>src/frontend/</code>, or <code>npm run dev</code> for development.</p>"
                "<p>API: <a href='/docs'>/docs</a></p>"
            )

    return app


app = create_app()
