#!/usr/bin/env bash
# Remove iClaude from this host.
#
#   iclaude uninstall               remove the container, image, command and auto-update;
#                                   keep your Claude login, Inkbox config, conversations and workspace
#   iclaude uninstall --purge       also delete all of that data (asks you to type "delete")
#
# Options:
#   --yes          do not ask for confirmation (with --purge, the data is deleted without asking)
#   --keep-files   keep the iClaude checkout directory
set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN_LINK="${ICLAUDE_BIN_DIR:-$HOME/.local/bin}/iclaude"
CRON_MARK="# iclaude-auto-update"
PURGE=0
ASSUME_YES=0
KEEP_FILES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --purge) PURGE=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --keep-files) KEEP_FILES=1 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
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

[ -f "$DIR/compose.yaml" ] && [ -f "$DIR/iclaude" ] || die "$DIR does not look like an iClaude checkout."

ask() {
  local answer
  { : </dev/tty; } 2>/dev/null || die "No terminal to confirm on. Re-run with --yes."
  read -r -p "$1 " answer </dev/tty
  printf '%s' "$answer"
}

echo "${BOLD}This removes iClaude from this server:${RESET}"
echo "  - the iclaude container, its network and image"
echo "  - the iclaude command ($BIN_LINK) and the daily auto-update"
[ "$KEEP_FILES" -eq 1 ] || echo "  - the checkout in $DIR"
if [ "$PURGE" -eq 1 ]; then
  echo "  - ${RED}${BOLD}all data${RESET}: your Claude login, Inkbox config, conversations, memory and /workspace files"
else
  echo "  Your data volumes (Claude login, Inkbox config, conversations, workspace) are kept."
fi

if [ "$ASSUME_YES" -eq 0 ]; then
  case "$(ask "Continue? [y/N]")" in y|Y|yes|YES) ;; *) echo "Nothing was removed."; exit 0 ;; esac
  if [ "$PURGE" -eq 1 ]; then
    echo "Back up first if unsure: docker run --rm -v iclaude_home:/v -v \"\$PWD\":/b alpine tar czf /b/iclaude-home.tgz -C /v ."
    [ "$(ask "Type delete to erase all iClaude data permanently:")" = "delete" ] || { echo "Nothing was removed."; exit 0; }
  fi
fi

step "Stopping and removing the container"
cd "$DIR"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  down_args=(--remove-orphans --rmi all)
  [ "$PURGE" -eq 1 ] && down_args+=(--volumes)
  docker compose down "${down_args[@]}"
  docker image rm iclaude:previous >/dev/null 2>&1 || true
  ok "Container and image removed"
  if [ "$PURGE" -eq 1 ]; then
    ok "Data volumes deleted"
  else
    ok "Data kept in Docker volumes iclaude_home and iclaude_workspace"
  fi
else
  warn "Docker is not reachable; skipped removing the container and image"
fi

step "Removing auto-update and the iclaude command"
if command -v crontab >/dev/null 2>&1 && crontab -l 2>/dev/null | grep -qF "$CRON_MARK"; then
  { crontab -l 2>/dev/null | grep -vF "$CRON_MARK" || true; } | crontab -
  ok "Auto-update disabled"
fi
if [ -L "$BIN_LINK" ] && [ "$(readlink -f "$BIN_LINK")" = "$DIR/iclaude" ]; then
  rm -f "$BIN_LINK"
  ok "Removed $BIN_LINK"
fi
rm -rf "${XDG_STATE_HOME:-$HOME/.local/state}/iclaude"

if [ "$KEEP_FILES" -eq 0 ]; then
  step "Removing $DIR"
  cd /
  rm -rf "$DIR"
  ok "Removed"
fi

echo
echo "${GREEN}${BOLD}iClaude is uninstalled.${RESET}"
[ "$PURGE" -eq 1 ] || echo "Reinstalling later picks up your kept data. Delete it with: docker volume rm iclaude_home iclaude_workspace"
echo "Your Inkbox agent and its webhooks still exist; remove them in the Inkbox Console if you no longer need them."
