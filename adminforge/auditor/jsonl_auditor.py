"""JSON Lines, hash-chained implementation of ``IAuditor``.

Each ``Operacao`` is appended as one JSON object per line to ``path`` via
``append_line`` (append-only, fsynced, never rewritten in place). Every
record embeds the SHA-256 hash of the *previous* record's payload
(``hash_anterior``) plus its own hash (``hash``) computed over everything
except that hash field, forming a hash chain: ``verificar_cadeia`` walks the
file and re-derives each hash to detect any record that was edited, removed,
or reordered after the fact. Because the log is append-only and each new
record's ``id`` and ``hash_anterior`` are derived by scanning the existing
file, if the process dies mid-``registrar`` the partially written line is
simply a truncated/invalid trailing line — everything before it remains
intact and verifiable, and the next ``registrar`` call recomputes
``proximo_id``/``hash_anterior`` from what's actually on disk.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from adminforge.domain import (
    NivelPermissao,
    Operacao,
    StatusOperacao,
    Subacao,
    TipoAcao,
)
from adminforge.exceptions import CadeiaQuebrada, NaoExiste
from adminforge.interfaces.auditor import IAuditor
from adminforge.store.atomic import append_line


class JsonlAuditor(IAuditor):
    """Append-only audit trail stored as one hash-chained JSON object per line.

    Reads (``listar``/``buscar``/``verificar_cadeia``) reparse the whole
    file on every call — there is no in-memory cache or index, so this
    scales linearly with the number of operations recorded so far. Writes
    (``registrar``) only ever append; no existing line is ever modified or
    removed by this class.
    """

    def __init__(self, path: Path):
        """Bind to the JSONL file at ``path``, creating its parent directory if needed.

        Does not create or touch the file itself; that happens lazily on
        the first ``registrar`` call via ``append_line``.
        """
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _serializar_subacao(self, s: Subacao) -> dict:
        """Convert a ``Subacao`` to a JSON-safe dict, dropping fields that are ``None`` or ``""``.

        Enum fields (``acao``, ``nivel``) are converted to their string
        values first. Omitting empty/``None`` fields keeps the on-disk
        record compact and keeps the hash computation stable across
        versions that added optional fields.
        """
        d = asdict(s)
        d["acao"] = s.acao.value
        if s.nivel is not None:
            d["nivel"] = s.nivel.value
        return {k: v for k, v in d.items() if v is not None and v != ""}

    def _calcular_hash(self, payload: dict) -> str:
        """Compute the SHA-256 hex digest of ``payload`` serialized with sorted keys.

        Sorting keys (and using ``default=str`` for anything JSON can't
        natively serialize) makes the hash deterministic regardless of dict
        insertion order, so the same logical payload always hashes the
        same way. ``payload`` must not include the ``hash`` field itself —
        callers are responsible for hashing everything *except* that field.
        """
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _ultimo_hash(self) -> str | None:
        """Return the ``hash`` field of the last line in the file, or ``None`` if the file is empty/absent.

        Scans the entire file to find the last non-blank line; this is the
        chain's current tip and becomes the next record's
        ``hash_anterior``.
        """
        ultimo = None
        if not self.path.exists():
            return None
        with self.path.open("r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                ultimo = json.loads(linha).get("hash")
        return ultimo

    def proximo_id(self) -> str:
        """Return the next sequential operation id as ``OP-000N`` (1-indexed, zero-padded to 4 digits).

        Derived by counting existing lines, not from a stored counter, so
        it stays consistent with whatever is actually on disk even if a
        previous run crashed mid-write.
        """
        contador = 1
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as f:
                contador = sum(1 for _ in f) + 1
        return f"OP-{contador:04d}"

    def registrar(self, operacao: Operacao) -> None:
        """Compute the chain hash for ``operacao`` and append it as one JSON line.

        Mutates ``operacao`` in place, setting ``hash_anterior`` (the
        current chain tip, from ``_ultimo_hash``) and ``hash`` (computed
        over the serialized payload, itself included afterward) before
        writing. This is the only method that appends to the log; the
        write is fsynced by ``append_line`` before this returns.
        """
        operacao.hash_anterior = self._ultimo_hash()
        payload = {
            "id": operacao.id,
            "momento": operacao.momento.isoformat(timespec="seconds"),
            "superadmin": operacao.superadmin,
            "comando": operacao.comando,
            "status": operacao.status.value,
            "subacoes": [self._serializar_subacao(s) for s in operacao.subacoes],
            "hash_anterior": operacao.hash_anterior,
        }
        operacao.hash = self._calcular_hash(payload)
        payload["hash"] = operacao.hash
        append_line(self.path, json.dumps(payload, ensure_ascii=False))

    def _carregar(self) -> list[Operacao]:
        """Parse the entire file into a list of ``Operacao``, in on-disk (append) order.

        Reparses from scratch every call — no caching. Blank lines are
        skipped; each remaining line must be a complete JSON object.
        """
        if not self.path.exists():
            return []
        out: list[Operacao] = []
        with self.path.open("r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                d = json.loads(linha)
                subacoes = [
                    Subacao(
                        servidor=s.get("servidor", ""),
                        acao=TipoAcao(s["acao"]),
                        credencial=s.get("credencial"),
                        chave_publica=s.get("chave_publica"),
                        username=s.get("username"),
                        nivel=NivelPermissao(s["nivel"]) if s.get("nivel") else None,
                        status=s.get("status", ""),
                        erro=s.get("erro"),
                        mensagem=s.get("mensagem"),
                    )
                    for s in d.get("subacoes", [])
                ]
                out.append(
                    Operacao(
                        id=d["id"],
                        momento=datetime.fromisoformat(d["momento"]),
                        superadmin=d["superadmin"],
                        comando=d["comando"],
                        status=StatusOperacao(d["status"]),
                        subacoes=subacoes,
                        hash_anterior=d.get("hash_anterior"),
                        hash=d.get("hash"),
                    )
                )
        return out

    def listar(self, limite: int = 50) -> list[Operacao]:
        """Return up to ``limite`` most recent operations, newest first (``0``/falsy means all)."""
        ops = self._carregar()
        return ops[-limite:][::-1] if limite else ops[::-1]

    def listar_falhas(self, limite: int = 50) -> list[Operacao]:
        """Return up to ``limite`` most recent failed or partially-failed operations, newest first."""
        falhos = [
            op
            for op in self._carregar()
            if op.status in (StatusOperacao.FALHA, StatusOperacao.SUCESSO_PARCIAL)
        ]
        return falhos[-limite:][::-1] if limite else falhos[::-1]

    def buscar(self, id: str) -> Operacao | None:
        """Look up a single operation by id, or ``None`` if not found (linear scan of the whole log)."""
        for op in self._carregar():
            if op.id == id:
                return op
        return None

    def verificar_cadeia(self) -> tuple[bool, str | None]:
        """Walk the log and re-verify every hash link, raising on the first break found.

        For each line, checks that its ``hash_anterior`` matches the
        previous line's stored hash and that recomputing the hash over its
        own payload (with the stored ``hash`` popped out first) reproduces
        that stored ``hash``. Raises ``CadeiaQuebrada`` as soon as either
        check fails, identifying the offending operation id — it does not
        collect and report all breaks in one pass. Returns ``(True, tip_hash)``
        (or ``(True, None)`` for an empty/absent log) only if the whole
        chain verifies cleanly.
        """
        anterior: str | None = None
        if not self.path.exists():
            return True, None
        with self.path.open("r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                d = json.loads(linha)
                hash_armazenado = d.pop("hash", None)
                if d.get("hash_anterior") != anterior:
                    raise CadeiaQuebrada(
                        f"prev_hash mismatch at {d.get('id')}"
                    )
                recalculado = self._calcular_hash(d)
                if recalculado != hash_armazenado:
                    raise CadeiaQuebrada(f"hash mismatch at {d.get('id')}")
                anterior = hash_armazenado
        return True, anterior

    def buscar_obrigatorio(self, id: str) -> Operacao:
        """Like ``buscar``, but raise ``NaoExiste`` instead of returning ``None`` when not found."""
        op = self.buscar(id)
        if op is None:
            raise NaoExiste(f"operation '{id}' does not exist")
        return op
