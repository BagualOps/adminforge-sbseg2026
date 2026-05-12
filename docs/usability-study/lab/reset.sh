#!/usr/bin/env bash
# Zera o lab entre participantes:
#   - arquiva o histórico de comandos da sessão e o estado final do AdminForge
#   - apaga o estado (volta a vazio) e recria o alice.pub
#   - derruba e recria os containers-alvo (estado limpo)
set -euo pipefail
cd "$(dirname "$0")"
LAB="$PWD"
STATE="$LAB/state"
KEYS="$LAB/keys"
ARCHIVE="$LAB/archive"
STAMP="$(date +%Y%m%d-%H%M%S)"

[ -f "$KEYS/adminforge_id.pub" ] || { echo "erro: lab não preparado — rode ./prep.sh primeiro"; exit 1; }
mkdir -p "$ARCHIVE"

# arquiva
[ -f "$ARCHIVE/history-current" ] && mv "$ARCHIVE/history-current" "$ARCHIVE/history-$STAMP" || true
[ -d "$STATE" ] && tar czf "$ARCHIVE/state-$STAMP.tgz" -C "$LAB" state 2>/dev/null || true

# zera estado
rm -rf "$STATE"; mkdir -p "$STATE"
cp "$KEYS/alice.pub" "$LAB/alice.pub"

# recria containers
export ADMINFORGE_PUBKEY="$(cat "$KEYS/adminforge_id.pub")"
docker compose down -v
docker compose up -d --build

echo "lab resetado ($STAMP): estado vazio, containers recriados. arquivos em $ARCHIVE/"
