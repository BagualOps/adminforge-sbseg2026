"""Helpers para manipulacao do bloco AdminForge em authorized_keys."""
from __future__ import annotations

MARCADOR_INICIO = "# BEGIN adminforge: "
MARCADOR_FIM = "# END adminforge: "


def bloco(ref: str, chave: str) -> str:
    return f"{MARCADOR_INICIO}{ref}\n{chave.strip()}\n{MARCADOR_FIM}{ref}"


def parse_blocos(conteudo: str) -> dict[str, str]:
    """Devolve {ref: corpo} dos blocos '# BEGIN/END adminforge: <ref>' encontrados."""
    out: dict[str, str] = {}
    ref: str | None = None
    buffer: list[str] = []
    for linha in conteudo.splitlines():
        if linha.startswith(MARCADOR_INICIO):
            ref = linha[len(MARCADOR_INICIO):]
            buffer = []
            continue
        if ref is not None and linha.startswith(MARCADOR_FIM):
            if linha[len(MARCADOR_FIM):] == ref:
                out[ref] = "\n".join(buffer)
            ref = None
            buffer = []
            continue
        if ref is not None:
            buffer.append(linha)
    return out


def substituir_bloco(conteudo: str, ref: str, bloco_novo: str) -> str:
    """Substitui o bloco com a ref dada por bloco_novo (vazio = remove). Linhas fora dos
    markers AdminForge sao preservadas."""
    inicio = f"{MARCADOR_INICIO}{ref}"
    fim = f"{MARCADOR_FIM}{ref}"
    out: list[str] = []
    dentro = False
    for linha in conteudo.splitlines():
        if linha == inicio:
            dentro = True
            continue
        if dentro:
            if linha == fim:
                dentro = False
            continue
        out.append(linha)
    if bloco_novo:
        out.append(bloco_novo)
    resultado = "\n".join(out)
    if resultado and not resultado.endswith("\n"):
        resultado += "\n"
    return resultado
