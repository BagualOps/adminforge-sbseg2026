from __future__ import annotations

import os
import sys

from adminforge.domain import Operacao, StatusOperacao
from adminforge.i18n import t as _

_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_UNDERLINE = "\033[4m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_CYAN = "\033[36m"


def _color(text: str, *codes: str, bold: bool = False, dim: bool = False, underline: bool = False) -> str:
    if not _USE_COLOR:
        return text
    parts = list(codes)
    if bold:
        parts.append(_BOLD)
    if dim:
        parts.append(_DIM)
    if underline:
        parts.append(_UNDERLINE)
    return "".join(parts) + text + _RESET


def echo(msg: str = "") -> None:
    print(msg)


def secho(msg: str, *codes: str, **kwargs: bool) -> None:
    print(_color(msg, *codes, **kwargs))


def ok(msg: str) -> None:
    print(_color("  OK  ", _GREEN, bold=True) + msg)


def fail(msg: str) -> None:
    print(_color(" ERRO ", _RED, bold=True) + msg)


def warn(msg: str) -> None:
    print(_color(" AVISO", _YELLOW, bold=True) + " " + msg)


def info(msg: str) -> None:
    print(_color("  i   ", _BLUE, bold=True) + msg)


def heading(msg: str) -> None:
    print()
    print(_color(msg, bold=True, underline=True))


def kv(chave: str, valor: str) -> None:
    print(_color(f"{chave:>12}: ", _CYAN) + valor)


def imprimir_resultado(op: Operacao) -> int:
    if op.status == StatusOperacao.SUCESSO:
        ok(f"{op.comando}  ({op.id})")
        return 0
    if op.status == StatusOperacao.SUCESSO_PARCIAL:
        warn(_("{cmd}  ({id}) — partial").format(cmd=op.comando, id=op.id))
        return 1
    erro = next((s.erro for s in op.subacoes if s.erro), op.comando)
    fail(f"{op.comando}  ({op.id})")
    if erro:
        secho(f"        {erro}", _RED, dim=True)
    return 2


def confirmar(pergunta: str, default: bool = False) -> bool:
    sufixo = "[y/N]" if not default else "[Y/n]"
    try:
        resposta = input(_color(f"{pergunta} {sufixo}: ", _YELLOW)).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not resposta:
        return default
    return resposta[:1] == "y" or resposta[:1] == "s"


def exit_se_falha(op: Operacao) -> None:
    rc = imprimir_resultado(op)
    if rc != 0:
        sys.exit(rc)


def tabela(cabecalho: list[str], linhas: list[list[str]]) -> None:
    if not linhas:
        secho(_("(empty)"), dim=True)
        return
    larguras = [len(c) for c in cabecalho]
    for linha in linhas:
        for i, valor in enumerate(linha):
            larguras[i] = max(larguras[i], len(str(valor)))
    sep = "  "
    print(_color(sep.join(c.ljust(larguras[i]) for i, c in enumerate(cabecalho)), bold=True))
    print(sep.join("-" * w for w in larguras))
    for linha in linhas:
        print(sep.join(str(v).ljust(larguras[i]) for i, v in enumerate(linha)))
