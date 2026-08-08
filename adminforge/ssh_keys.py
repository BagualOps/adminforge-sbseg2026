"""Parse, validate and fingerprint OpenSSH public keys.

No cryptographic verification is performed: a key is accepted if its type
is in TIPOS_SUPORTADOS and its payload is valid base64, not if it decodes
to a structurally valid key blob for that type.
"""
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
    """Split a one-line 'type base64 [comment]' public key into (type, base64, comment).

    Raises FormatoInvalido if the line is empty, has fewer than two
    fields, the type is not in TIPOS_SUPORTADOS, or the payload is not
    valid base64. The comment is optional and returned as "" if absent.
    """
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
    """Return the key's SHA256 fingerprint in OpenSSH's 'SHA256:<base64>' form.

    Matches the format `ssh-keygen -lf` prints, so a fingerprint reported
    here can be compared directly against one pasted from the ssh CLI.
    """
    tipo, blob, _ = parse_chave_publica(raw)
    decoded = base64.b64decode(blob.encode("ascii"))
    digest = hashlib.sha256(decoded).digest()
    b64 = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{b64}"


def chave_canonica(raw: str) -> str:
    """Re-render a public key as 'type base64 comment', normalizing whitespace.

    Used so the same logical key registered with different incidental
    spacing or line endings compares equal and stores identically.
    """
    tipo, blob, comentario = parse_chave_publica(raw)
    return f"{tipo} {blob} {comentario}".strip()
