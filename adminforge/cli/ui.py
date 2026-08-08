"""Terminal output primitives shared by every CLI subcommand: colored status lines, tables and prompts.

Color is auto-disabled when stdout is not a TTY or $NO_COLOR is set, so piping
`adminforge` output to a file or another program never leaks ANSI escapes.
"""
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
    """Wrap `text` in the given ANSI escape codes, or return it unchanged if color is disabled."""
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
    """Print a plain line to stdout (a thin wrapper so callers never call print() directly)."""
    print(msg)


def secho(msg: str, *codes: str, **kwargs: bool) -> None:
    """Print `msg` styled with the given ANSI codes/flags (see `_color`)."""
    print(_color(msg, *codes, **kwargs))


def ok(msg: str) -> None:
    """Print a green "OK" status line."""
    print(_color("  OK  ", _GREEN, bold=True) + msg)


def fail(msg: str) -> None:
    """Print a red "ERRO" status line. Does not raise or exit by itself."""
    print(_color(" ERRO ", _RED, bold=True) + msg)


def warn(msg: str) -> None:
    """Print a yellow "AVISO" (warning) status line."""
    print(_color(" AVISO", _YELLOW, bold=True) + " " + msg)


def info(msg: str) -> None:
    """Print a blue informational status line."""
    print(_color("  i   ", _BLUE, bold=True) + msg)


def heading(msg: str) -> None:
    """Print a bold, underlined section heading preceded by a blank line."""
    print()
    print(_color(msg, bold=True, underline=True))


def kv(chave: str, valor: str) -> None:
    """Print one right-aligned "key: value" line (key width 12, cyan key)."""
    print(_color(f"{chave:>12}: ", _CYAN) + valor)


def imprimir_resultado(op: Operacao) -> int:
    """Print the outcome of an Operacao (success/partial/failure) and return its process exit code.

    On failure, also prints the error of the first failed sub-action (if any)
    as extra context. Return value maps status to exit code: 0 for
    SUCESSO, 1 for SUCESSO_PARCIAL, 2 for anything else (failure) — callers
    typically return this value straight from the CLI command.
    """
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
    """Prompt `pergunta` on stdin and return True/False for the user's answer.

    Accepts an empty reply as `default`, and treats both "y" and "s" (yes in
    Portuguese) as affirmative. Ctrl-D or Ctrl-C are treated as "no" rather
    than propagating an exception, so callers never need their own
    KeyboardInterrupt handling around a confirmation prompt.
    """
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
    """Print the result of `op` and terminate the process (sys.exit) if it did not fully succeed.

    Unlike `imprimir_resultado`, this never returns to the caller when the
    operation is a partial success or a failure — use it only in commands
    that have nothing left to do after this point.
    """
    rc = imprimir_resultado(op)
    if rc != 0:
        sys.exit(rc)


def tabela(cabecalho: list[str], linhas: list[list[str]]) -> None:
    """Print `linhas` as a left-aligned, space-padded table under `cabecalho`.

    Column widths are computed from the widest cell (header or value) in each
    column. Prints a dimmed "(empty)" placeholder instead of a table when
    `linhas` is empty.
    """
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
