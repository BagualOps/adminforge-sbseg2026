#!/usr/bin/env bash
# One command: register a user, add an SSH key, verify the hash chain over both.
#
# Nothing is installed. AdminForge has no third-party runtime dependencies, so it runs
# from the clone with the system Python; that is the point Claim #3 measures.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || {
  echo "need: python3 >= 3.11 (found $("$PY" -V 2>&1))" >&2; exit 1; }

STATE="$(mktemp -d)"
KEY="$STATE/alice_key"
trap 'rm -rf "$STATE"' EXIT

ssh-keygen -q -t ed25519 -N "" -f "$KEY"

AF=("$PY" -m adminforge.cli.main --state "$STATE")
"${AF[@]}" user add --username alice --name "Alice Souza" --email alice@example.com \
  --key-file "$KEY.pub"
"${AF[@]}" history verify

echo "MINIMAL TEST: PASSED"
