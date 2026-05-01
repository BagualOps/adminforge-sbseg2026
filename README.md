# AdminForge

CLI Python para gestão de identidades privilegiadas em frotas de servidores Linux. Pensado para um cenário concreto: ~600 máquinas, ~20 admins, equipes que mudam, sem o peso de FreeIPA/LDAP+Kerberos.

> **Por que existe.** Hoje o acesso é configurado servidor a servidor. Quando alguém entra, instala-se a chave em todas as máquinas que esse admin precisa. Quando alguém sai, fica fácil esquecer um servidor. AdminForge declara o estado desejado em YAML, calcula o delta e propaga só o que mudou — com histórico verificável.

## Estado do projeto

- **M-0** Modelagem v1 — [`docs/modelagem-v1.pdf`](docs/modelagem-v1.pdf)
- **M-1** Protótipo Python — **este repositório** (10/10 UCs implementados, 37 testes passando, integration test em Docker no CI)
- **M-2** Robustez — retentativa automática, `apply verify`, cifragem seletiva
- **M-3** Rust + modo *pull* — servidores puxam estado de repositório Git assinado

### Footprint (zero deps de runtime)

| Camada | Antes | Agora | Variação |
|--------|-------|-------|----------|
| Código nosso (produção) | 2.429 LOC | 2.358 LOC | -71 (-3%) |
| Dependências de runtime | ~56.000 LOC (paramiko, click, PyYAML, cryptography, …) | **0** | **-100%** |
| Total executado | ~58.400 LOC | 2.358 LOC | **-96%** |

Substituições que compõem essa redução:

- `paramiko + cryptography + bcrypt + pynacl + cffi` → `subprocess(ssh)` chamando OpenSSH binário
- `click` → `argparse` (stdlib) + helpers ANSI
- `PyYAML` → `json` (stdlib); arquivos de estado em `.json`

