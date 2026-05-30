"""Run the admin server: uv run pidgin-admin"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Pidgin administration UI + API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--home", type=Path, default=None, help="Pidgin home directory")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    from pidgin.api.app import create_app

    app = create_app(pidgin_home=args.home)
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
