# Configuração

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `ADMINFORGE_STATE` | `./state` | Diretório com YAMLs e `history.jsonl`. Pode ser absoluto. |
| `ADMINFORGE_SUPERADMIN` | `$USER` | Identifica quem operou (vai pro histórico). |
| `ADMINFORGE_SSH_KEY` | `~/.ssh/adminforge_id` | Chave privada usada pelo `SSHDeployer`. |
| `ADMINFORGE_SSH_USER` | `adminforge` | Usuário de serviço nos servidores gerenciados. |

Sobreposição via flag tem precedência: `--state /var/lib/adminforge/state` ignora `ADMINFORGE_STATE`.

## Estrutura do diretório `state/`

```
state/
├── admins/                 # 1 arquivo por admin
│   └── <username>.json
├── admin-groups/
│   └── <nome>.json
├── servers/                # 1 arquivo por servidor (inclui chaves_instaladas)
│   └── <hostname>.json
├── server-groups/
│   └── <nome>.json
├── permissions.json        # arquivo único
├── history.jsonl           # append-only
└── .lock                   # fcntl flock
```

Permissões: diretórios `0700`, arquivos `0600`.

## Schemas dos arquivos JSON

### `admins/<username>.json`

```json
{
  "id": "9c1d8e1a-9b1f-4e09-9d34-3b5b23a3eaa1",
  "username": "alice",
  "nome": "Alice Silva",
  "email": "alice@empresa.com",
  "status": "ativo",
  "credenciais": [
    {
      "id": "7f01...",
      "chave_publica": "ssh-ed25519 AAAA... alice@laptop",
      "fingerprint": "SHA256:abc...",
      "status": "ativa"
    }
  ]
}
```

`status`: `ativo | inativo | bloqueado`. `credenciais[].status`: `ativa | revogada`.

### `admin-groups/<nome>.json`

```json
{
  "id": "...",
  "nome": "sysadmins",
  "membros": ["alice", "bob"]
}
```

### `servers/<hostname>.json`

```json
{
  "id": "...",
  "hostname": "web-01",
  "ipv4": "10.0.0.10",
  "porta_ssh": 22,
  "chave_host": "ssh-ed25519 AAAAC3...",
  "chaves_instaladas": [
    {
      "ref": "alice:SHA256:abc...",
      "username": "alice",
      "nivel": "sudo"
    }
  ]
}
```

`chaves_instaladas` reflete o que de fato está nesse servidor. **É a única fonte de verdade do estado real**; o Planner compara com isso para calcular o delta.

### `server-groups/<nome>.json`

```json
{
  "id": "...",
  "nome": "producao",
  "membros": ["web-01", "web-02"]
}
```

### `permissions.json`

```json
{
  "permissoes": [
    {
      "id": "...",
      "grupo_admin": "sysadmins",
      "grupo_servidor": "producao",
      "nivel": "sudo"
    }
  ]
}
```

`nivel`: `shell | sudo`.

### `known_hosts`

Arquivo OpenSSH padrão, gerenciado pela ferramenta. Cada linha:

```
[hostname]:porta  ssh-ed25519 AAAAC3...
```

Usado pelo `SSHDeployer` com `ssh -o UserKnownHostsFile=state/known_hosts -o StrictHostKeyChecking=yes`.

### `history.jsonl` (1 linha por operação)

```json
{"id":"OP-0042","momento":"2026-04-22T14:32:11-03:00","superadmin":"alice","comando":"apply","status":"sucesso_parcial","subacoes":[{"servidor":"web-01","acao":"adicionar_chave","credencial":"alice:SHA256:abc","status":"sucesso"},{"servidor":"db-03","acao":"adicionar_chave","credencial":"alice:SHA256:abc","status":"falha","erro":"ssh: connect timeout after 30s"}],"hash_anterior":"7c4a8d09...","hash":"9e8b2c14..."}
```

## Backup

```bash
tar -czf adminforge-state-$(date +%F).tar.gz state/
```

Restaurar = expandir e respeitar permissões. Histórico permanece verificável (a cadeia foi preservada).

## Migração futura para Git (M-3)

`state/` é compatível com `git init` direto. O M-3 prevê servidores em modo *pull* lendo de um repositório Git assinado — manter a estrutura atual habilita essa transição sem mudar layout.
