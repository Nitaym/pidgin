#!/usr/bin/env python3
"""
Pidgin Office — backend API
===========================
A tiny dependency-free HTTP API (Python stdlib only) that persists the office
to a JSON file and stores the "missing features" notes as plain text.

Endpoints
---------
GET  /api/health             -> {"ok": true}
GET  /api/office             -> the saved office JSON (or {empty:true} on first run)
PUT  /api/office   {json}    -> overwrite the office store
GET  /api/features           -> {"text": "<contents of MISSING_FEATURES.md>"}
PUT  /api/features {text}    -> overwrite MISSING_FEATURES.md

Run:  python server.py        (listens on :8000, override with PORT env var)
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
OFFICE_PATH = os.path.join(DATA_DIR, "office.json")
# MISSING_FEATURES.md lives in the project root (one level up from backend/).
FEATURES_PATH = os.path.join(os.path.dirname(ROOT), "MISSING_FEATURES.md")
PORT = int(os.environ.get("PORT", "8770"))

os.makedirs(DATA_DIR, exist_ok=True)

DEFAULT_FEATURES = "# Missing Features\n\n- (add notes here)\n"


def read_features():
    if not os.path.exists(FEATURES_PATH):
        with open(FEATURES_PATH, "w", encoding="utf-8") as f:
            f.write(DEFAULT_FEATURES)
    with open(FEATURES_PATH, "r", encoding="utf-8") as f:
        return f.read()


def write_features(text):
    with open(FEATURES_PATH, "w", encoding="utf-8") as f:
        f.write(text)


def read_office():
    if not os.path.exists(OFFICE_PATH):
        return {"agents": [], "decorations": [], "_seq": 1, "empty": True}
    with open(OFFICE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def write_office(data):
    with open(OFFICE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class Handler(BaseHTTPRequestHandler):
    # ── helpers ──────────────────────────────────────────────────────────────
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def log_message(self, fmt, *args):
        # concise one-line log
        print(f"  {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")

    # ── routes ───────────────────────────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self._send_json(200, {"ok": True})
        if path == "/api/office":
            return self._send_json(200, read_office())
        if path == "/api/features":
            return self._send_json(200, {"text": read_features()})
        return self._send_json(404, {"error": "not found"})

    def do_PUT(self):
        path = urlparse(self.path).path
        body = self._read_body()
        if path == "/api/office":
            write_office(body)
            return self._send_json(200, {"ok": True})
        if path == "/api/features":
            write_features(body.get("text", ""))
            return self._send_json(200, {"ok": True})
        return self._send_json(404, {"error": "not found"})

    # allow POST as an alias for PUT
    do_POST = do_PUT


def main():
    server = ThreadingHTTPServer(("", PORT), Handler)
    print(f"Pidgin Office backend running on http://localhost:{PORT}")
    print(f"  office store : {OFFICE_PATH}")
    print(f"  features file: {FEATURES_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
