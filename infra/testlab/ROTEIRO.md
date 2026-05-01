# Roteiro de teste — lab Docker

Roteiro passo a passo para validar o AdminForge end-to-end contra 3 containers Debian. Tudo isolado: sem afetar produção, fácil de derrubar.

> **Tempo estimado:** 10 minutos.
> **Nível:** sequencial — execute na ordem.
> **Onde rodar:** raiz do repositório (`/mnt/win_ssd/adminForge`).

---

## 0. Pré-requisitos

```bash
docker --version          # >= 24
docker compose version    # v2 ou superior
python3 --version         # >= 3.11
```

Instalar o AdminForge em modo editável:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## 1. Preparar o lab

### 1.1 Gerar chave do AdminForge

```bash
mkdir -p infra/testlab/keys
ssh-keygen -t ed25519 -N "" -f infra/testlab/keys/adminforge_id -C "adminforge@testlab"

# A chave precisa de permissão 0600 num filesystem que respeite POSIX:
cp infra/testlab/keys/adminforge_id /tmp/adminforge_id
cp infra/testlab/keys/adminforge_id.pub /tmp/adminforge_id.pub
chmod 600 /tmp/adminforge_id
```

### 1.2 Configurar o `.env` do lab

```bash
cat > infra/testlab/.env <<EOF
ADMINFORGE_PUBKEY=$(cat infra/testlab/keys/adminforge_id.pub)
EOF
```

### 1.3 Subir os containers

```bash
docker compose -f infra/testlab/docker-compose.yml --env-file infra/testlab/.env up -d --build
sleep 2
docker compose -f infra/testlab/docker-compose.yml ps
```

**Esperado:** `adminforge-web-01`, `adminforge-web-02`, `adminforge-db-03` em `Up`, expostos em `2201`, `2202`, `2203`.

### 1.4 Validar SSH inicial

```bash
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i /tmp/adminforge_id -p 2201 adminforge@127.0.0.1 'whoami; hostname'
```

**Esperado:** `adminforge` / `web-01`. Repita para `2202` (web-02) e `2203` (db-03).

### 1.5 Configurar variáveis de ambiente

```bash
export ADMINFORGE_STATE=/tmp/lab-state
export ADMINFORGE_SSH_KEY=/tmp/adminforge_id
export ADMINFORGE_SSH_USER=adminforge
export ADMINFORGE_SUPERADMIN=cristhian

rm -rf /tmp/lab-state && mkdir -p /tmp/lab-state
```

---

## 2. Cenário A — Caminho feliz

### 2.1 Cadastrar 2 admins com suas chaves

```bash
ssh-keygen -t ed25519 -N "" -f /tmp/marina -C "marina@laptop"
ssh-keygen -t ed25519 -N "" -f /tmp/rui    -C "rui@laptop"

adminforge admin add marina --nome "Marina Silva" --email marina@empresa.com
adminforge admin add rui    --nome "Rui Costa"     --email rui@empresa.com
adminforge key add marina --file /tmp/marina.pub
adminforge key add rui    --file /tmp/rui.pub
```

**Esperado:** 4 linhas `OK ... (OP-000n)`.

```bash
adminforge admin list
adminforge admin show marina
```

**Esperado:** marina e rui com status `ativo`, cada um com 1 credencial `ativa`.

### 2.2 Cadastrar grupo e servidores

```bash
adminforge group create sysadmins
adminforge group add-member sysadmins marina
adminforge group add-member sysadmins rui

HK=$(ssh-keyscan -t ed25519 -p 2201 127.0.0.1 2>/dev/null | grep ssh-ed25519 | awk '{print $2" "$3}')

adminforge server add web-01 --ip 127.0.0.1 --porta 2201 --host-key "$HK"
adminforge server add web-02 --ip 127.0.0.1 --porta 2202 --host-key "$HK"
adminforge server add db-03  --ip 127.0.0.1 --porta 2203 --host-key "$HK"

adminforge server-group create producao
adminforge server-group add-member producao web-01
adminforge server-group add-member producao web-02
adminforge server-group add-member producao db-03
```

> Os 3 containers compartilham a mesma host_key (`ssh-keygen -A` rodou no build do Dockerfile, não no boot). Em produção, cada servidor teria a sua.

### 2.3 Conceder acesso e ver prévia

```bash
adminforge grant sysadmins producao --nivel sudo
adminforge preview
```

**Esperado:**

