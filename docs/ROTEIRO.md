# Roteiro completo de teste

Validação manual de **todo** o sistema AdminForge: 10 casos de uso + edge cases + (opcional) auditoria em servidor real.

> **Tempo estimado:** 15-20 minutos
> **Risco:** zero (lab isolado em containers); a parte opcional contra servidor real é read-only.
> **Pré-requisito mínimo:** Python 3.11+ e cliente OpenSSH. Para o lab Docker: `docker compose v2`.

> **Sobre os nomes nos exemplos.** `alice`, `bob`, `charlie`, `dave` são placeholders convencionais — substitua pelos nomes reais dos administradores do seu CPD. `web-01`, `db-03`, `producao`, `sysadmins` idem (substitua pelos seus hostnames e grupos). `<IP-DO-SERVIDOR>` e similares entre `<...>` são placeholders explícitos: troque antes de executar.

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
export ADMINFORGE_SUPERADMIN=$USER       # ou substitua por <seu-username>

rm -rf /tmp/lab-state && mkdir -p /tmp/lab-state
```

---

## PARTE B — Os 10 casos de uso (10 min)

### UC-1 — Cadastrar admin

```bash
af admin add alice --nome "Alice Silva" --email alice@empresa.com
af admin add bob    --nome "Bob Costa"    --email bob@empresa.com
af admin add charlie   --nome "Charlie Pereira" --email charlie@empresa.com
```

Validações:

```bash
af admin list                # tabela: 3 admins, status=ativo
af admin show alice         # detalhes + 0 credenciais + 0 grupos
```

**Edge case — duplicata:**

```bash
af admin add alice --nome X --email x@e.com
# Esperado: ERRO  ... username 'alice' ja existe
```

**Edge case — formato:**

```bash
af admin add "Alice!" --nome X --email x@e.com
# Esperado: ERRO  ... username invalido
af admin add valid --nome X --email "nao-e-email"
# Esperado: ERRO  ... email invalido
```

### UC-2 — Cadastrar / revogar chave SSH

```bash
ssh-keygen -t ed25519 -N "" -f /tmp/alice -C "alice@laptop"
ssh-keygen -t ed25519 -N "" -f /tmp/bob    -C "bob@laptop"
ssh-keygen -t ed25519 -N "" -f /tmp/charlie   -C "charlie@laptop"

af key add alice --file /tmp/alice.pub
af key add bob    --file /tmp/bob.pub
af key add charlie   --file /tmp/charlie.pub

af key list alice           # 1 credencial, status=ativa
```

**Edge case — tipo não suportado:**

```bash
af key add alice --string "ssh-dss AAAA..."
# Esperado: ERRO  ... tipo de chave nao suportado
```

**Edge case — duplicada:**

```bash
af key add alice --file /tmp/alice.pub
# Esperado: ERRO  ... chave ja cadastrada
```

### UC-3 — Gerenciar grupo de admin

```bash
af group create sysadmins
af group add-member sysadmins alice
af group add-member sysadmins bob

af group create dba
af group add-member dba charlie
af group add-member dba alice    # alice em 2 grupos

af group list
af admin show alice              # mostra "Grupos: sysadmins, dba"
```

**Edge case — idempotência:**

```bash
af group add-member sysadmins alice
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
  + adicionar_chave    charlie:SHA256:...     sudo
  + adicionar_chave    alice:SHA256:...   shell

producao (web-01, web-02)
  + adicionar_chave    alice:SHA256:...   sudo
  + adicionar_chave    bob:SHA256:...      sudo
  ...
```

> Note: alice aparece em `db-03` com nível `shell` (via grupo `sysadmins → bancos`), mas no `producao` ela está com `sudo` (`sysadmins → producao --nivel sudo`).

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
  OK  db-03    adicionar_chave    charlie:SHA256:...
  OK  db-03    adicionar_chave    alice:SHA256:...
  ...
operacao: OP-001x
status: SUCESSO
sucessos: 7
falhas: 0
```

**Validar dentro dos containers:**

```bash
echo "--- web-01: alice ---"
docker exec adminforge-web-01 sudo cat /home/alice/.ssh/authorized_keys
echo "--- web-01: sudoers da alice ---"
docker exec adminforge-web-01 sudo cat /etc/sudoers.d/adminforge-alice
echo "--- visudo -c (sintaxe valida) ---"
docker exec adminforge-web-01 sudo visudo -c
echo "--- conta unix alice ---"
docker exec adminforge-web-01 id alice
```

