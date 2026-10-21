#!/usr/bin/env bash
# Update iClaude: fast-forward the checkout, rebuild, restart, and roll back if a working
# install stops passing its checks. Run through `iclaude update` (or `--auto` from cron).
set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$DIR"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/iclaude"
AUTO=0
REBUILD_AFTER_DAYS="${ICLAUDE_REBUILD_AFTER_DAYS:-7}"
HEALTH_WAIT="${ICLAUDE_UPDATE_HEALTH_WAIT:-180}"

case "${1:-}" in
  --auto) AUTO=1 ;;
  "") ;;
  *) echo "Usage: iclaude update [--auto]" >&2; exit 2 ;;
esac

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }
die() { log "update failed: $*"; exit 1; }

mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/update.lock"
flock -n 9 || { log "another update is already running"; exit 0; }

[ -d .git ] || die "$DIR is not a git checkout; reinstall with install.sh to get updates"
branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$branch" != "HEAD" ] || die "the checkout is pinned to a fixed version (detached HEAD); check out a branch to update"
[ -z "$(git status --porcelain --untracked-files=no)" ] || die "local changes in $DIR; commit or discard them first"

git fetch --quiet origin "$branch" || die "could not reach the iClaude repository"
old="$(git rev-parse HEAD)"
new="$(git rev-parse FETCH_HEAD)"

image_age_days() {
  local created
  created="$(docker image inspect -f '{{.Created}}' "${ICLAUDE_IMAGE:-iclaude:local}" 2>/dev/null)" || { echo 9999; return; }
  echo $(( ($(date +%s) - $(date -d "$created" +%s)) / 86400 ))
}

bad_file="$STATE_DIR/rolled-back-commit"
if [ "$AUTO" -eq 1 ] && [ "$old" != "$new" ] && [ "$(cat "$bad_file" 2>/dev/null)" = "$new" ]; then
  log "skipping ${new:0:7}, which was rolled back earlier; run iclaude update to retry it"
  exit 0
fi

if [ "$old" = "$new" ]; then
  if [ "$AUTO" -eq 1 ] && [ "$(image_age_days)" -lt "$REBUILD_AFTER_DAYS" ]; then
    log "up to date at ${old:0:7}"
    exit 0
  fi
  log "no new commits; rebuilding to pick up base image security updates"
else
  git merge-base --is-ancestor "$old" "$new" || die "remote history changed (not a fast-forward); update manually"
fi

checks_pass() { "$DIR/iclaude" check >/dev/null 2>&1; }
was_healthy=0
if [ -n "$(docker compose ps --status running -q iclaude 2>/dev/null)" ] && checks_pass; then
  was_healthy=1
fi

image="${ICLAUDE_IMAGE:-iclaude:local}"
previous="${image%%:*}:previous"
has_previous=0
if docker image inspect "$image" >/dev/null 2>&1; then
  docker tag "$image" "$previous"
  has_previous=1
fi

restore_checkout() { [ "$(git rev-parse HEAD)" = "$old" ] || git reset --quiet --keep "$old"; }

rollback() {
  restore_checkout
  [ "$has_previous" -eq 1 ] || die "$1; no previous image to roll back to"
  docker tag "$previous" "$image"
  docker compose up -d --no-build
  [ "$old" = "$new" ] || echo "$new" > "$bad_file"
  die "$1; rolled back to ${old:0:7}"
}

[ "$old" = "$new" ] || git merge --quiet --ff-only FETCH_HEAD
if ! docker compose build --pull; then
  restore_checkout
  die "image build failed; the running version is unchanged"
fi
docker compose up -d --no-build

if [ "$was_healthy" -eq 1 ]; then
  deadline=$((SECONDS + HEALTH_WAIT))
  until checks_pass; do
    [ "$SECONDS" -lt "$deadline" ] || rollback "checks failed after updating to ${new:0:7}"
    sleep 5
  done
fi

rm -f "$bad_file"
if [ "$old" = "$new" ]; then
  log "rebuilt ${new:0:7}"
else
  log "updated ${old:0:7} -> ${new:0:7}: $(git log -1 --format=%s "$new")"
fi
