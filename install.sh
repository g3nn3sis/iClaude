#!/usr/bin/env bash
# iClaude installer for an Ubuntu/Debian host that already has Docker.
#
#   curl -fsSL https://raw.githubusercontent.com/g3nn3sis/iClaude/master/install.sh | bash
#
# Options:
#   --dir <path>   install location (default: ~/iclaude, or $ICLAUDE_DIR)
#   --ref <ref>    branch or tag to install (default: master, or $ICLAUDE_REF)
#   --no-setup     install and start only; skip Claude login and Inkbox setup
#
# Re-running is safe: it updates the checkout, rebuilds, and skips finished steps.
set -euo pipefail

REPO_URL="${ICLAUDE_REPO:-https://github.com/g3nn3sis/iClaude.git}"
DIR="${ICLAUDE_DIR:-$HOME/iclaude}"
REF="${ICLAUDE_REF:-master}"
BIN_DIR="${ICLAUDE_BIN_DIR:-$HOME/.local/bin}"
RUN_SETUP=1

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="${2:?--dir needs a path}"; shift ;;
    --ref) REF="${2:?--ref needs a branch or tag}"; shift ;;
    --no-setup) RUN_SETUP=0 ;;
    -h|--help) sed -n '2,12p' "$0" 2>/dev/null || true; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ -t 1 ]; then
  BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
else
  BOLD=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi
step() { echo "${BOLD}==> $*${RESET}"; }
ok()   { echo "  ${GREEN}✓${RESET} $*"; }
warn() { echo "  ${YELLOW}!${RESET} $*"; }
die()  { echo "${RED}✗ $*${RESET}" >&2; exit 1; }

step "Checking prerequisites"
[ "$(uname -s)" = "Linux" ] || die "iClaude runs on a Linux host (Ubuntu or Debian)."
[ "$(id -u)" -ne 0 ] || warn "Running as root. A regular user in the 'docker' group is recommended."
command -v git >/dev/null 2>&1 || die "git is missing. Install it with: sudo apt-get install -y git"
command -v docker >/dev/null 2>&1 || die "Docker is missing. Install it first: https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || die "The Docker Compose plugin is missing. Install it with: sudo apt-get install -y docker-compose-plugin"
if ! docker info >/dev/null 2>&1; then
  if [ -S /var/run/docker.sock ] && [ ! -w /var/run/docker.sock ]; then
    die "No permission to use Docker. Run: sudo usermod -aG docker $USER, then log out and back in, and re-run this installer."
  fi
  die "The Docker daemon is not running. Start it with: sudo systemctl enable --now docker"
fi
ok "Docker $(docker version --format '{{.Server.Version}}'), $(docker compose version --short 2>/dev/null || echo compose)"

step "Fetching iClaude ($REF) into $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch --quiet origin "$REF"
  git -C "$DIR" checkout --quiet "$REF" 2>/dev/null || git -C "$DIR" checkout --quiet -B "$REF" FETCH_HEAD
  git -C "$DIR" merge --quiet --ff-only FETCH_HEAD || die "Local changes in $DIR block the update. Commit or discard them, then re-run."
elif [ -e "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ]; then
  die "$DIR exists and is not an iClaude checkout. Choose another location with --dir."
else
  git clone --quiet --branch "$REF" "$REPO_URL" "$DIR"
fi
ok "$(git -C "$DIR" log -1 --format='%h %s')"

mkdir -p "$BIN_DIR"
ln -sfn "$DIR/iclaude" "$BIN_DIR/iclaude"
ok "Linked $BIN_DIR/iclaude"
case ":$PATH:" in
  *":$BIN_DIR:"*) ICLAUDE=iclaude ;;
  *) ICLAUDE="$DIR/iclaude"; warn "$BIN_DIR is not on your PATH; use $ICLAUDE or add it to PATH." ;;
esac

step "Building and starting the container (the first build takes a few minutes)"
"$DIR/iclaude" start
ok "Container started; it waits until setup is complete"

if [ "$RUN_SETUP" -eq 0 ]; then
  echo
  echo "Next: $ICLAUDE login, then $ICLAUDE setup"
  exit 0
fi

if ! { : </dev/tty; } 2>/dev/null; then
  warn "No terminal available for the interactive steps."
  echo "Next: $ICLAUDE login, then $ICLAUDE setup"
  exit 0
fi

step "Claude login"
if "$DIR/iclaude" check claude </dev/tty >/dev/null 2>&1; then
  ok "Already logged in"
else
  "$DIR/iclaude" login </dev/tty || die "Claude login did not finish. Re-run: $ICLAUDE login"
fi

step "Inkbox setup"
if "$DIR/iclaude" check inkbox webhook authorised </dev/tty >/dev/null 2>&1; then
  ok "Already configured (re-run $ICLAUDE setup to change it)"
else
  "$DIR/iclaude" setup </dev/tty
fi

step "Status"
if "$DIR/iclaude" check </dev/tty; then
  echo
  echo "${GREEN}${BOLD}iClaude is running.${RESET} Text your agent from iMessage."
  echo "Logs: $ICLAUDE logs -f    Diagnostics: $ICLAUDE doctor"
else
  echo
  echo "Some checks still fail. Fix them with the commands shown, then run: $ICLAUDE status"
fi
