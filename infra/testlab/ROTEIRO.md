# Roteiro completo de teste

Validação manual de **todo** o sistema AdminForge: 10 casos de uso + edge cases + (opcional) auditoria em servidor real.

> **Tempo estimado:** 15-20 minutos
> **Risco:** zero (lab isolado em containers); a parte opcional contra servidor real é read-only.
> **Pré-requisito mínimo:** Python 3.11+ e cliente OpenSSH. Para o lab Docker: `docker compose v2`.

---

## PARTE A — Setup (3 min)

### A.1 Clone

```bash
git clone https://github.com/BagualOps/adminforge-v1.git
cd adminforge-v1
```

Não precisa de `pip install` nem `venv` — zero deps de runtime.

### A.2 Atalho pro CLI

```bash
alias af='python3 -m adminforge.cli.main'
af --version    # adminforge 0.1.0
af --help | head -25
```

### A.3 Suba o lab Docker

```bash
mkdir -p infra/testlab/keys
ssh-keygen -t ed25519 -N "" -f infra/testlab/keys/adminforge_id -C "adminforge@testlab"

# A chave precisa de 0600 num filesystem POSIX (alguns mounts /mnt/* nao preservam):
cp infra/testlab/keys/adminforge_id /tmp/adminforge_id
chmod 600 /tmp/adminforge_id

cat > infra/testlab/.env <<EOF
ADMINFORGE_PUBKEY=$(cat infra/testlab/keys/adminforge_id.pub)
EOF

docker compose -f infra/testlab/docker-compose.yml --env-file infra/testlab/.env up -d --build
sleep 3
docker compose -f infra/testlab/docker-compose.yml ps
```

Esperado: 3 containers `Up`, expostos em `2201`, `2202`, `2203`.

### A.4 Verifique conectividade

```bash
for p in 2201 2202 2203; do
  ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -i /tmp/adminforge_id -p $p adminforge@127.0.0.1 'echo OK $(hostname)'
done
```

Esperado: `OK web-01`, `OK web-02`, `OK db-03`.

### A.5 Configure variáveis de ambiente

```bash
export ADMINFORGE_STATE=/tmp/lab-state
export ADMINFORGE_SSH_KEY=/tmp/adminforge_id
export ADMINFORGE_SSH_USER=adminforge
export ADMINFORGE_SUPERADMIN=cristhian

rm -rf /tmp/lab-state && mkdir -p /tmp/lab-state
```

---

## PARTE B — Os 10 casos de uso (10 min)

### UC-1 — Cadastrar admin

```bash
af admin add marina --nome "Marina Silva" --email marina@empresa.com
af admin add rui    --nome "Rui Costa"    --email rui@empresa.com
af admin add joao   --nome "João Pereira" --email joao@empresa.com
```

Validações:

```bash
af admin list                # tabela: 3 admins, status=ativo
af admin show marina         # detalhes + 0 credenciais + 0 grupos
```

**Edge case — duplicata:**

```bash
af admin add marina --nome X --email x@e.com
# Esperado: ERRO  ... username 'marina' ja existe
```

**Edge case — formato:**

```bash
af admin add "Marina!" --nome X --email x@e.com
# Esperado: ERRO  ... username invalido
af admin add valid --nome X --email "nao-e-email"
# Esperado: ERRO  ... email invalido
```

### UC-2 — Cadastrar / revogar chave SSH

```bash
ssh-keygen -t ed25519 -N "" -f /tmp/marina -C "marina@laptop"
ssh-keygen -t ed25519 -N "" -f /tmp/rui    -C "rui@laptop"
ssh-keygen -t ed25519 -N "" -f /tmp/joao   -C "joao@laptop"

af key add marina --file /tmp/marina.pub
af key add rui    --file /tmp/rui.pub
af key add joao   --file /tmp/joao.pub

af key list marina           # 1 credencial, status=ativa
```

**Edge case — tipo não suportado:**

```bash
af key add marina --string "ssh-dss AAAA..."
# Esperado: ERRO  ... tipo de chave nao suportado
```

**Edge case — duplicada:**

```bash
af key add marina --file /tmp/marina.pub
# Esperado: ERRO  ... chave ja cadastrada
```

