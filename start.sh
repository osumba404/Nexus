#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Epicenter Nexus — Linux / macOS startup script
# Usage:
#   ./start.sh               # 3 workers × 8 threads (ports 8001-8003)
#   ./start.sh --dev         # Django dev server on port 8080
#   ./start.sh --workers 5 --threads 12
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Activate virtualenv if present
if [[ -f "$ROOT/venv/bin/activate" ]]; then
    source "$ROOT/venv/bin/activate"
fi

DEV=false
WORKERS=3
THREADS=8
PORT=8001

while [[ $# -gt 0 ]]; do
    case $1 in
        --dev)      DEV=true;       shift ;;
        --workers)  WORKERS="$2";   shift 2 ;;
        --threads)  THREADS="$2";   shift 2 ;;
        --port)     PORT="$2";      shift 2 ;;
        *)          echo "Unknown option: $1"; exit 1 ;;
    esac
done

if $DEV; then
    echo "[Nexus] Starting development server on port 8080…"
    python manage.py runserver 8080
    exit 0
fi

echo "[Nexus] Applying migrations…"
python manage.py migrate --noinput

echo "[Nexus] Starting $WORKERS Waitress workers (ports $PORT–$((PORT + WORKERS - 1)))…"
python serve.py --workers "$WORKERS" --threads "$THREADS" --port "$PORT"
