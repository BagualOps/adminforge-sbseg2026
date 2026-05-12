#!/usr/bin/env bash
# Sobe o lab de avaliação de usabilidade do AdminForge nesta máquina.
#
#   - cria/usa um venv com o adminforge + autocomplete (argcomplete)
#   - gera as chaves (chave de serviço do AdminForge + chave de exemplo da "Alice")
#   - sobe os 3 containers-alvo (web-01, web-02, db-03)
#   - escreve um env.sh para o participante dar `source`
#   - imprime o ponto de entrada (os IPs/portas da frota ja estao no roteiro)
#
# Idempotente: rodar de novo não recria chaves nem venv; só garante os containers no ar.
# Para zerar entre participantes: ./reset.sh
set -euo pipefail
cd "$(dirname "$0")"
LAB="$PWD"
SRC="${ADMINFORGE_SRC:-$(cd "$LAB/../../.." && pwd)}"   # raiz do repo adminforge
STATE="$LAB/state"
KEYS="$LAB/keys"
ARCHIVE="$LAB/archive"

command -v docker >/dev/null || { echo "erro: docker não encontrado"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "erro: 'docker compose' não disponível"; exit 1; }
command -v python3 >/dev/null || { echo "erro: python3 não encontrado"; exit 1; }
[ -f "$SRC/pyproject.toml" ] || { echo "erro: não achei o repo adminforge em $SRC (defina ADMINFORGE_SRC)"; exit 1; }

mkdir -p "$KEYS" "$STATE" "$ARCHIVE"

# 1) chave de serviço do AdminForge (a pública vai pros containers; a privada o adminforge usa)
[ -f "$KEYS/adminforge_id" ] || ssh-keygen -t ed25519 -N '' -f "$KEYS/adminforge_id" -C 'adminforge@lab' -q
# 2) chave de exemplo da "Alice" — só a .pub é usada no roteiro (Tarefa 1)
[ -f "$KEYS/alice" ] || ssh-keygen -t ed25519 -N '' -f "$KEYS/alice" -C 'alice@laptop' -q
cp "$KEYS/alice.pub" "$LAB/alice.pub"

export ADMINFORGE_PUBKEY="$(cat "$KEYS/adminforge_id.pub")"

# 3) venv com o adminforge + autocomplete
[ -d "$LAB/venv" ] || python3 -m venv "$LAB/venv"
"$LAB/venv/bin/pip" install -q --upgrade pip
"$LAB/venv/bin/pip" install -q "$SRC[completion]"

# 4) containers-alvo
docker compose up -d --build

# 5) espera o sshd dos alvos responder com a chave de serviço
for p in 2201 2202 2203; do
    ok=""
    for _ in $(seq 1 30); do
        if ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
               -o ConnectTimeout=2 -i "$KEYS/adminforge_id" -p "$p" adminforge@127.0.0.1 true 2>/dev/null; then
            ok=1; break
        fi
        sleep 1
    done
    [ -n "$ok" ] || { echo "aviso: container na porta $p não respondeu em 30s"; }
done

# 6) ambiente para o participante (source nisso)
cat > "$LAB/env.sh" <<EOF
# source este arquivo para usar o adminforge no lab desta sessão
export PATH="$LAB/venv/bin:\$PATH"
export ADMINFORGE_STATE="$STATE"
export ADMINFORGE_SSH_KEY="$KEYS/adminforge_id"
export ADMINFORGE_SSH_USER="adminforge"
export ADMINFORGE_SUPERADMIN="\${USER:-pesquisa}"
export ADMINFORGE_LANG="pt"                         # CLI em pt-br no estudo; troque p/ en se precisar
export HISTFILE="$ARCHIVE/history-current"          # comandos da sessão; reset.sh arquiva
eval "\$(register-python-argcomplete adminforge 2>/dev/null)" || true
eval "\$(register-python-argcomplete af 2>/dev/null)" || true   # 'af' = atalho de 'adminforge'
cd "$LAB" || true                                   # passa a trabalhar na pasta do lab (alice.pub esta aqui)
EOF

cat <<EOF

================  lab pronto  ================
 Ponto de entrada (nesta máquina):

   source $LAB/env.sh           # (entra na pasta do lab)
   adminforge --help            # autocomplete: tecle Tab

 Chave pública da "Alice" (Tarefa 1):  ./alice.pub  (na pasta do lab, após o source)
 Estado do AdminForge (vazio):         $STATE

 Frota (ja consta na Tarefa 2 do roteiro):
   web-01  ->  127.0.0.1 : 2201
   web-02  ->  127.0.0.1 : 2202   (tem drift de sudoers semeado p/ a Tarefa 8)
   db-03   ->  127.0.0.1 : 2203

 Roteiro do participante:  ../ROTEIRO_PARTICIPANTE.md
 Guia do facilitador:      ../GUIA_FACILITADOR.md
 Entre participantes:      ./reset.sh
==============================================
EOF