### UC-3 — Gerenciar grupo de admin

```bash
af group create sysadmins
af group add-member sysadmins marina
af group add-member sysadmins rui

af group create dba
af group add-member dba joao
af group add-member dba marina    # marina em 2 grupos

af group list
af admin show marina              # mostra "Grupos: sysadmins, dba"
```

**Edge case — idempotência:**

```bash
af group add-member sysadmins marina
# Esperado: OK   (operacao registrada como sucesso, sem duplicar)
```

**Edge case — grupo com permissão associada:**

```bash
af group create temp
af group delete temp              # OK (sem permissao, deleta)
```

### UC-4 — Cadastrar servidor

Capture as host_keys (todas iguais nos 3 containers porque foram geradas no build):

```bash
HK=$(ssh-keyscan -t ed25519 -p 2201 127.0.0.1 2>/dev/null | grep ssh-ed25519 | awk '{print $2" "$3}')
echo "$HK" | head -c 80; echo

af server add web-01 --ip 127.0.0.1 --porta 2201 --host-key "$HK"
af server add web-02 --ip 127.0.0.1 --porta 2202 --host-key "$HK"
af server add db-03  --ip 127.0.0.1 --porta 2203 --host-key "$HK"

af server list                   # tabela: 3 servidores, 0 chaves
af server show web-01            # detalha host_key e chaves_instaladas (vazio)
```

### UC-5 — Gerenciar grupo de servidor

```bash
af server-group create producao
af server-group add-member producao web-01
af server-group add-member producao web-02

af server-group create bancos
af server-group add-member bancos db-03

af server-group list
```

### UC-6 — Conceder / revogar acesso

```bash
af grant sysadmins producao --nivel sudo
af grant dba       bancos    --nivel sudo
af grant sysadmins bancos    --nivel shell    # sysadmins acesso shell em bancos

cat /tmp/lab-state/permissions.json
```

Esperado: 3 permissões.

**Edge case — atualizar nível (não duplica):**

```bash
af grant sysadmins producao --nivel shell
cat /tmp/lab-state/permissions.json | python3 -c "import json,sys;d=json.load(sys.stdin);print(len(d['permissoes']))"
# Esperado: 3 (mesma quantidade, nivel atualizado)
af grant sysadmins producao --nivel sudo     # restaura para sudo
```

**Edge case — revogar inexistente:**

```bash
af revoke fantasma producao
# Esperado: ERRO  ... permissao nao existe
```

### UC-7 — Preview

```bash
af preview
```

Esperado: lista subações agrupadas por servidor com `+` (verde, adicionar) e `-` (vermelho, remover):

```
i  6 subacoes em 3 servidores

db-03
  + adicionar_chave    joao:SHA256:...     sudo
  + adicionar_chave    marina:SHA256:...   shell

producao (web-01, web-02)
  + adicionar_chave    marina:SHA256:...   sudo
  + adicionar_chave    rui:SHA256:...      sudo
  ...
```

> Note: marina aparece em `db-03` com nível `shell` (via grupo `sysadmins → bancos`), mas no `producao` ela está com `sudo` (`sysadmins → producao --nivel sudo`).

**Edge case — preview é read-only:**

```bash
af history list -n 1
# A entrada mais recente NAO eh preview (nao gera operacao mutadora)
```

### UC-8 — Apply (real, via SSH)

```bash
af apply --yes
```

Esperado: cada subação executada via SSH real, todas com status `sucesso`.

```
  OK  db-03    adicionar_chave    joao:SHA256:...
  OK  db-03    adicionar_chave    marina:SHA256:...
  ...
operacao: OP-001x
status: SUCESSO
sucessos: 7
falhas: 0
```

**Validar dentro dos containers:**

```bash
echo "--- web-01: marina ---"
docker exec adminforge-web-01 sudo cat /home/marina/.ssh/authorized_keys
echo "--- web-01: sudoers da marina ---"
docker exec adminforge-web-01 sudo cat /etc/sudoers.d/adminforge-marina
echo "--- visudo -c (sintaxe valida) ---"
docker exec adminforge-web-01 sudo visudo -c
echo "--- conta unix marina ---"
docker exec adminforge-web-01 id marina
```

