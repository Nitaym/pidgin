#!/usr/bin/env bash
# Start the Pidgin Office backend (Python stdlib API on :8770)
set -e
cd "$(dirname "$0")/backend"
echo "Starting backend on http://localhost:8770 ..."
python server.py
