#!/bin/sh
set -e
cd "$(dirname "$0")"
port="${1:-${PORT:-8000}}"
python3 build.py
echo "http://127.0.0.1:$port/"
exec python3 -m http.server "$port" --bind 127.0.0.1
