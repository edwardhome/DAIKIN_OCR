#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
uv run nameplate init-db
uv run nameplate worker &
nameplate_worker_pid=$!
cleanup() {
  kill "$nameplate_worker_pid" 2>/dev/null || true
  wait "$nameplate_worker_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
uv run nameplate serve