Esperado:
- `authorized_keys` tem o bloco `# BEGIN adminforge: marina:SHA256:...` ... `# END adminforge: marina:SHA256:...` envolvendo a chave
- sudoers `marina ALL=(ALL) NOPASSWD:ALL`
- `visudo -c` parsed OK
- `id marina` retorna UID/GID

**Smoke test — marina loga e usa sudo:**

```bash
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i /tmp/marina -p 2201 marina@127.0.0.1 'whoami; sudo whoami'
# Esperado: marina / root
```

**Idempotência:**

```bash
af apply --yes
# Esperado: OK  nada a fazer — estado sincronizado
```

### UC-9 — Histórico

```bash
af history list                     # ultimas 50, 1 linha por operacao
af history list -n 5                # so as 5 mais recentes
af history show OP-0001             # detalhes + cadeia de hash
af history failed                   # so falhas e parciais (deveria estar vazio)
af history verify
# Esperado: OK  cadeia integra (ultimo hash: ...)
```

**Edge case — adulteração detectada:**

```bash
HIST=/tmp/lab-state/history.jsonl
sed -i '1s/sucesso/falha/' "$HIST"
af history verify
# Esperado: ERRO  cadeia quebrada: hash divergente em OP-0001
sed -i '1s/falha/sucesso/' "$HIST"
af history verify       # volta a OK
```

### UC-10 — Auditar usuários e serviços

```bash
af audit server web-01
```

Esperado: lista 3 usuários (`adminforge`, `marina`, `rui`) com UID/shell + serviços rodando (`ssh`, etc.).

```bash
af audit server web-01 --user marina    # destaca marina em amarelo
af audit server web-01 --user fantasma  # nao destaca; nao alerta
```

---

## PARTE C — Cenários de robustez

### C.1 Briga com edição manual (markers preservam linha pessoal)

```bash
docker exec --user marina adminforge-web-01 \
    bash -c 'echo "ssh-ed25519 AAAA-FakeManualKey marina@home" >> ~/.ssh/authorized_keys'

docker exec --user marina adminforge-web-01 cat /home/marina/.ssh/authorized_keys
# Esperado: bloco AdminForge + linha manual da marina
```

Revogue a chave gerenciada:

```bash
FP=$(af key list marina | tail -1 | awk '{print $1}')
af key revoke "$FP"
af apply --yes

docker exec --user marina adminforge-web-01 cat /home/marina/.ssh/authorized_keys
# Esperado: APENAS a linha manual sobra; o bloco com markers desapareceu
```

> Markers funcionam. AdminForge respeita o que o usuário coloca à mão.

### C.2 Desabilitar admin

```bash
af admin disable rui --yes

af preview              # 2 subacoes 'remover_chave' para rui
af apply --yes

docker exec adminforge-web-01 sudo cat /home/rui/.ssh/authorized_keys
# Esperado: arquivo vazio ou so newlines

docker exec adminforge-web-01 ls /etc/sudoers.d/ | grep rui
# Esperado: vazio (sudoers do rui foi removido)
```

### C.3 Falha parcial (servidor offline)

```bash
docker stop adminforge-db-03

af admin add carla --nome "Carla" --email c@e.com
ssh-keygen -t ed25519 -N "" -f /tmp/carla -C "carla@laptop"
af key add carla --file /tmp/carla.pub
af group add-member sysadmins carla

af apply --yes
```

Esperado:
- `web-01` e `web-02`: OK
- `db-03`: ERRO `ssh: connect ... timed out`
- Status final: `SUCESSO_PARCIAL`, sucessos: 2, falhas: 1

```bash
docker start adminforge-db-03
sleep 3
af apply --yes
# Esperado: SO a subacao que faltou em db-03 entra no delta
```

### C.4 Validações

```bash
af admin add "Inv@lid" --nome X --email x@e.com    # username invalido
af admin add valido --nome X --email "ruim"        # email invalido
af group delete sysadmins                          # bloqueia: tem permissao associada
af revoke fantasma producao                        # permissao nao existe
```

Cada um deve dar **ERRO** com mensagem clara.

### C.5 Lockfile concorrente

