#!/usr/bin/env bash
# Build, test and install on the server (inside the LXC container, from the repo).
# Without --apply this is a dry run: it only shows what would happen.
#
# Usage: deploy/deploy.sh [--apply] [--skip-tests]
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APPLY=0
TESTS=1
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --skip-tests) TESTS=0 ;;
    *) echo "Unbekannt: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\033[1m==> %s\033[0m\n' "$*"; }
run() { if ((APPLY)); then "$@"; else printf '    (Probelauf) %s\n' "$*"; fi; }

cd "$REPO"
step "Stand: $(git rev-parse --short HEAD) $(git log -1 --format=%s)"
[[ -z "$(git status --porcelain)" ]] || echo "    Achtung: nicht committete Änderungen im Arbeitsverzeichnis"

step "Web-App bauen"
command -v npm >/dev/null || { echo "npm fehlt (apt install nodejs npm)" >&2; exit 1; }
run bash -c "cd web && npm ci --no-audit --no-fund && npm test && npm run build"

if ((TESTS)); then
  step "Server-Tests"
  python3 -c "import ensurepip" 2>/dev/null || { echo "python3-venv fehlt (apt install python3-venv)" >&2; exit 1; }
  run bash -c "cd server && { [[ -x .venv/bin/pip ]] || { rm -rf .venv && python3 -m venv .venv; }; } \
    && .venv/bin/pip install -q -r requirements.txt -r requirements-dev.txt && .venv/bin/python -m pytest -q"
fi

step "Installieren"
run sudo "$REPO/deploy/install.sh"

((APPLY)) || echo "Probelauf beendet. Mit --apply wirklich ausführen."