```
i  6 subacoes em 3 servidores

db-03
  + adicionar_chave    marina:SHA256:...  sudo
  + adicionar_chave    rui:SHA256:...     sudo
web-01
  + adicionar_chave    marina:SHA256:...  sudo
  + adicionar_chave    rui:SHA256:...     sudo
web-02
  + adicionar_chave    marina:SHA256:...  sudo
  + adicionar_chave    rui:SHA256:...     sudo
```

### 2.4 Aplicar

```bash
adminforge apply --yes
```

**Esperado:** 6 linhas `OK`, `status: SUCESSO`, `sucessos: 6`, `falhas: 0`.

---

## 3. Cenário B — Verificar diretamente nos containers

### 3.1 `authorized_keys` com markers

```bash
docker exec adminforge-web-01 sudo cat /home/marina/.ssh/authorized_keys
```

**Esperado:**

```
# BEGIN adminforge: marina:SHA256:...
ssh-ed25519 AAAA... marina@laptop
# END adminforge: marina:SHA256:...
```

### 3.2 Conta Unix criada

```bash
docker exec adminforge-web-01 id marina
```

**Esperado:** `uid=1001(marina) gid=1001(marina) groups=1001(marina)`.

### 3.3 Sudoers válido

```bash
docker exec adminforge-web-01 sudo cat /etc/sudoers.d/adminforge-marina
docker exec adminforge-web-01 sudo visudo -c
```

**Esperado:** linha `marina ALL=(ALL) NOPASSWD:ALL` e `parsed OK` para todos os arquivos.

### 3.4 Marina loga e usa sudo

```bash
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i /tmp/marina -p 2201 marina@127.0.0.1 'whoami; sudo whoami'
```

**Esperado:** `marina` / `root`.

---

## 4. Cenário C — Idempotência

```bash
adminforge apply --yes
```

**Esperado:** `OK nada a fazer — estado sincronizado`. Nenhuma conexão SSH é aberta.

---

## 5. Cenário D — Briga com edição manual (markers funcionam)

### 5.1 Marina adiciona chave dela manualmente, fora do AdminForge

```bash
docker exec --user marina adminforge-web-01 \
    bash -c 'echo "ssh-ed25519 AAAA... marina-pessoal@home" >> ~/.ssh/authorized_keys'

docker exec --user marina adminforge-web-01 cat /home/marina/.ssh/authorized_keys
```

**Esperado:** o bloco do AdminForge + a linha pessoal.

### 5.2 AdminForge revoga a chave gerenciada

```bash
FP=$(adminforge key list marina | tail -1 | awk '{print $1}')
adminforge key revoke "$FP"
adminforge apply --yes
```

**Esperado:** 3 linhas `OK remover_chave`.

### 5.3 Conferir que **só** o bloco gerenciado sumiu

```bash
docker exec --user marina adminforge-web-01 cat /home/marina/.ssh/authorized_keys
```

**Esperado:** **apenas** `ssh-ed25519 AAAA... marina-pessoal@home`. O bloco com markers desapareceu.

```bash
docker exec adminforge-web-01 ls /etc/sudoers.d/
```

**Esperado:** `adminforge-rui` continua, `adminforge-marina` foi removido.

---

## 6. Cenário E — Desabilitar admin

```bash
adminforge admin disable rui --yes
adminforge preview
```

**Esperado:** 3 subações `remover_chave` para rui (uma por servidor).

```bash
adminforge apply --yes
docker exec adminforge-web-01 sudo cat /home/rui/.ssh/authorized_keys
```

**Esperado:** arquivo vazio (ou só com newlines).

```bash
docker exec adminforge-web-01 ls /etc/sudoers.d/
```

**Esperado:** `adminforge-rui` foi removido. Restou apenas `adminforge` (do bootstrap) e `README`.

---

## 7. Cenário F — Histórico

### 7.1 Listar e detalhar

```bash
adminforge history list
adminforge history show OP-0019
```

**Esperado:** tabela cronológica com as ~25 operações; `show` exibe metadados + cadeia de hashes + lista de subações.

### 7.2 Verificar cadeia íntegra

```bash
adminforge history verify
```

**Esperado:** `OK cadeia integra (ultimo hash: ...)`.

### 7.3 Detectar adulteração retroativa

Edite manualmente o histórico para simular um ataque:

```bash
# Pega a primeira linha e troca 'sucesso' por 'falha' nela
HIST=$ADMINFORGE_STATE/history.jsonl
sed -i '1s/sucesso/falha/' "$HIST"
adminforge history verify
```