Em **dois terminais simultaneamente**:

```bash
# terminal 1
af apply --yes

# terminal 2 (no mesmo momento)
af admin add teste --nome T --email t@e.com
```

Esperado no terminal 2: `outra instância do AdminForge está em execução` (exit 3).

---

## PARTE D — Estado em disco (JSON)

```bash
ls -la /tmp/lab-state/
cat /tmp/lab-state/admins/marina.json
cat /tmp/lab-state/servers/web-01.json
cat /tmp/lab-state/permissions.json
cat /tmp/lab-state/known_hosts
head -3 /tmp/lab-state/history.jsonl
```

Esperado:
- Diretório `0700`, arquivos `0600`
- JSON formatado e legível
- `known_hosts` no formato OpenSSH padrão
- `history.jsonl`: 1 linha por operação, com `hash` e `hash_anterior`

---

## PARTE E — (Opcional) Auditoria read-only em servidor real

Se você tem acesso SSH a um servidor (qualquer um — pode ser compartilhado, desde que respeite a política do lugar), dá pra exercitar o `audit server` contra ele. **Apenas operações read-only** — não rode `apply` em servidor que não é seu.

Substitua os placeholders pelos valores do seu host:

```bash
export ADMINFORGE_STATE=/tmp/audit-real
export ADMINFORGE_SSH_USER=<seu-usuario-no-servidor>
export ADMINFORGE_SSH_KEY=<caminho-da-sua-chave-privada>
export ADMINFORGE_SUPERADMIN=<seu-username-local>
mkdir -p /tmp/audit-real

af server add <apelido> --ip <IP-DO-SERVIDOR> --auto
# Confira o fingerprint exibido contra um canal seguro
# (ex: ssh-keygen -lf ~/.ssh/known_hosts -F <hostname>)

af audit server <apelido>                       # lista usuarios e servicos
af audit server <apelido> --user <username>     # destaca + alerta se sem servico
af audit server <apelido> --service <nome>      # destaca servicos relacionados

af history list
af history verify
```

O `audit` é estritamente leitura: roda `getent passwd` e `systemctl list-units` via SSH. Não escreve nada no servidor remoto. O único efeito local é uma entrada no `state/history.jsonl`.

Limpeza:

```bash
rm -rf /tmp/audit-real
unset ADMINFORGE_STATE ADMINFORGE_SSH_USER ADMINFORGE_SSH_KEY ADMINFORGE_SUPERADMIN
```

---

## PARTE F — Limpeza do lab Docker

```bash
docker compose -f infra/testlab/docker-compose.yml --env-file infra/testlab/.env down -v

rm -rf /tmp/lab-state
rm -f /tmp/marina /tmp/marina.pub /tmp/rui /tmp/rui.pub /tmp/joao /tmp/joao.pub /tmp/carla /tmp/carla.pub /tmp/adminforge_id
```

---

## Checklist final (cole o que verificou)

| # | Cenário | OK? | Observação |
|---|---------|-----|------------|
| UC-1 | Cadastrar admin (3 admins) + duplicata + formato | | |
| UC-2 | Cadastrar/revogar chave + tipo invalido + duplicada | | |
| UC-3 | Gerenciar grupo de admin + idempotencia | | |
| UC-4 | Cadastrar servidor (3 servidores) | | |
| UC-5 | Gerenciar grupo de servidor | | |
| UC-6 | grant/revoke + atualizar nivel + revoke inexistente | | |
| UC-7 | preview lista delta agrupado | | |
| UC-8 | apply real via SSH; markers e sudoers nos containers | | |
| UC-9 | history list/show/verify + adulteracao detectada | | |
| UC-10 | audit server + filtros --user/--service | | |
| C.1 | Markers preservam edicao manual | | |
| C.2 | Desabilitar admin remove dos servidores | | |
| C.3 | Falha parcial; retentativa pega so o que faltou | | |
| C.4 | Validacoes de formato e regras de negocio | | |
| C.5 | Lockfile bloqueia segunda instancia | | |
| D | JSON de estado bem-formado, permissoes 0600 | | |
| E | (Opcional) audit em servidor real, read-only | | |

Se qualquer linha falhar, abra issue com a saída completa.
