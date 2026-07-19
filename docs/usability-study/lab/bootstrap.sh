#!/usr/bin/env bash
# Bootstrap do lab de avaliação de usabilidade do AdminForge — uma linha só.
#
#   curl -fsSL https://raw.githubusercontent.com/BagualOps/adminforge-sbseg2026/main/docs/usability-study/lab/bootstrap.sh | bash
#
# O que faz, tudo a nível de usuário (não instala nada no sistema):
#   - clona (ou atualiza) o repo em ./adminforge-sbseg2026 (no diretório onde você rodar isto)
#   - roda o prep.sh: cria um venv com o adminforge + autocomplete, gera as chaves
#     (serviço + exemplo da "Alice"), sobe os 3 containers-alvo e escreve o env.sh
#   - imprime o ponto de entrada no fim
#
# Requisitos da máquina: git, python3 (>= 3.11), docker (com 'docker compose' v2).
# Customizável por env: ADMINFORGE_LAB_DIR (destino — default ./adminforge-sbseg2026),
# ADMINFORGE_REPO_URL, ADMINFORGE_REPO_REF (branch ou tag — SHA de commit não funciona com clone --branch).
set -euo pipefail

REPO_URL="${ADMINFORGE_REPO_URL:-https://github.com/BagualOps/adminforge-sbseg2026.git}"
REPO_REF="${ADMINFORGE_REPO_REF:-main}"
DEST="${ADMINFORGE_LAB_DIR:-$PWD/adminforge-sbseg2026}"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31merro:\033[0m %s\n' "$*" >&2; exit 1; }

for c in git python3 docker ssh ssh-keygen; do command -v "$c" >/dev/null 2>&1 || die "'$c' não encontrado no PATH"; done
docker compose version >/dev/null 2>&1 || die "'docker compose' (v2) não disponível"
python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)' \
    || die "precisa de Python >= 3.11 (achei: $(python3 -V 2>&1))"

if [ -e "$DEST" ] && [ ! -d "$DEST/.git" ]; then
    die "$DEST já existe e não é um repositório git — remova-o ou defina ADMINFORGE_LAB_DIR"
fi
if [ -d "$DEST/.git" ]; then
    [ -f "$DEST/docs/usability-study/lab/prep.sh" ] \
        || die "$DEST é um repo git mas não parece ser o adminforge-sbseg2026 — defina ADMINFORGE_LAB_DIR para outro lugar"
    say "atualizando o repo em $DEST"
    git -C "$DEST" fetch -q --depth 1 origin "$REPO_REF"
    git -C "$DEST" reset -q --hard FETCH_HEAD
else
    say "clonando $REPO_URL ($REPO_REF) em $DEST"
    mkdir -p "$(dirname "$DEST")"
    git clone -q --depth 1 --branch "$REPO_REF" "$REPO_URL" "$DEST"
fi

say "preparando o lab (venv + chaves + containers) — pode levar 1–2 min na primeira vez ..."
exec bash "$DEST/docs/usability-study/lab/prep.sh"
