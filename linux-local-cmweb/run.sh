#!/usr/bin/env bash
#
# Start the local CMWEB development server.
#
#   ./run.sh                 http://127.0.0.1:8000/
#   ./run.sh --port 8080     another port
#   ./run.sh --public        listen on 0.0.0.0 so other machines can reach it
#   ./run.sh -- <args>       pass the rest straight to manage.py runserver
#
# Note: the Site row must match the host:port you browse with, because
# settings.py defines no SITE_ID. Re-run  ./setup.sh --host <host:port>  if you
# change the port and feeds or absolute URLs start looking wrong.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE="$HERE/site"
PY="$HERE/ENV/bin/python3"

PORT=8000
BIND=127.0.0.1

while [ $# -gt 0 ]; do
    case "$1" in
        --port)    shift; PORT="${1:?--port needs an argument}" ;;
        --public)  BIND=0.0.0.0 ;;
        --)        shift; break ;;
        -h|--help) sed -n '3,12p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *)         echo "Unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

[ -x "$PY" ]     || { echo "No ENV/ found -- run ./setup.sh first." >&2; exit 1; }
[ -d "$SITE" ]   || { echo "No site/ found -- run ./setup.sh first." >&2; exit 1; }
[ -f "$HERE/cm_web_db" ] || {
    echo "No database found -- run ./setup.sh first." >&2; exit 1; }

cd "$SITE"
export DJANGO_SETTINGS_MODULE=cmweb.settings
export PYTHONPATH="$HERE/stubs"
export PYTHONDONTWRITEBYTECODE=1

printf '\033[32;01mCMWEB local  ->  http://%s:%s/\033[0m\n' "$BIND" "$PORT"
cat <<'EOF'
  builds     /builds/
  commits    /commits/
  repos      /repositories/
  admin      /admin/     admin / s3cr17   or   local / local
  login      /accounts/login/

EOF

exec "$PY" manage.py runserver "$BIND:$PORT" "$@"
