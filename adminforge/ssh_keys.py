from __future__ import annotations

import base64
import hashlib

from adminforge.exceptions import FormatoInvalido

TIPOS_SUPORTADOS = (
    "ssh-ed25519",
    "ssh-rsa",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
)


def parse_chave_publica(raw: str) -> tuple[str, str, str]:
    raw = raw.strip()
    if not raw:
        raise FormatoInvalido("empty key")
    partes = raw.split(None, 2)
    if len(partes) < 2:
        raise FormatoInvalido("key requires type and base64 payload")
    tipo, blob, comentario = partes[0], partes[1], partes[2] if len(partes) == 3 else ""
    if tipo not in TIPOS_SUPORTADOS:
        raise FormatoInvalido(f"unsupported key type: {tipo}")
    try:
        base64.b64decode(blob, validate=True)
    except Exception as e:
        raise FormatoInvalido(f"invalid base64 payload: {e}") from e
    return tipo, blob, comentario


def fingerprint(raw: str) -> str:
    tipo, blob, _ = parse_chave_publica(raw)
    decoded = base64.b64decode(blob.encode("ascii"))
    digest = hashlib.sha256(decoded).digest()
    b64 = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{b64}"


def chave_canonica(raw: str) -> str:
    tipo, blob, comentario = parse_chave_publica(raw)
    return f"{tipo} {blob} {comentario}".strip()
