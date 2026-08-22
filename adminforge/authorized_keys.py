"""Helpers for managing the AdminForge block in authorized_keys."""
from __future__ import annotations

START_MARKER = "# BEGIN adminforge: "
END_MARKER = "# END adminforge: "


def block(ref: str, key: str) -> str:
    """Build one managed BEGIN/END block for `key`, tagged with `ref`.

    `key` is stripped but not otherwise validated or re-encoded; it is
    written verbatim between the markers.
    """
    return f"{START_MARKER}{ref}\n{key.strip()}\n{END_MARKER}{ref}"


def parse_blocks(conteudo: str) -> dict[str, str]:
    """Return {ref: body} of the '# BEGIN/END adminforge: <ref>' blocks found."""
    out: dict[str, str] = {}
    ref: str | None = None
    buffer: list[str] = []
    for line in conteudo.splitlines():
        if line.startswith(START_MARKER):
            ref = line[len(START_MARKER):]
            buffer = []
            continue
        if ref is not None and line.startswith(END_MARKER):
            if line[len(END_MARKER):] == ref:
                out[ref] = "\n".join(buffer)
            ref = None
            buffer = []
            continue
        if ref is not None:
            buffer.append(line)
    return out


def replace_block(conteudo: str, ref: str, new_block: str) -> str:
    """Replace the body of the block with the given ref (empty = remove). Lines outside
    the AdminForge markers are preserved."""
    inicio = f"{START_MARKER}{ref}"
    fim = f"{END_MARKER}{ref}"
    out: list[str] = []
    dentro = False
    for line in conteudo.splitlines():
        if line == inicio:
            dentro = True
            continue
        if dentro:
            if line == fim:
                dentro = False
            continue
        out.append(line)
    if new_block:
        out.append(new_block)
    resultado = "\n".join(out)
    if resultado and not resultado.endswith("\n"):
        resultado += "\n"
    return resultado
