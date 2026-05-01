# Cookbook por caso de uso

Cada caso de uso da modelagem v1, com gatilho, fluxo e exemplo copiável.

> **Convenção.** Operações que mudam o estado **desejado** não tocam servidor nenhum — tocam apenas os JSONs em `state/`. As mudanças vão para os servidores no próximo `apply`. Excessão: `audit server` é read-only direto no servidor.

---

## UC-1 — Cadastrar admin

```bash
adminforge admin add <username> --nome "Nome Completo" --email pessoa@empresa.com
```

- `username` deve casar com `^[a-z_][a-z0-9_-]{0,30}$` (regra Linux).
- E-mail validado por regex simples.
- Cadastro duplicado falha com mensagem clara.

```bash
adminforge admin list                # tabela
adminforge admin show alice         # detalha admin + chaves + grupos
adminforge admin disable alice      # status=inativo, chaves revogadas
```

---

## UC-2 — Cadastrar / revogar chave SSH

```bash
adminforge key add alice --file ~/.ssh/alice.pub
adminforge key add alice --string "ssh-ed25519 AAAA... alice@laptop"
```

Aceita `ssh-ed25519`, `ssh-rsa`, `ecdsa-sha2-nistp{256,384,521}`. Fingerprint é SHA256 da chave.

Revogar:

```bash
adminforge key list alice
adminforge key revoke SHA256:abc123...
```

A revogação muda o status para `revogada`. A remoção física do `authorized_keys` acontece no próximo `apply`.

---

## UC-3 — Gerenciar grupo de admin

```bash
adminforge group create sysadmins
adminforge group add-member sysadmins alice
adminforge group remove-member sysadmins alice
adminforge group delete sysadmins        # bloqueia se houver permissoes associadas
adminforge group list
```

`add-member` e `remove-member` são idempotentes — repetir é no-op com `sucesso`.

---

## UC-4 — Cadastrar servidor

```bash
# Modo manual: voce traz a host_key (ssh-keyscan)
adminforge server add web-01 --ip 10.0.0.10 \
    --host-key "ssh-ed25519 AAAAC3..."

# Modo auto: captura via SSH (TOFU - trust on first use)
adminforge server add db-03 --ip 10.0.0.30 --auto
```

Após cadastrado, conexões usam `RejectPolicy` — uma host key divergente faz a subação falhar com erro claro.

```bash
adminforge server list
adminforge server show web-01
adminforge server remove web-01     # remove do estado; nao limpa chaves no servidor
```

> **Pré-condição** (modelagem 5.4): o servidor deve estar acessível via SSH com a chave do AdminForge **já instalada manualmente** (ou via cloud-init) no usuário de serviço.

---

## UC-5 — Gerenciar grupo de servidor

Análogo ao UC-3:

```bash
adminforge server-group create producao
adminforge server-group add-member producao web-01
adminforge server-group remove-member producao web-01
adminforge server-group delete producao
adminforge server-group list
```

---

## UC-6 — Conceder / revogar acesso

```bash
adminforge grant sysadmins producao --nivel sudo
adminforge grant sysadmins producao --nivel shell      # rebaixa nivel
adminforge revoke sysadmins producao
```

- Mesmo par `(grupo_admin, grupo_servidor)` é único: `grant` repetido **atualiza** o nível.
- `nivel sudo` instala `/etc/sudoers.d/adminforge-<username>` com `NOPASSWD:ALL`.
- `nivel shell` apenas instala a chave em `~/<username>/.ssh/authorized_keys`.
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
adminforge history list                  # ultimas 50
adminforge history list -n 200
adminforge history show OP-0042          # detalhes + subacoes
adminforge history failed                # so falhas e parciais
adminforge history verify                # checa cadeia SHA256
```

`verify` re-calcula o hash de cada entrada e compara com o `hash_anterior` da próxima. Qualquer alteração retroativa (mesmo um caractere) é detectada e o comando aponta o ID do primeiro divergente.

---

## UC-10 — Auditar usuários e serviços do servidor

```bash
adminforge audit server web-01
adminforge audit server web-01 --user tomcat
adminforge audit server web-01 --service nginx
```

Conecta via SSH (read-only), lista:
- Usuários locais com UID ≥ 1000.
- Serviços em execução (`systemctl list-units --state=running`, fallback `service --status-all`).

Quando `--user X` aparece em usuários mas não em serviços, AdminForge sinaliza como possível "sobra operacional".

> **Escopo.** Esta é uma leitura **diagnóstica**, não substitui auditoria nativa do host (`sshd` + `auditd`).

---

## Globals e variáveis de ambiente

| Variável                  | Padrão                        | Para que serve |
|---------------------------|-------------------------------|----------------|
| `ADMINFORGE_STATE`        | `./state`                     | Diretório dos JSONs e do `history.jsonl`. |
| `ADMINFORGE_SUPERADMIN`   | `$USER`                       | Identifica quem está executando (vai pro histórico). |
| `ADMINFORGE_SSH_KEY`      | `~/.ssh/adminforge_id`        | Chave privada usada pelo Deployer SSH. |
| `ADMINFORGE_SSH_USER`     | `adminforge`                  | Usuário de serviço nos servidores gerenciados. |

Todos os comandos aceitam `--help` (`-h`) com exemplos.
