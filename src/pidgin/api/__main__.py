"""Run the admin server: uv run pidgin-admin"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import uvicorn

_PKG_ROOT = Path(__file__).resolve().parents[1]


def _configure_logging(level_name: str = "INFO") -> None:
    """Configure structured logging for Pidgin."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("pidgin").setLevel(level)
    if level > logging.DEBUG:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def _apply_home(home: Path | None) -> None:
    if home is not None:
        os.environ["PIDGIN_HOME"] = str(home.expanduser())


def _resolved_home(home: Path | None) -> Path | None:
    if home is not None:
        return home.expanduser()
    home_raw = os.getenv("PIDGIN_HOME", "").strip()
    return Path(home_raw).expanduser() if home_raw else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Pidgin administration UI + API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--home", type=Path, default=None, help="Pidgin home directory")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Restart on code changes (uses import-string factory; requires PIDGIN_HOME/--home)",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("PIDGIN_LOG_LEVEL", "INFO"),
        help="Logging level for pidgin modules (DEBUG, INFO, WARNING). Default: INFO",
    )
    args = parser.parse_args()

    _configure_logging(args.log_level)
    _apply_home(args.home)

    if args.reload:
        uvicorn.run(
            "pidgin.api.app:create_app_from_env",
            factory=True,
            host=args.host,
            port=args.port,
            reload=True,
            reload_dirs=[str(_PKG_ROOT)],
        )
        return

    from pidgin.api.app import create_app

    app = create_app(pidgin_home=_resolved_home(args.home))
    uvicorn.run(app, host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
