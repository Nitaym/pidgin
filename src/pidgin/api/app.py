from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import pidgin.connectors  # noqa: F401 — register connector factories
from pidgin.api.routes import auth, devterm_api, devwork_api, hooks, workspace_api, workspaces
from pidgin.runtime.worker import BackgroundWorker
from pidgin.services.workspace import reconcile_workspace_agents
from pidgin.voice import routes as voice_routes

# Configure logging early — runs in every worker process (including --reload workers)
def _ensure_logging() -> None:
    level_name = os.getenv("PIDGIN_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    if not root.handlers:  # don't reconfigure if already set up by __main__
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        )
    logging.getLogger("pidgin").setLevel(level)
    if level > logging.DEBUG:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

_ensure_logging()


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
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        raw_home = app.state.pidgin_home
        home = Path(raw_home) if raw_home else None
        # Reconcile the pre-seeded agents (Enablement, HR) across every existing
        # workspace, so workspaces created before a seed agent was added gain it.
        # Idempotent and isolated — never block startup if it fails.
        try:
            reconcile_workspace_agents(home)
        except Exception:  # noqa: BLE001 — reconciliation must not block startup
            logging.getLogger(__name__).exception(
                "[startup] workspace agent reconciliation failed"
            )
        worker = BackgroundWorker(home)
        app.state.worker = worker
        worker.start()
        # Developer worker: Linear watcher + Claude Code executor (DEVELOPER_WORKER_SPEC).
        from pidgin.devwork.runner import DevRunner, set_runner

        dev_runner = DevRunner(home)
        set_runner(dev_runner)
        dev_runner.start()
        try:
            yield
        finally:
            dev_runner.stop()
            set_runner(None)
            from pidgin.devwork.terminals import manager as terminal_manager

            terminal_manager().shutdown()
            worker.stop()

    app = FastAPI(
        title="Pidgin",
        description="AI workforce workspace API + UI",
        lifespan=lifespan,
    )
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
    app.include_router(devwork_api.router)
    app.include_router(devterm_api.router)
    app.include_router(hooks.router)
    app.include_router(voice_routes.router)

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


def create_app_from_env() -> FastAPI:
    """Factory entry for uvicorn --reload (reads PIDGIN_HOME from the environment)."""
    home_raw = os.getenv("PIDGIN_HOME", "").strip()
    home = Path(home_raw).expanduser() if home_raw else None
    return create_app(pidgin_home=home)


app = create_app()
