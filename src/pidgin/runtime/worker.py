from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from pidgin.runtime.scheduler import run_once

log = logging.getLogger(__name__)


class BackgroundWorker:
    """Polls pending inbound_events and dispatches turns off the request path.

    Each inbound webhook (e.g. Slack) only persists an event and returns
    immediately; this worker runs the actual LLM turn so the ack stays well
    inside Slack's 3s window. The worker owns its own SQLite connection, opened
    inside its thread, so nothing is shared across threads.
    """

    def __init__(self, home: Path | None, *, poll_interval_seconds: float = 1.0) -> None:
        self._home = home
        self._poll = poll_interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="pidgin-worker", daemon=True
        )
        self._thread.start()
        log.info("[worker] background worker started")

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
        self._thread = None
        log.info("[worker] background worker stopped")

    def _run(self) -> None:
        conn: sqlite3.Connection | None = None
        while not self._stop.is_set():
            try:
                if conn is None:
                    conn = self._open_conn()
                    if conn is None:
                        # No workspace yet — keep polling until one is created.
                        self._stop.wait(self._poll)
                        continue
                processed = run_once(conn)
                if processed == 0:
                    self._stop.wait(self._poll)
            except Exception:  # noqa: BLE001 — worker must never die on one bad tick
                log.exception("[worker] tick failed; reopening connection")
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                conn = None
                self._stop.wait(self._poll)
        if conn is not None:
            conn.close()

    def _open_conn(self) -> sqlite3.Connection | None:
        from pidgin.db import apply_migrations, connect
        from pidgin.services.workspace import get_singleton_workspace
        from pidgin.workspace import resolve_workspace_paths

        workspace = get_singleton_workspace(home=self._home)
        if workspace is None:
            return None
        paths = resolve_workspace_paths(workspace.id, home=self._home)
        conn = connect(paths.db_sqlite)
        apply_migrations(conn)
        log.info("[worker] connected to workspace %s", workspace.id)
        return conn