Detalhes em [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#zero-deps).

### Endurecimentos do `apply` (revisão crítica)

| # | Mudança | Status |
|---|---------|--------|
| 1 | Markers `# BEGIN/END adminforge: <ref>` em `authorized_keys` — não briga com edição manual | ✅ |
| 2 | `visudo -cf` antes de mover sudoers — sintaxe ruim não quebra `sudo` da máquina | ✅ |
| 3 | `ADMINFORGE_CREATE_UNIX_USER=false` desabilita `useradd` automático | ✅ |
| 4 | Threshold UID >= 100 no `audit server` — captura service accounts (postgres, tomcat, etc.) | ✅ |
| 5 | Strategy: `SSHDeployer` (real) e `DryRunDeployer` (testes) | ✅ |
| 6 | Lockfile (`fcntl.flock`) — exclusão mútua entre operadores | ✅ |
| 7 | Histórico append-only com cadeia SHA256; `verify` aponta divergência | ✅ |
| 8 | Backup `authorized_keys.bak` antes da edição | M-2 |
| 9 | Sudoers configurável por comando (não só `NOPASSWD:ALL`) | M-2 |
| 10 | `apply verify` — confere `chaves_instaladas` declaradas vs reais | M-2 |
| 11 | Paralelismo + taxa-falha-máxima no Deployer | M-2 |
| 12 | `apply --diff` mostra antes/depois do `authorized_keys` | M-2 |

## Princípios

| Diretriz | O que significa |
|----------|-----------------|
| **Modular** | CLI, Núcleo, Store, Planner, Deployer, Auditor — cada um trocável. |
| **Independente em uso** | AdminForge fora do ar não tira ninguém de servidor algum. |
| **Só CLI na v1** | Sem GUI; o Superadmin opera no terminal. |
| **Tudo registrado** | Cada comando vira entrada no histórico, com cadeia de hashes. |
| **Só aplica o que mudou** | Servidor com 5 chaves + admin novo no grupo → só a 6ª chave é propagada. |
| **Inspeciona o real sob demanda** | `audit server` lê usuários/serviços via SSH, sem alterar nada. |

## Arquitetura — visão de 30 segundos

```
CLI ──► Núcleo ─┬─► Store    (YAML em ./state/)
                ├─► Planner  (delta = desejado − chaves_instaladas)
                ├─► Deployer (SSH paramiko, ou DryRun para testes)
                └─► Auditor  (history.jsonl com cadeia de SHA256)
```

Detalhes em [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Modelagem completa (papéis, casos de uso, fluxos, segurança) em [`docs/modelagem-v1.pdf`](docs/modelagem-v1.pdf).

## Quickstart (60 segundos)

**Zero dependências de runtime** — basta Python 3.11+ e o cliente OpenSSH (já vem em qualquer Linux).

```bash
git clone https://github.com/BagualOps/adminforge-v1.git
cd adminforge-v1

# Roda direto, sem pip install (nem venv):
python3 -m adminforge.cli.main --help

# Cadastros (mudam apenas o estado desejado)
alias adminforge="python3 -m adminforge.cli.main"

adminforge admin add alice --nome "Alice Silva" --email alice@empresa.com
adminforge key add alice --file ~/.ssh/alice.pub
adminforge group create sysadmins
adminforge group add-member sysadmins alice

adminforge server add web-01 --ip 10.0.0.10 --auto       # TOFU host_key
adminforge server-group create producao
adminforge server-group add-member producao web-01

adminforge grant sysadmins producao --nivel sudo

# Ver e aplicar
adminforge preview                                        # read-only
adminforge apply                                          # via SSH
adminforge history list
adminforge history verify
```

Pra instalar como comando do sistema (opcional):

```bash
pipx install .            # ou: pip install --user .
```

Receitário completo por caso de uso: [`docs/USAGE.md`](docs/USAGE.md).

## Casos de uso (UC-1 a UC-10)

| ID    | Comando                                                | O que faz |
|-------|--------------------------------------------------------|-----------|
| UC-1  | `adminforge admin add`                                 | Cadastra admin (sem grupo, sem acesso). |
| UC-2  | `adminforge key add` / `key revoke`                    | Cadastra/revoga chave SSH (ed25519, rsa, ecdsa). |
| UC-3  | `adminforge group ...`                                 | Cria/edita/exclui grupo de admin. |
| UC-4  | `adminforge server add`                                | Registra servidor com TOFU de host key. |
| UC-5  | `adminforge server-group ...`                          | Cria/edita grupo de servidor. |
| UC-6  | `adminforge grant` / `revoke`                          | Liga grupos com nível `shell` ou `sudo`. |
| UC-7  | `adminforge preview`                                   | Mostra o delta sem tocar em servidores. |
| UC-8  | `adminforge apply`                                     | Propaga o delta via SSH em paralelo. |
| UC-9  | `adminforge history list/show/failed/verify`           | Auditoria do que o Superadmin fez. |
| UC-10 | `adminforge audit server`                              | Inspeção operacional read-only do servidor. |

## Segurança

- YAMLs em diretório `0700`, arquivos `0600`.
- Chave SSH dedicada do AdminForge (não a do Superadmin).
- `StrictHostKeyChecking=no` é proibido — host key armazenada por servidor.
- Histórico append-only com cadeia SHA256; `verify` aponta primeiro ponto de divergência.
- O escopo de auditoria é estrito: AdminForge audita o **Superadmin**; logins dos admins nos servidores ficam com `sshd`/`auditd` de cada máquina.

Mais em [`docs/SECURITY.md`](docs/SECURITY.md).

## Documentação

| Documento | Conteúdo |
|-----------|----------|
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | Caminho feliz em 5 minutos. |
| [`docs/USAGE.md`](docs/USAGE.md)           | Cookbook por caso de uso, com exemplos copiáveis. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Componentes, padrões de projeto, decisões. |
| [`docs/SECURITY.md`](docs/SECURITY.md)     | Modelo de ameaças, cuidados operacionais, escopo de auditoria. |
| [`docs/CONFIG.md`](docs/CONFIG.md)         | Variáveis de ambiente e estrutura do `state/`. |
| [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) | Como rodar testes, lint, contribuir. |
| [`docs/ROTEIRO.md`](docs/ROTEIRO.md) | Guia de operação completo: instalação, bootstrap, cadastro inicial, rotina diária. |
| [`docs/modelagem-v1.pdf`](docs/modelagem-v1.pdf) | Modelagem original (sumário, diagramas, fluxos, questões em aberto). |

## Testes

```bash
pytest -v
```

36 testes cobrem o fluxo end-to-end e edge cases (cadeia quebrada, duplicatas, idempotência, falha parcial, no-op, lockfile concorrente, permissão 0600).

### Como usar em produção

Para começar a operar sua frota com AdminForge — bootstrap dos servidores, cadastro inicial, e fluxos do dia-a-dia (alguém entrou, alguém saiu, novo servidor, chave comprometida) — siga o **[Guia de operação](docs/ROTEIRO.md)**.

## Licença

GNU AGPL-3.0.
