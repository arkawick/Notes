#!/usr/bin/env bash
#
# Build a runnable CMWEB instance on Linux from the three source directories,
# without writing anything into them.
#
#   ./setup.sh                    build everything, keep an existing database
#   ./setup.sh --fresh            delete the database first and rebuild
#   ./setup.sh --relink           rebuild only the site/ tree, then stop
#   ./setup.sh --host HOST:PORT   Site row domain (default localhost:8000)
#   ./setup.sh --skip-apt         do not try to install apt packages
#
# See README.md for what each step corresponds to in the upstream Quick Guide.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

PROJECT="$ROOT/cmweb-project"
APP="$ROOT/cmweb-app"
STUBS_SRC="$ROOT/local-cmweb/stubs"

SITE="$HERE/site"
VENV="$HERE/ENV"
PY="$VENV/bin/python3"
FIXTURE="$APP/explorer/fixtures/testdata.json"

FRESH=0
RELINK_ONLY=0
SKIP_APT=0
SITE_HOST="localhost:8000"

while [ $# -gt 0 ]; do
    case "$1" in
        --fresh)    FRESH=1 ;;
        --relink)   RELINK_ONLY=1 ;;
        --skip-apt) SKIP_APT=1 ;;
        --host)     shift; SITE_HOST="${1:?--host needs an argument}" ;;
        -h|--help)  sed -n '3,15p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *)          echo "Unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

say()  { printf '\033[32;01m== %s\033[0m\n' "$*"; }
warn() { printf '\033[33;01m!! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31;01m!! %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- 0. checks

say "0/7  checking inputs"
[ -d "$PROJECT/cmweb" ] || die "cmweb-project not found at $PROJECT"
[ -d "$APP/explorer" ]  || die "cmweb-app not found at $APP"
[ -f "$FIXTURE" ]       || die "fixture not found at $FIXTURE"
[ -d "$STUBS_SRC" ]     || die "shims not found at $STUBS_SRC (expected local-cmweb/stubs)"
command -v python3 >/dev/null || die "python3 is not on PATH"

PYVER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"

# Django 5.2 supports Python 3.10 - 3.13. Ubuntu 22.04 ships 3.10, which is
# fine; 20.04 ships 3.8, which is not, even though the upstream
# requirements-20.txt also pins Django 5.2.8.
python3 - <<'PY' || die "Python $PYVER is too old: Django 5.2 needs 3.10 or newer. See INSTALL.md section 2."
import sys
sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)
PY

python3 -c 'import venv' 2>/dev/null || die \
    "the venv module is missing. On Debian/Ubuntu: sudo apt-get install python3-venv,
     or without sudo see INSTALL.md section 4b."

echo "     python3        $PYVER"
echo "     cmweb-project  $PROJECT"
echo "     cmweb-app      $APP"
echo "     site host      $SITE_HOST"

# ------------------------------------------------------------ 1. apt packages

if [ "$SKIP_APT" -eq 0 ]; then
    say "1/7  apt packages"
    if command -v apt-get >/dev/null && command -v sudo >/dev/null; then
        # Deliberately not cmweb-project/etc/apt-get-22.list: that list pulls
        # somc-c2d-repository and somc-virtualenv3 from Sony's apt repository,
        # and dev headers for PostgreSQL, ODBC, graphviz and LDAP that a local
        # SQLite instance does not need.
        sudo apt-get update
        # shellcheck disable=SC2046
        sudo apt-get install -y $(grep -v '^\s*#' "$HERE/etc/apt-packages.list" | tr '\n' ' ')
    else
        warn "apt-get or sudo missing -- skipping. Install the equivalents of"
        warn "$HERE/etc/apt-packages.list by hand if the build fails."
    fi
else
    say "1/7  apt packages (skipped)"
fi

# ------------------------------------------------------------- 2. site/ tree

say "2/7  assembling site/"

# The cmweb-manifest places cmweb-project at site/ and cmweb-app at site/apps.
# Reproducing that with two symlinks would mean creating site/apps and
# site/cmweb/secure.py *inside* cmweb-project. Both paths are gitignored
# upstream, so that would be legitimate -- but this working copy has no git
# repositories, so a mistake there is unrecoverable.
#
# Instead site/ is a real directory of symlinks into cmweb-project, with two
# exceptions that must be real files: cmweb/secure.py (generated) and
# cmweb/urls.py (patched). PATH_SITE therefore resolves to this directory and
# PATH_ROOT to linux-local-cmweb/, so the database, static output, cache and
# logs all land here rather than next to the source.

rm -rf "$SITE"
mkdir -p "$SITE/cmweb" "$SITE/etc"

