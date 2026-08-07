#!/usr/bin/env bash
# Removes what a run of this artifact leaves behind, inside the clone and outside it.
# Never touches anything tracked by git, and never removes the clone.
#
#   ./cleanup.sh --dry-run   list what would go, delete nothing
#   ./cleanup.sh             remove it
set -euo pipefail
cd "$(dirname "$0")"

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

total=0
gone() {
  local p="$1" what="$2" sz
  [ -e "$p" ] || return 0
  sz=$(du -sm "$p" 2>/dev/null | cut -f1); sz=${sz:-0}
  total=$((total + sz))
  printf '  %-44s %5s MB  %s\n' "$p" "$sz" "$what"
  [ "$DRY" = "1" ] || rm -rf "$p"
}

echo "Removing what a run of this artifact leaves behind:"
gone .venv          "the Python environment"
gone .pytest_cache  "test cache"
gone build          "packaging output"
for d in *.egg-info; do gone "$d" "packaging metadata"; done
gone "${ADMINFORGE_STATE:-}" "the state directory named by ADMINFORGE_STATE"

# Claim #1 builds a local fleet. Its own trap removes it on a clean exit, but an
# interrupted run leaves containers, networks and the base images behind.
if command -v docker >/dev/null; then
  ids="$(docker ps -aq --filter 'name=adminforge' 2>/dev/null || true)"
  if [ -n "$ids" ]; then
    n=$(printf '%s\n' "$ids" | wc -l)
    printf '  %-44s %5s      %s\n' "$n container(s) adminforge*" "-" "the claim fleet"
    [ "$DRY" = "1" ] || docker rm -f $ids >/dev/null
  fi
  nets="$(docker network ls -q --filter 'name=adminforge' 2>/dev/null || true)"
  if [ -n "$nets" ]; then
    printf '  %-44s %5s      %s\n' "docker networks adminforge*" "-" "the claim network"
    [ "$DRY" = "1" ] || docker network rm $nets >/dev/null 2>&1 || true
  fi
fi

echo
if [ "$DRY" = "1" ]; then
  echo "Dry run: nothing was removed. ${total} MB would be freed."
else
  echo "Done. ${total} MB freed. Nothing tracked by git was touched."
fi
