# Configuração

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `ADMINFORGE_STATE` | `./state` | Diretório com JSONs e `history.jsonl`. Pode ser absoluto. |
| `ADMINFORGE_SUPERADMIN` | `$USER` | Identifica quem operou (vai pro histórico). |
| `ADMINFORGE_SSH_KEY` | `~/.ssh/adminforge_id` | Chave privada usada pelo `SSHDeployer`. |
| `ADMINFORGE_SSH_USER` | `adminforge` | Usuário de serviço nos servidores gerenciados. |
| `ADMINFORGE_LANG` | _(auto)_ | Idioma da CLI: `en` (padrão) ou `pt`. Sem ele, herda de `LC_ALL`/`LC_MESSAGES`/`LANG` (qualquer coisa que comece com `pt` vira português); na ausência de tudo, `en`. Afeta `--help`, mensagens e prompts — não os valores de status no estado (esses são a API). |

Sobreposição via flag tem precedência: `--state /var/lib/adminforge/state` ignora `ADMINFORGE_STATE`.

> **Idioma.** A CLI é bilíngue (en/pt-br). O texto-fonte é o inglês; o catálogo pt-br vive em `adminforge/i18n.py`. Uma string sem tradução cai para o inglês — degrada, não quebra. O *boilerplate* do `argparse` (`usage:`, `the following arguments are required:`...) permanece em inglês.

## Estrutura do diretório `state/`

```
state/
├── users/                  # 1 arquivo por usuário gerenciado
│   └── <username>.json
├── user-groups/
│   └── <nome>.json
├── servers/                # 1 arquivo por servidor (inclui installed_keys)
│   └── <hostname>.json
├── server-groups/
│   └── <nome>.json
├── sudo-profiles/          # 1 arquivo por perfil nomeado de comandos sudo
│   └── <nome>.json
├── permissions.json        # arquivo único
├── history.jsonl           # append-only
└── .lock                   # fcntl flock
```

Permissões: diretórios `0700`, arquivos `0600`.

## Schemas dos arquivos JSON

### `users/<username>.json`

```json
{
  "id": "9c1d8e1a-9b1f-4e09-9d34-3b5b23a3eaa1",
  "username": "alice",
  "name": "Alice Silva",
  "email": "alice@empresa.com",
  "status": "ativo",
  "credenciais": [
    {
      "id": "7f01...",
      "public_key": "ssh-ed25519 AAAA... alice@laptop",
      "fingerprint": "SHA256:abc...",
      "status": "ativa"
    }
  ]
}
```

`status`: `ativo | inativo | bloqueado`. `credenciais[].status`: `ativa | revogada`.

### `user-groups/<nome>.json`

```json
{
  "id": "...",
  "name": "sysadmins",
  "members": ["alice", "bob"]
}
```

### `servers/<hostname>.json`

```json
{
  "id": "...",
  "hostname": "web-01",
  "ipv4": "10.0.0.10",
  "ssh_port": 22,
  "host_key": "ssh-ed25519 AAAAC3...",
  "installed_keys": [
    {
      "ref": "alice:SHA256:abc...",
      "username": "alice",
      "level": "sudo"
    }
  ]
}
```

`installed_keys` reflete o que de fato está nesse servidor. **É a única fonte de verdade do estado real**; o Planner compara com isso para calcular o delta.

### `server-groups/<nome>.json`

```json
{
  "id": "...",
  "name": "producao",
  "members": ["web-01", "web-02"]
}
```

### `permissions.json`

```json
{
  "permissions": [
    {
      "id": "...",
      "user_group": "sysadmins",
      "server_group": "producao",
      "level": "sudo",
      "profile": "read-logs"
    }
  ]
}
```

`nivel`: `shell | sudo`. `profile` é opcional (apenas com `nivel: sudo`); aponta para um arquivo em `sudo-profiles/`. Sem `profile`, o `apply` instala `NOPASSWD:ALL`.

### `sudo-profiles/<nome>.json`

```json
{
  "id": "...",
  "name": "read-logs",
  "commands": [
    "/bin/journalctl",
    "/bin/cat /var/log/*"
  ]
}
```

Cada `command` precisa ser um caminho absoluto (`/...`) — sudoers exige absolute paths. Quando uma `Permission` aponta para este profile, o `apply` escreve `/etc/sudoers.d/adminforge-<username>` com uma linha `<username> ALL=(ALL) NOPASSWD: <comando>` para cada item.

### `known_hosts`

Arquivo OpenSSH padrão, gerenciado pela ferramenta. Cada linha:

```
[hostname]:porta  ssh-ed25519 AAAAC3...
```

Usado pelo `SSHDeployer` com `ssh -o UserKnownHostsFile=state/known_hosts -o StrictHostKeyChecking=yes`.

### `history.jsonl` (1 linha por operação)

```json
{"id":"OP-0042","timestamp":"2026-04-22T14:32:11-03:00","superadmin":"alice","command":"apply","status":"sucesso_parcial","sub_actions":[{"server":"web-01","action":"adicionar_chave","credential":"alice:SHA256:abc","status":"success"},{"server":"db-03","action":"adicionar_chave","credential":"alice:SHA256:abc","status":"falha","error":"ssh: connect timeout after 30s"}],"previous_hash":"7c4a8d09...","hash":"9e8b2c14..."}
```

## Backup

```bash
tar -czf adminforge-state-$(date +%F).tar.gz state/
```

Restaurar = expandir e respeitar permissões. Histórico permanece verificável (a cadeia foi preservada).

## Migração futura para Git (M-3)

`state/` é compatível com `git init` direto. O M-3 prevê servidores em modo *pull* lendo de um repositório Git assinado — manter a estrutura atual habilita essa transição sem mudar layout.
