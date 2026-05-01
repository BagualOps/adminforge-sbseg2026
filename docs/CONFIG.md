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
│   └── <username>.yaml
├── admin-groups/
│   └── <nome>.yaml
├── servers/                # 1 arquivo por servidor (inclui chaves_instaladas)
│   └── <hostname>.yaml
├── server-groups/
│   └── <nome>.yaml
├── permissions.yaml        # arquivo único
├── history.jsonl           # append-only
└── .lock                   # fcntl flock
```

Permissões: diretórios `0700`, arquivos `0600`.

## Schemas dos YAMLs

### `admins/<username>.yaml`

```yaml
id: 9c1d8e1a-9b1f-4e09-9d34-3b5b23a3eaa1
username: marina
nome: Marina Silva
email: marina@empresa.com
status: ativo                 # ativo | inativo | bloqueado
credenciais:
  - id: 7f01...
    chave_publica: "ssh-ed25519 AAAA... marina@laptop"
    fingerprint: SHA256:abc...
    status: ativa             # ativa | revogada
```

### `admin-groups/<nome>.yaml`

```yaml
id: ...
nome: sysadmins
membros:
  - marina
  - rui
```

### `servers/<hostname>.yaml`

```yaml
id: ...
hostname: web-01
ipv4: 10.0.0.10
porta_ssh: 22
chave_host: "ssh-ed25519 AAAAC3..."
chaves_instaladas:
  - ref: "marina:SHA256:abc..."
    username: marina
    nivel: sudo
```

`chaves_instaladas` reflete o que de fato está nesse servidor. **É a única fonte de verdade do estado real**; o Planner compara com isso para calcular o delta.

### `server-groups/<nome>.yaml`

```yaml
id: ...
nome: producao
membros:
  - web-01
  - web-02
```

### `permissions.yaml`

```yaml
permissoes:
  - id: ...
    grupo_admin: sysadmins
    grupo_servidor: producao
    nivel: sudo               # shell | sudo
```

### `history.jsonl` (1 linha por operação)

```json
{"id":"OP-0042","momento":"2026-04-22T14:32:11-03:00","superadmin":"cristhian","comando":"apply","status":"sucesso_parcial","subacoes":[{"servidor":"web-01","acao":"adicionar_chave","credencial":"marina:SHA256:abc","status":"sucesso"},{"servidor":"db-03","acao":"adicionar_chave","credencial":"marina:SHA256:abc","status":"falha","erro":"ssh: connect timeout after 30s"}],"hash_anterior":"7c4a8d09...","hash":"9e8b2c14..."}
```

## Backup

```bash
tar -czf adminforge-state-$(date +%F).tar.gz state/
```

Restaurar = expandir e respeitar permissões. Histórico permanece verificável (a cadeia foi preservada).

## Migração futura para Git (M-3)

`state/` é compatível com `git init` direto. O M-3 prevê servidores em modo *pull* lendo de um repositório Git assinado — manter a estrutura atual habilita essa transição sem mudar layout.
