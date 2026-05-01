# Contribuindo

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
```

## Rodando testes

```bash
pytest -v                          # todos
pytest tests/test_planner.py -v    # módulo
pytest -k "fluxo_completo" -v      # filtro
pytest --cov=adminforge            # cobertura
```

A suíte cobre 36 cenários: unitários por componente + fluxo end-to-end + edge cases.

## Lint e tipos

```bash
ruff check .
mypy adminforge/
```

## Estilo

- `ruff` com line-length 100, target Python 3.11.
- Nomes em português onde fizer sentido (entidades, comandos), técnicos em inglês (`fingerprint`, `host_key`).
- Sem comentários óbvios. Comentário só quando explica **porquê** não-óbvio.
- KISS antes de DRY antes de "elegante".

## Estrutura de novo caso de uso

1. Acrescentar método no `Nucleo` (validações + Store + Auditor).
2. Acrescentar comando na CLI (`adminforge/cli/main.py`).
3. Escrever teste de fluxo positivo + 1-2 edge cases em `tests/test_nucleo.py`.
4. Acrescentar exemplo no [`USAGE.md`](USAGE.md).

## Commits

- Convencionais: `feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`.
- Mensagem em português, modo imperativo, focada no **porquê**.

## Branches & PRs

- Branch a partir de `main`.
- PR pequeno (≤ 400 linhas idealmente).
- Descrição com checklist: testes adicionados? docs atualizadas? regression manual?

## Roadmap

Ver "Próximos passos" e "Questões em aberto" em [`modelagem-v1.pdf`](modelagem-v1.pdf), seção 8.
