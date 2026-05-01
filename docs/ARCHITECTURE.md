# Arquitetura

> **Visão de 30 segundos.** Seis componentes, cada um com uma responsabilidade clara. CLI é a única porta de entrada; os outros são internos. Estado declarado em YAML; estado real espelhado no campo `chaves_instaladas` de cada servidor; delta calculado em memória; aplicação via SSH; histórico append-only com cadeia de hashes.

## Diagrama

```
                       ┌──────────────────┐
                       │       CLI        │  (Click; única porta de entrada)
                       └────────┬─────────┘
                                │
                       ┌────────▼─────────┐
                       │      Núcleo      │  (regras de negócio + lockfile)
                       └─┬────┬────┬────┬─┘
                         │    │    │    │
                ┌────────┘    │    │    └────────┐
                │             │    │             │
        ┌───────▼──────┐  ┌───▼────▼───┐  ┌──────▼──────┐
        │    Store     │  │  Planner   │  │   Auditor   │
        │  YAML 0600   │  │   delta    │  │ history.jsonl│
        └──────────────┘  └─────┬──────┘  └─────────────┘
                                │
                          ┌─────▼─────┐
                          │  Deployer │  (Strategy: SSH ou DryRun)
                          └─────┬─────┘
                                │ SSH
                          ┌─────▼─────┐
                          │ Frota Linux │
                          └───────────┘
```

## Responsabilidades

| Componente | O que faz | Não faz |
|------------|-----------|---------|
| **CLI** (`adminforge/cli`) | Lê argumentos, valida sintaxe, formata saída. | Não conhece YAML, SSH ou hash chain. |
| **Núcleo** (`adminforge/core/nucleo.py`) | Aplica regras (duplicatas, validações), coordena demais. | Não escreve em arquivo nem conecta em servidor diretamente. |
| **Store** (`adminforge/store/yaml_store.py`) | Persiste entidades em YAML; lockfile; escrita atômica; permissão 0600. | Não conhece SSH nem hash chain. |
| **Planner** (`adminforge/planner/planner.py`) | Calcula `desejado − chaves_instaladas` e emite subações. | Não persiste, não conecta em servidor. |
| **Deployer** (`adminforge/deployer/`) | Executa subações via SSH; faz inspeção operacional. | Não decide o que fazer; recebe lista pronta do Núcleo. |
| **Auditor** (`adminforge/auditor/jsonl_auditor.py`) | Persiste histórico append-only com cadeia SHA256. | Não muda estado; só lê/escreve `history.jsonl`. |

## Persistência

```
state/
├── admins/                # 1 arquivo por admin (inclui suas chaves)
│   └── marina.yaml
├── admin-groups/
│   └── sysadmins.yaml
├── servers/               # cada server.yaml inclui chaves_instaladas
│   └── web-01.yaml
├── server-groups/
│   └── producao.yaml
├── permissions.yaml       # arquivo único: lista de (grupo_admin, grupo_servidor, nivel)
├── history.jsonl          # append-only, 1 linha por comando
└── .lock                  # fcntl.flock — exclusão mútua
```

Razões:
- **Texto simples.** Cabe na escala (≈20 admins, 600 servidores), versável em Git, lê-se a olho nu.
- **Sem banco.** Sem ACID, sem schema migration, sem processo separado.
- **Lockfile.** Evita escrita simultânea; falha rápida é aceitável.

## Padrões aplicados

Quatro padrões, cada um resolvendo problema concreto:

- **Repository** no Store: esconde de onde os dados vêm. `IStore` permite trocar YAML por Git ou memória sem tocar Núcleo.
- **Strategy** no Deployer: `SSHDeployer` (paramiko) e `DryRunDeployer` (testes); trocar por Ansible é substituição, não refatoração.
- **Command** na CLI: cada subcomando vira um método auditável do Núcleo; cada chamada gera Operação no histórico.
- **Observer (light)** no Auditor: Núcleo registra Operação ao final de cada caso de uso.

Padrões deliberadamente **evitados**: Singleton, Abstract Factory, container DI, herança profunda, async generalizado. Nenhum resolve problema real nesta versão.

