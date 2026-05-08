# Cookbook por caso de uso

Cada caso de uso da modelagem v1, com gatilho, fluxo e exemplo copiável.

> **Convenção.** Operações que mudam o estado **desejado** não tocam servidor nenhum — tocam apenas os JSONs em `state/`. As mudanças vão para os servidores no próximo `apply`. Exceção: `audit server` é read-only direto no servidor.

---

## UC-1 — Cadastrar usuário

```bash
adminforge user add --username <username> --name "Nome Completo" --email pessoa@empresa.com
```

- `username` deve casar com `^[a-z_][a-z0-9_-]{0,30}$` (regra Linux).
- E-mail validado por regex simples.
- Cadastro duplicado falha com mensagem clara.

```bash
adminforge user list                          # tabela
adminforge user show --username alice         # detalha + chaves + grupos
adminforge user disable --username alice      # status=inativo, chaves revogadas
```

---

## UC-2 — Cadastrar / revogar chave SSH

```bash
adminforge user key add --username alice --file ~/.ssh/alice.pub
adminforge user key add --username alice --string "ssh-ed25519 AAAA... alice@laptop"
```

Aceita `ssh-ed25519`, `ssh-rsa`, `ecdsa-sha2-nistp{256,384,521}`. Fingerprint é SHA256 da chave.

Revogar:

```bash
adminforge user key list --username alice
adminforge user key revoke --fingerprint SHA256:abc123...
```

A revogação muda o status para `revogada`. A remoção física do `authorized_keys` acontece no próximo `apply`.

---

## UC-3 — Gerenciar grupo de usuários

```bash
adminforge user-group create --name sysadmins
adminforge user-group add-member --group sysadmins --username alice bob carla
adminforge user-group remove-member --group sysadmins --username bob
adminforge user-group delete --name sysadmins        # bloqueia se houver permissoes associadas
adminforge user-group list
```

`add-member` e `remove-member` aceitam **N usernames de uma vez**, separados por espaço, vírgula ou misto (`alice,bob carla`). Idempotentes; tudo entra como uma única operação no histórico — falha atômica se algum usuário não existir.

---

## UC-4 — Cadastrar servidor (TOFU + fingerprint)

Há dois modos. **Use `--auto` na primeira vez** que cadastra um servidor — o AdminForge captura a host key, mostra o fingerprint e pede confirmação interativa.

### Modo automático (recomendado)

```bash
adminforge server add --hostname web-01 --ip 10.0.0.10 --auto
```

Fluxo:

1. AdminForge executa `ssh-keyscan -t ed25519,rsa,ecdsa` no IP/porta.
2. Calcula o **fingerprint SHA256** da chave pública do host (mesmo formato que o `ssh` mostra na primeira conexão).
3. Imprime algo como:
   ```
       i  host_key capturada: SHA256:5kF7y2...HxQ9c
   Confirma o fingerprint? [y/N]:
   ```
4. **Antes de digitar `y`**, valide o fingerprint por um canal independente (out-of-band): rode `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` no console do servidor, peça ao provisionador, ou compare contra o que veio no cloud-init. Esse passo é o que garante o "T" do TOFU (*Trust On First Use*) — uma vez aceito, fingerprint divergente em conexões futuras causa falha clara.
5. Se confirmar, o servidor é gravado com a host key fixada. Conexões seguintes usam `StrictHostKeyChecking=yes` contra esse `known_hosts` próprio do AdminForge (em `state/known_hosts`).

### Modo manual

Se você já tem a host key (ex.: provisionou o servidor e copiou a saída de `ssh-keyscan`):

```bash
adminforge server add --hostname web-01 --ip 10.0.0.10 \
    --host-key "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA..."
```

Pula a confirmação (já confiou no que está colando).

> **Pré-condição** (modelagem 5.4): o servidor deve estar acessível via SSH com a chave pública do AdminForge **já instalada** no usuário de serviço (definido por `ADMINFORGE_SSH_USER`, default `adminforge`). Esse bootstrap é manual ou via cloud-init.

### Quando o fingerprint diverge depois

Se a host key registrada e a real divergirem (servidor reinstalado, chave rotacionada, MITM), o `apply` para esse servidor falha com:

```
ERRO  web-01   adicionar_chave  alice:...  — ssh: Host key verification failed
```

Para aceitar a nova: `adminforge server remove --hostname web-01 --yes` e `server add --auto` de novo.

```bash
adminforge server list
adminforge server show --hostname web-01
adminforge server remove --hostname web-01     # remove do estado; nao limpa chaves no servidor
```

---

## UC-5 — Gerenciar grupo de servidores

Análogo ao UC-3, com suporte a N hostnames de uma vez (espaço, vírgula ou misto):

```bash
adminforge server-group create --name producao
adminforge server-group add-member --group producao --hostname web-01,web-02 web-03
adminforge server-group remove-member --group producao --hostname web-03
adminforge server-group delete --name producao
adminforge server-group list
```

