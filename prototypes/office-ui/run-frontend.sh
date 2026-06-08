#!/usr/bin/env bash
# Serve the Pidgin Office frontend (static files on :5500)
set -e
cd "$(dirname "$0")"
echo "Serving frontend on http://localhost:5500 ..."
npx serve -p 5500 --no-clipboard