Esperado:
- `authorized_keys` tem o bloco `# BEGIN adminforge: alice:SHA256:...` ... `# END adminforge: alice:SHA256:...` envolvendo a chave
- sudoers `alice ALL=(ALL) NOPASSWD:ALL`
- `visudo -c` parsed OK
- `id alice` retorna UID/GID

**Smoke test — alice loga e usa sudo:**

```bash
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i /tmp/alice -p 2201 alice@127.0.0.1 'whoami; sudo whoami'
# Esperado: alice / root
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

Esperado: lista 3 usuários (`adminforge`, `alice`, `bob`) com UID/shell + serviços rodando (`ssh`, etc.).

```bash
af audit server web-01 --user alice    # destaca alice em amarelo
af audit server web-01 --user fantasma  # nao destaca; nao alerta
```

---

## PARTE C — Cenários de robustez

### C.1 Briga com edição manual (markers preservam linha pessoal)

```bash
docker exec --user alice adminforge-web-01 \
    bash -c 'echo "ssh-ed25519 AAAA-FakeManualKey alice@home" >> ~/.ssh/authorized_keys'

docker exec --user alice adminforge-web-01 cat /home/alice/.ssh/authorized_keys
# Esperado: bloco AdminForge + linha manual da alice
```

Revogue a chave gerenciada:

```bash
FP=$(af key list alice | tail -1 | awk '{print $1}')
af key revoke "$FP"
af apply --yes

docker exec --user alice adminforge-web-01 cat /home/alice/.ssh/authorized_keys
# Esperado: APENAS a linha manual sobra; o bloco com markers desapareceu
```

> Markers funcionam. AdminForge respeita o que o usuário coloca à mão.

### C.2 Desabilitar admin

```bash
af admin disable bob --yes

af preview              # 2 subacoes 'remover_chave' para bob
af apply --yes

docker exec adminforge-web-01 sudo cat /home/bob/.ssh/authorized_keys
# Esperado: arquivo vazio ou so newlines

docker exec adminforge-web-01 ls /etc/sudoers.d/ | grep bob
# Esperado: vazio (sudoers do bob foi removido)
```

### C.3 Falha parcial (servidor offline)

```bash
docker stop adminforge-db-03

af admin add dave --nome "Dave" --email c@e.com
ssh-keygen -t ed25519 -N "" -f /tmp/dave -C "dave@laptop"
af key add dave --file /tmp/dave.pub
af group add-member sysadmins dave

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
cat /tmp/lab-state/admins/alice.json
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

## PARTE E — Validação contra servidor real (que você controla)

Aqui você roda o **fluxo completo** (incluindo `apply`) contra uma máquina real de verdade — não containers. Use uma **VM/VPS/host que você possui** (DigitalOcean droplet, Proxmox, AWS EC2, Raspberry Pi na sua rede, etc.).

> **Pré-requisito de cidadania:** o `apply` cria contas Unix, escreve em `/etc/sudoers.d/` e modifica `~/<user>/.ssh/authorized_keys` de outros usuários. Não rode contra servidor que não é seu.

### E.1 Bootstrap único do usuário `adminforge` no servidor

O AdminForge precisa de um usuário Linux com sudo `NOPASSWD` e a chave dele instalada antes do primeiro `apply`. Faça **uma vez** por servidor:

**Opção 1 — VM nova com cloud-init.** Inclua no `user-data` ao provisionar:

```yaml
#cloud-config
users:
  - name: adminforge
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - ssh-ed25519 AAAA... adminforge@operador
```

**Opção 2 — Servidor existente, manualmente:**

```bash
# (no seu laptop) gere a chave do AdminForge
ssh-keygen -t ed25519 -N "" -f ~/.ssh/adminforge_id -C "adminforge@operador"

# (no servidor, como root ou via sudo) crie o usuario e instale a chave
ssh root@<seu-servidor> bash <<EOF
useradd -m -s /bin/bash adminforge
echo 'adminforge ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/adminforge
chmod 0440 /etc/sudoers.d/adminforge
visudo -c
install -d -m 700 -o adminforge -g adminforge /home/adminforge/.ssh
echo "$(cat ~/.ssh/adminforge_id.pub)" \
    | install -m 600 -o adminforge -g adminforge /dev/stdin /home/adminforge/.ssh/authorized_keys
EOF
```

