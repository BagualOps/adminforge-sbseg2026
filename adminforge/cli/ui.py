from __future__ import annotations

import sys

import click

from adminforge.domain import Operacao, StatusOperacao


def ok(msg: str) -> None:
    click.secho(f"  OK  ", fg="green", bold=True, nl=False)
    click.echo(msg)


def fail(msg: str) -> None:
    click.secho(" ERRO ", fg="red", bold=True, nl=False)
    click.echo(msg)


def warn(msg: str) -> None:
    click.secho(" AVISO", fg="yellow", bold=True, nl=False)
    click.echo(f" {msg}")


def info(msg: str) -> None:
    click.secho("  i   ", fg="blue", bold=True, nl=False)
    click.echo(msg)


def heading(msg: str) -> None:
    click.echo()
    click.secho(msg, bold=True, underline=True)


def kv(chave: str, valor: str) -> None:
    click.secho(f"{chave:>12}: ", fg="cyan", nl=False)
    click.echo(valor)


def imprimir_resultado(op: Operacao) -> int:
    if op.status == StatusOperacao.SUCESSO:
        ok(f"{op.comando}  ({op.id})")
        return 0
    if op.status == StatusOperacao.SUCESSO_PARCIAL:
        warn(f"{op.comando}  ({op.id}) — parcial")
        return 1
    erro = next((s.erro for s in op.subacoes if s.erro), op.comando)
    fail(f"{op.comando}  ({op.id})")
    if erro:
        click.secho(f"        {erro}", fg="red", dim=True)
    return 2


def confirmar(pergunta: str, default: bool = False) -> bool:
    return click.confirm(click.style(pergunta, fg="yellow"), default=default)


def exit_se_falha(op: Operacao) -> None:
    rc = imprimir_resultado(op)
    if rc != 0:
        sys.exit(rc)


def tabela(cabecalho: list[str], linhas: list[list[str]]) -> None:
    if not linhas:
        click.secho("(vazio)", dim=True)
        return
    larguras = [len(c) for c in cabecalho]
    for linha in linhas:
        for i, valor in enumerate(linha):
            larguras[i] = max(larguras[i], len(str(valor)))
    sep = "  "
    click.secho(sep.join(c.ljust(larguras[i]) for i, c in enumerate(cabecalho)), bold=True)
    click.echo(sep.join("-" * w for w in larguras))
    for linha in linhas:
        click.echo(sep.join(str(v).ljust(larguras[i]) for i, v in enumerate(linha)))
