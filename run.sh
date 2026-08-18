#!/usr/bin/env bash
# Starts the FIR Selector server and opens it in your browser.
set -euo pipefail
cd "$(dirname "$0")"

python3 app.py &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

sleep 1.5
open "http://localhost:5002"

wait "$SERVER_PID"