Verifique antes de continuar:

```bash
ssh -i ~/.ssh/adminforge_id -o BatchMode=yes adminforge@<seu-servidor> 'whoami; sudo -n whoami'
# Esperado: adminforge / root
```

### E.2 Configure o AdminForge para apontar pra esse servidor

```bash
export ADMINFORGE_STATE=/tmp/state-real
export ADMINFORGE_SSH_KEY=~/.ssh/adminforge_id
export ADMINFORGE_SSH_USER=adminforge
export ADMINFORGE_SUPERADMIN=$USER
mkdir -p /tmp/state-real
```

### E.3 Cadastre o servidor

```bash
af server add prod-01 --ip <IP-DO-SERVIDOR> --auto
# Confira o fingerprint contra um canal seguro
```

### E.4 Rode o fluxo do PARTE B contra esse servidor

Agora repita os passos UC-1 a UC-9 da [PARTE B](#parte-b--os-10-casos-de-uso-10-min), trocando os apelidos `web-01/web-02/db-03` por `prod-01` e adicionando admins/grupos como achar útil.

Exemplo enxuto:

```bash
af admin add teste --nome "Conta Teste" --email teste@operador.local
ssh-keygen -t ed25519 -N "" -f /tmp/teste_key -C "teste@laptop"
af key add teste --file /tmp/teste_key.pub
af group create operadores
af group add-member operadores teste

af server-group create real
af server-group add-member real prod-01

af grant operadores real --nivel sudo
af preview
af apply --yes
```

Validação direta no servidor:

```bash
ssh -i ~/.ssh/adminforge_id adminforge@<seu-servidor> 'sudo cat /home/teste/.ssh/authorized_keys'
ssh -i ~/.ssh/adminforge_id adminforge@<seu-servidor> 'sudo cat /etc/sudoers.d/adminforge-teste'
ssh -i ~/.ssh/adminforge_id adminforge@<seu-servidor> 'sudo visudo -c'

# Smoke test: a conta teste loga e usa sudo?
ssh -i /tmp/teste_key teste@<seu-servidor> 'whoami; sudo whoami'
# Esperado: teste / root
```

Revogação e limpeza:

```bash
FP=$(af key list teste | tail -1 | awk '{print $1}')
af key revoke "$FP"
af apply --yes

# Verifique que sumiu
ssh -i ~/.ssh/adminforge_id adminforge@<seu-servidor> 'sudo cat /home/teste/.ssh/authorized_keys'
# Esperado: vazio ou sem o bloco do AdminForge

af history verify
```

Limpeza local:

```bash
rm -rf /tmp/state-real /tmp/teste_key /tmp/teste_key.pub
unset ADMINFORGE_STATE ADMINFORGE_SSH_USER ADMINFORGE_SSH_KEY ADMINFORGE_SUPERADMIN
```

### E.5 (Sub-opção) Audit em servidor compartilhado (read-only)

Tem servidor onde você só consegue logar como você, sem direito a `apply`? Dá pra exercitar o `audit server`, que é estritamente leitura (`getent passwd` + `systemctl list-units` via SSH):

```bash
export ADMINFORGE_STATE=/tmp/audit-only
export ADMINFORGE_SSH_USER=<seu-usuario-no-servidor>
export ADMINFORGE_SSH_KEY=<sua-chave-privada>
export ADMINFORGE_SUPERADMIN=$USER
mkdir -p /tmp/audit-only

af server add host --ip <IP-DO-SERVIDOR> --auto
af audit server host
af audit server host --user <conta-tecnica-suspeita>
af history verify
```

Não rode `apply` aqui. O `audit` não escreve nada no servidor remoto.

---

## PARTE F — Limpeza do lab Docker

```bash
docker compose -f infra/testlab/docker-compose.yml --env-file infra/testlab/.env down -v

rm -rf /tmp/lab-state
rm -f /tmp/alice /tmp/alice.pub /tmp/bob /tmp/bob.pub /tmp/charlie /tmp/charlie.pub /tmp/dave /tmp/dave.pub /tmp/adminforge_id
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
| E | Fluxo completo contra servidor real (que voce controla) | | |
| E.5 | (Sub-opcao) audit read-only em servidor compartilhado | | |

Se qualquer linha falhar, abra issue com a saída completa.