## SOLID, pragmaticamente

- **S** Cada componente da tabela acima muda por um motivo só.
- **O** Trocar Deployer SSH por Ansible é substituição (Open/Closed).
- **L** Implementações de `IStore` (YAML, Git, memória) se comportam igual para o Núcleo.
- **I** Interfaces pequenas: Store não sabe de SSH; Deployer não lê arquivo.
- **D** Núcleo depende de `IStore`/`IDeployer`/`IAuditor`, não das classes concretas. Facilita testes (DryRunDeployer no `conftest`).

## Apply: o coração do sistema

```
1. Núcleo abre Operação com status=em_andamento
2. Planner calcula delta e produz lista de Subações
3. CLI exibe lista e pede confirmação
4. Deployer executa subações em paralelo (limite configurável)
5. Para cada subação:
   - sucesso  -> atualiza chaves_instaladas no Store
   - falha    -> anota erro; nao toca chaves_instaladas
6. Núcleo fecha Operação com sucesso | sucesso_parcial | falha
7. CLI imprime resumo
```

**Não existe fila de "tarefas pendentes".** Pendência é sempre calculada na hora como `desejado − aplicado`. Se uma subação falhar, `chaves_instaladas` daquele servidor não muda, então o próximo `apply` naturalmente identifica a diferença no delta. Isso evita duas fontes da verdade que podem divergir.

## Histórico imutável

Cada entrada de `history.jsonl` é um JSON com:

```json
{
  "id": "OP-0042",
  "momento": "2026-04-22T14:32:11-03:00",
  "superadmin": "cristhian",
  "comando": "apply",
  "status": "sucesso_parcial",
  "subacoes": [...],
  "hash_anterior": "7c4a8d09...",
  "hash": "9e8b2c14..."
}
```

`hash` é SHA256 sobre o JSON canônico (chaves ordenadas) **incluindo `hash_anterior`**, o que encadeia as entradas. `adminforge history verify` recalcula tudo e detecta:

- alteração de qualquer campo de uma entrada (hash não bate);
- inserção, deleção ou reordenação (hash_anterior não bate);
- truncamento do final (último hash conhecido não bate com o atual).

## Decisões e trade-offs

| Decisão | Por quê | Trade-off |
|---------|---------|-----------|
| YAML em vez de banco | Escala pequena cabe em texto; versionável em Git. | Sem indexação; busca = leitura linear. Aceitável para dezenas de admins. |
| Fluxo síncrono | Sem latência crítica; um Superadmin opera por vez. | `apply` em 600 servidores depende de SSH paralelo no Deployer. |
| Sem cache | Ler YAML é barato. | Cada leitura abre arquivos. |
| `chaves_instaladas` no Servidor | Resposta direta a "o que já está deployado". | Reconciliação opcional (`apply verify`) fica para M-2. |
| Lockfile | KISS para exclusão mútua. | Falha rápida se outra instância roda; aceitável. |
| TOFU para host_key | KISS; conta com confirmação humana no cadastro. | Não detecta MitM no primeiro contato. |
| `chave_host` armazenada | Detecta MitM em conexões seguintes. | Rotação requer revalidação manual. |

## Estrutura do código

```
adminforge/
├── __init__.py
├── domain.py              # dataclasses + enums das 7 entidades
├── exceptions.py          # hierarquia de erros
├── ssh_keys.py            # parse, fingerprint, validacao
├── interfaces/            # ABCs (Store, Deployer, Auditor)
├── store/
│   ├── atomic.py          # write_atomic, append_line
│   └── yaml_store.py      # IStore + lockfile
├── auditor/
│   └── jsonl_auditor.py   # cadeia SHA256
├── planner/
│   └── planner.py         # delta entre desejado e aplicado
├── deployer/
│   ├── dry_run.py         # IDeployer fake p/ testes
│   └── ssh_deployer.py    # paramiko + RejectPolicy
├── core/
│   └── nucleo.py          # orquestrador
└── cli/
    ├── main.py            # Click — 10 UCs
    └── ui.py              # cores, tabelas, confirmações
```