---

## UC-6 — Conceder / revogar acesso

```bash
adminforge grant --user-group sysadmins --server-group producao --level sudo
adminforge grant --user-group sysadmins --server-group producao --level shell    # rebaixa nivel
adminforge revoke --user-group sysadmins --server-group producao
```

Aliases CRUD equivalentes (mesmo comportamento):

```bash
adminforge permission list
adminforge permission update --user-group sysadmins --server-group producao --level sudo
adminforge permission delete --user-group sysadmins --server-group producao
```

- Mesmo par `(user_group, server_group)` é único: `grant`/`permission update` repetido **atualiza** o nível.
- `--level sudo` instala `/etc/sudoers.d/adminforge-<username>` com `NOPASSWD:ALL`.
- `--level shell` apenas instala a chave em `~/<username>/.ssh/authorized_keys`.
- Quando dois grupos concedem níveis diferentes, **sudo prevalece**.

---

## UC-7 — Ver prévia

```bash
adminforge preview
```

Read-only: lê o estado declarado e cada `chaves_instaladas`, calcula o delta, agrupa por servidor:

```
i  3 subacoes em 2 servidores

web-01
  + adicionar_chave    alice:SHA256:abc...    sudo
  - remover_chave      bob:SHA256:def...       shell

db-03
  + adicionar_chave    alice:SHA256:abc...    sudo
```

---

## UC-8 — Aplicar mudanças

```bash
adminforge apply              # confirma antes
adminforge apply --yes        # sem confirmacao
adminforge apply --dry-run    # simula com DryRunDeployer
```

Saída típica com falha parcial:

```
  OK   web-01   adicionar_chave   alice:SHA256:abc...
  OK   web-02   adicionar_chave   alice:SHA256:abc...
 ERRO  db-03    adicionar_chave   alice:SHA256:abc... — ssh: connect timeout after 30s

operacao: OP-0042
  status: SUCESSO_PARCIAL
sucessos: 2
  falhas: 1
i  reaplicar com 'adminforge apply' retentativa apenas as subacoes em falha
```

`apply` **não tem fila de pendentes**. O delta é recalculado a cada execução: o que não foi para o servidor (porque o `chaves_instaladas` não mudou) entra novamente no próximo `apply`. Detalhes em [`ARCHITECTURE.md`](ARCHITECTURE.md#apply).

---

## UC-9 — Histórico

```bash
adminforge history list                       # ultimas 50
adminforge history list -n 200
adminforge history show --id OP-0042          # detalhes + subacoes
adminforge history failed                     # so falhas e parciais
adminforge history verify                     # checa cadeia SHA256
```

`verify` re-calcula o hash de cada entrada e compara com o `hash_anterior` da próxima. Qualquer alteração retroativa (mesmo um caractere) é detectada e o comando aponta o ID do primeiro divergente.

---

## UC-10 — Auditar servidor

```bash
adminforge audit server --hostname web-01                  # tudo
adminforge audit server --hostname web-01 --humans         # só UID >= 1000
adminforge audit server --hostname web-01 --user tomcat    # destaca usuário
adminforge audit server --hostname web-01 --group docker   # filtra grupos
adminforge audit server --hostname web-01 --service nginx  # destaca serviço
```

Conecta via SSH (read-only) numa única chamada e coleta:

- **Usuários:** todos do `getent passwd`, classificados em `sistema` (UID < 100), `serviço` (100–999) e `humano` (≥ 1000). Tabela com UID, shell, grupos a que pertence e indicador se há regra `sudo` para a conta.
- **Grupos:** `getent group` com gid e membros.
- **Sudoers:** lista `/etc/sudoers.d/` e o corpo das regras. Marca arquivos `adminforge-*` como gerenciados pelo AdminForge; demais como **manuais** (drift).
- **Serviços:** `systemctl list-units --state=running` (fallback `service --status-all`).

No fim, seção **Alerts** sinaliza heurísticas:
- usuário existe mas nenhum serviço correspondente está rodando (`tomcat` sem `tomcat.service`);
- arquivos em `/etc/sudoers.d/` fora do AdminForge.

> **Escopo.** Leitura **diagnóstica**, não substitui auditoria nativa do host (`sshd` + `auditd`).

---

## Globals e variáveis de ambiente

| Variável                  | Padrão                        | Para que serve |
|---------------------------|-------------------------------|----------------|
| `ADMINFORGE_STATE`        | `./state`                     | Diretório dos JSONs e do `history.jsonl`. |
| `ADMINFORGE_SUPERADMIN`   | `$USER`                       | Identifica quem está executando (vai pro histórico). |
| `ADMINFORGE_SSH_KEY`      | `~/.ssh/adminforge_id`        | Chave privada usada pelo Deployer SSH. |
| `ADMINFORGE_SSH_USER`     | `adminforge`                  | Usuário de serviço nos servidores gerenciados. |

Todos os comandos aceitam `--help` (`-h`) com exemplos.