**Esperado:** sai com `ERRO cadeia quebrada: hash divergente em OP-0001` (ou o ID da entrada adulterada).

Restaurar:

```bash
sed -i '1s/falha/sucesso/' "$HIST"
adminforge history verify   # volta a OK
```

---

## 8. Cenário G — Auditoria operacional (UC-10)

```bash
adminforge audit server web-01
```

**Esperado:** lista usuários (`adminforge`, `marina`, `rui`) e serviços rodando (`sshd` no mínimo).

```bash
adminforge audit server web-01 --user marina
adminforge audit server web-01 --user kreutz   # usuario que nao existe
```

**Esperado:** primeiro destaca `marina` em amarelo; segundo lista normalmente sem destaque.

---

## 9. Cenário H — Falha parcial (servidor offline)

```bash
docker stop adminforge-db-03

# Restaurar marina para gerar diff
adminforge admin add marina2 --nome "Marina Dois" --email m2@e.com
ssh-keygen -t ed25519 -N "" -f /tmp/marina2 -C "marina2@laptop"
adminforge key add marina2 --file /tmp/marina2.pub
adminforge group add-member sysadmins marina2

adminforge apply --yes
```

**Esperado:** 2 OKs (web-01, web-02), 1 ERRO em db-03 com mensagem `ssh: ...connect... timeout` ou similar. Status final `SUCESSO_PARCIAL`. `sucessos: 2`, `falhas: 1`.

```bash
docker start adminforge-db-03
sleep 2
adminforge apply --yes
```

**Esperado:** apenas a subação que faltou (db-03 ↦ marina2) entra no delta. Status `SUCESSO`.

---

## 10. Cenário I — Validações

### 10.1 Username inválido

```bash
adminforge admin add "Inv@lid" --nome "X" --email x@e.com
```

**Esperado:** `ERRO admin add Inv@lid` com mensagem sobre formato.

### 10.2 Chave duplicada

```bash
adminforge key add marina --file /tmp/marina.pub   # ja foi cadastrada
```

**Esperado:** `ERRO ... chave ja cadastrada`.

### 10.3 Excluir grupo com permissão associada

```bash
adminforge group delete sysadmins
```

**Esperado:** `ERRO ... grupo 'sysadmins' tem permissoes associadas; revogue antes`.

### 10.4 Revogar permissão inexistente

```bash
adminforge revoke fantasma producao
```

**Esperado:** `ERRO ... permissao nao existe`.

### 10.5 Lockfile ativo

Em **dois terminais** simultaneamente:

```bash
# terminal 1
adminforge apply --yes

# terminal 2 (no mesmo instante)
adminforge admin add teste --nome "T" --email t@e.com
```

**Esperado:** terminal 2 falha com `outra instância do AdminForge está em execução`.

---

## 11. Limpeza

```bash
docker compose -f infra/testlab/docker-compose.yml --env-file infra/testlab/.env down
rm -rf /tmp/lab-state
rm -f /tmp/adminforge_id /tmp/adminforge_id.pub /tmp/marina /tmp/marina.pub /tmp/rui /tmp/rui.pub /tmp/marina2 /tmp/marina2.pub
```

---

## Tabela de checagem rápida

| # | Cenário | Comando | Resultado esperado |
|---|---------|---------|--------------------|
| A | Caminho feliz | `apply --yes` | 6 OK, status SUCESSO |
| B | Markers no `authorized_keys` | `docker exec ... cat` | Bloco `# BEGIN/END adminforge:` |
| B | Sudoers válido | `visudo -c` | parsed OK |
| B | Login do admin | `ssh marina@... sudo whoami` | `root` |
| C | Idempotência | `apply --yes` | nada a fazer |
| D | Edição manual preservada | revoke + apply + cat | só linha manual sobra |
| E | Desabilitar admin | `admin disable + apply` | chaves removidas |
| F | Histórico íntegro | `history verify` | cadeia integra |
| F | Adulteração detectada | edita JSONL + verify | cadeia quebrada em OP-XXXX |
| G | Audit operacional | `audit server` | lista users + services |
| H | Falha parcial | `docker stop + apply` | SUCESSO_PARCIAL, falha entra no delta |
| I | Validações | comandos inválidos | mensagens claras de erro |
| I | Lockfile | apply + cmd paralelo | LockOcupado |

Se qualquer linha falhar, abrir um issue com a saída completa do comando.