# Top level of cmweb-project: manage.py, Makefile, static/, templates/, bin/
for entry in "$PROJECT"/*; do
    name="$(basename "$entry")"
    case "$name" in
        cmweb|etc) continue ;;          # handled below
    esac
    ln -s "$entry" "$SITE/$name"
done

# Dotfiles are not matched by the glob above. .pycodestylerc is the one that
# matters: `make kwalitee` passes it to pycodestyle by path.
for dotfile in .pycodestylerc; do
    if [ -e "$PROJECT/$dotfile" ]; then
        ln -s "$PROJECT/$dotfile" "$SITE/$dotfile"
    fi
done

# cmweb-app lands at site/apps, which is what settings.py appends to sys.path.
ln -s "$APP" "$SITE/apps"

# The cmweb package: symlink every module, then override two of them.
for entry in "$PROJECT"/cmweb/*; do
    ln -s "$entry" "$SITE/cmweb/$(basename "$entry")"
done

# secure.py -- mandatory. See etc/secure.py.in for why.
rm -f "$SITE/cmweb/secure.py"
cp "$HERE/etc/secure.py.in" "$SITE/cmweb/secure.py"

# urls.py -- the upstream Quick Guide says to edit this line by hand:
#     re_path(r'^accounts/login/?$', RedirectToUrl.as_view()),
# to
#     re_path(r'^accounts/login/?$', auth_views.LoginView.as_view()),
# because locally there is no Apache doing LDAP, so Django's own login view
# has to serve /accounts/login/. Copy and patch instead of editing the source.
rm -f "$SITE/cmweb/urls.py"
sed "s|re_path(r'\^accounts/login/?\$', RedirectToUrl.as_view())|re_path(r'^accounts/login/?\$', auth_views.LoginView.as_view())|" \
    "$PROJECT/cmweb/urls.py" > "$SITE/cmweb/urls.py"

if grep -q 'RedirectToUrl.as_view()' "$SITE/cmweb/urls.py"; then
    warn "the /accounts/login/ patch did not apply -- upstream urls.py may have"
    warn "changed. Log in at /admin/ instead, or patch site/cmweb/urls.py."
fi

# etc/: substitute our requirements for the internal-package ones, so that the
# upstream `make install` target works unmodified. The Makefile picks the file
# by `lsb_release --release`, so provide both names.
ln -s "$PROJECT/etc/apt-get-20.list" "$SITE/etc/apt-get-20.list"
ln -s "$PROJECT/etc/apt-get-22.list" "$SITE/etc/apt-get-22.list"
ln -s "$HERE/requirements-linux.txt" "$SITE/etc/requirements-20.txt"
ln -s "$HERE/requirements-linux.txt" "$SITE/etc/requirements-22.txt"

# The shim packages stand in for Sony-internal distributions. Shared with the
# Windows harness rather than duplicated. Remove any previous link first: it
# lives outside site/ and so survives the rm -rf above.
if [ -L "$HERE/stubs" ] || [ -e "$HERE/stubs" ]; then
    rm -f "$HERE/stubs"
fi
ln -s "$STUBS_SRC" "$HERE/stubs"

mkdir -p "$HERE/var/log" "$HERE/repository" "$HERE/cache"

echo "     site/            -> $(readlink -f "$SITE")"
echo "     site/apps        -> $APP"
echo "     stubs/           -> $STUBS_SRC"

if [ "$RELINK_ONLY" -eq 1 ]; then
    say "done (--relink: stopping before the virtualenv)"
    exit 0
fi

# -------------------------------------------------------------- 3. virtualenv

say "3/7  virtualenv"
if [ ! -x "$PY" ]; then
    python3 -m venv "$VENV"
    "$PY" -m pip install --upgrade pip wheel setuptools --quiet
else
    echo "     ENV/ already present"
fi

# The Makefile builds its virtualenv with somc-virtualenv3, a Sony-internal
# wrapper. Touching its stamp file makes `make install` skip that step and go
# straight to pip, so the upstream target works with the venv built above.
touch "$VENV/.virtualenv-installed"

# ----------------------------------------------------------- 4. dependencies

say "4/7  dependencies"
"$PY" -m pip install -r "$HERE/requirements-linux.txt"

# --------------------------------------------------------------- 5. database

cd "$SITE"
export DJANGO_SETTINGS_MODULE=cmweb.settings
export PYTHONPATH="$HERE/stubs"
export PYTHONDONTWRITEBYTECODE=1

if [ "$FRESH" -eq 1 ]; then
    say "5/7  removing existing database"
    rm -f "$HERE/cm_web_db"
else
    say "5/7  keeping existing database (use --fresh to reset)"
fi

say "     migrate"
# --skip-checks: the system checks import the URLconf, which reaches view
# classes that evaluate Parameter.get_int(...) at class-body scope. On an empty
# database that queries a table that does not exist yet.
"$PY" manage.py migrate --noinput --skip-checks

# ------------------------------------------------------------- 6. sample data

say "6/7  sample data"
# Equivalent to `make install-testdata`, but with model signals muted. The
# fixture is already-indexed data; replaying it through the normal save path
# re-fires CMWEB's indexing signals, which try to reach JIRA and M+ per issue
# and write a django-reversion revision per row. See
# ../local-cmweb/USING-TESTDATA.md.
"$PY" "$HERE/scripts/load_testdata.py" "$FIXTURE"

# ------------------------------------------------------------- 7. post-setup

say "7/7  site row, home page and login"
"$PY" "$HERE/scripts/post_setup.py" "$SITE_HOST"

cat <<EOF

Ready.

  ./run.sh                 http://127.0.0.1:8000/
  ./run.sh --port 8080     (re-run setup.sh --host localhost:8080 first)

  admin / s3cr17           from the fixture
  local / local            created by post_setup.py

EOF
