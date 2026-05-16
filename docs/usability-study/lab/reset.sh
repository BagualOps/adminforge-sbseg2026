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

# arquiva os comandos da sessão (desde o último reset), com horário por comando
hist="$ARCHIVE/history-current"
if [ -s "$hist" ]; then
    log="$ARCHIVE/comandos-$STAMP.log"
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$hist" > "$log" <<'PY'
import sys, datetime
ts = None
for linha in open(sys.argv[1], encoding="utf-8", errors="replace"):
    linha = linha.rstrip("\n")
    if linha.startswith("#") and linha[1:].isdigit():
        ts = int(linha[1:]); continue
    if not linha:
        continue
    quando = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "?"
    print(f"{quando}  {linha}")
    ts = None
PY
    else
        cp "$hist" "$log"   # fallback: histórico cru (linhas #epoch + comando)
    fi
    rm -f "$hist"
    n=$(grep -cve '^$' "$log" 2>/dev/null || true)
    nh=$(grep -cE -- '(--help| -h([[:space:]]|$))' "$log" 2>/dev/null || true)
    echo "comandos da sessão arquivados: $n linha(s), $nh com --help/-h → archive/$(basename "$log")"
fi
# arquiva a sessão gravada (comandos + saída), tirando os códigos ANSI p/ ficar legível
sess="$ARCHIVE/sessao-current.log"
if [ -s "$sess" ]; then
    sed -E 's/\x1b\[[0-9;?]*[A-Za-z]//g; s/\x1b\][^\a]*\a//g; s/\r//g' "$sess" \
        > "$ARCHIVE/sessao-$STAMP.log" 2>/dev/null || cp "$sess" "$ARCHIVE/sessao-$STAMP.log"
    rm -f "$sess"
    echo "sessão (comandos + saída) arquivada → archive/sessao-$STAMP.log"
fi

[ -d "$STATE" ] && tar czf "$ARCHIVE/state-$STAMP.tgz" -C "$LAB" state 2>/dev/null || true

# zera estado
rm -rf "$STATE"; mkdir -p "$STATE"
cp "$KEYS/alice.pub" "$LAB/alice.pub"

# recria containers
export ADMINFORGE_PUBKEY="$(cat "$KEYS/adminforge_id.pub")"
docker compose down -v
docker compose up -d --build

echo "lab resetado ($STAMP): estado vazio, containers recriados. arquivos em $ARCHIVE/"
