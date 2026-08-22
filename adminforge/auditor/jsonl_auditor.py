"""JSON Lines, hash-chained implementation of ``IAuditor``.

Each ``Operation`` is appended as one JSON object per line to ``path`` via
``append_line`` (append-only, fsynced, never rewritten in place). Every
record embeds the SHA-256 hash of the *previous* record's payload
(``previous_hash``) plus its own hash (``hash``) computed over everything
except that hash field, forming a hash chain: ``verify_chain`` walks the
file and re-derives each hash to detect any record that was edited, removed,
or reordered after the fact. Because the log is append-only and each new
record's ``id`` and ``previous_hash`` are derived by scanning the existing
file, if the process dies mid-``record`` the partially written line is
simply a truncated/invalid trailing line — everything before it remains
intact and verifiable, and the next ``record`` call recomputes
``next_id``/``previous_hash`` from what's actually on disk.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from adminforge.domain import (
    PermissionLevel,
    Operation,
    OperationStatus,
    SubAction,
    ActionType,
)
from adminforge.exceptions import BrokenChain, NotFound
from adminforge.interfaces.auditor import IAuditor
from adminforge.store.atomic import append_line


class JsonlAuditor(IAuditor):
    """Append-only audit trail stored as one hash-chained JSON object per line.

    Reads (``list_operations``/``find``/``verify_chain``) reparse the whole
    file on every call — there is no in-memory cache or index, so this
    scales linearly with the number of operations recorded so far. Writes
    (``record``) only ever append; no existing line is ever modified or
    removed by this class.
    """

    def __init__(self, path: Path):
        """Bind to the JSONL file at ``path``, creating its parent directory if needed.

        Does not create or touch the file itself; that happens lazily on
        the first ``record`` call via ``append_line``.
        """
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _serialize_sub_action(self, s: SubAction) -> dict:
        """Convert a ``SubAction`` to a JSON-safe dict, dropping fields that are ``None`` or ``""``.

        Enum fields (``action``, ``level``) are converted to their string
        values first. Omitting empty/``None`` fields keeps the on-disk
        record compact and keeps the hash computation stable across
        versions that added optional fields.
        """
        d = asdict(s)
        d["action"] = s.action.value
        if s.level is not None:
            d["level"] = s.level.value
        return {k: v for k, v in d.items() if v is not None and v != ""}

    def _compute_hash(self, payload: dict) -> str:
        """Compute the SHA-256 hex digest of ``payload`` serialized with sorted keys.

        Sorting keys (and using ``default=str`` for anything JSON can't
        natively serialize) makes the hash deterministic regardless of dict
        insertion order, so the same logical payload always hashes the
        same way. ``payload`` must not include the ``hash`` field itself —
        callers are responsible for hashing everything *except* that field.
        """
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _last_hash(self) -> str | None:
        """Return the ``hash`` field of the last line in the file, or ``None`` if the file is empty/absent.

        Scans the entire file to find the last non-blank line; this is the
        chain's current tip and becomes the next record's
        ``previous_hash``.
        """
        ultimo = None
        if not self.path.exists():
            return None
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ultimo = json.loads(line).get("hash")
        return ultimo

    def next_id(self) -> str:
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

    def record(self, operation: Operation) -> None:
        """Compute the chain hash for ``operation`` and append it as one JSON line.

        Mutates ``operation`` in place, setting ``previous_hash`` (the
        current chain tip, from ``_last_hash``) and ``hash`` (computed
        over the serialized payload, itself included afterward) before
        writing. This is the only method that appends to the log; the
        write is fsynced by ``append_line`` before this returns.
        """
        operation.previous_hash = self._last_hash()
        payload = {
            "id": operation.id,
            "timestamp": operation.timestamp.isoformat(timespec="seconds"),
            "superadmin": operation.superadmin,
            "command": operation.command,
            "status": operation.status.value,
            "sub_actions": [self._serialize_sub_action(s) for s in operation.sub_actions],
            "previous_hash": operation.previous_hash,
        }
        operation.hash = self._compute_hash(payload)
        payload["hash"] = operation.hash
        append_line(self.path, json.dumps(payload, ensure_ascii=False))

    def _load(self) -> list[Operation]:
        """Parse the entire file into a list of ``Operation``, in on-disk (append) order.

        Reparses from scratch every call — no caching. Blank lines are
        skipped; each remaining line must be a complete JSON object.
        """
        if not self.path.exists():
            return []
        out: list[Operation] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                sub_actions = [
                    SubAction(
                        server=s.get("server", ""),
                        action=ActionType(s["action"]),
                        credential=s.get("credential"),
                        public_key=s.get("public_key"),
                        username=s.get("username"),
                        level=PermissionLevel(s["level"]) if s.get("level") else None,
                        status=s.get("status", ""),
                        error=s.get("error"),
                        message=s.get("message"),
                    )
                    for s in d.get("sub_actions", [])
                ]
                out.append(
                    Operation(
                        id=d["id"],
                        timestamp=datetime.fromisoformat(d["timestamp"]),
                        superadmin=d["superadmin"],
                        command=d["command"],
                        status=OperationStatus(d["status"]),
                        sub_actions=sub_actions,
                        previous_hash=d.get("previous_hash"),
                        hash=d.get("hash"),
                    )
                )
        return out

    def list_operations(self, limit: int = 50) -> list[Operation]:
        """Return up to ``limit`` most recent operations, newest first (``0``/falsy means all)."""
        ops = self._load()
        return ops[-limit:][::-1] if limit else ops[::-1]

    def list_failures(self, limit: int = 50) -> list[Operation]:
        """Return up to ``limit`` most recent failed or partially-failed operations, newest first."""
        falhos = [
            op
            for op in self._load()
            if op.status in (OperationStatus.FAILURE, OperationStatus.PARTIAL_SUCCESS)
        ]
        return falhos[-limit:][::-1] if limit else falhos[::-1]

    def find(self, id: str) -> Operation | None:
        """Look up a single operation by id, or ``None`` if not found (linear scan of the whole log)."""
        for op in self._load():
            if op.id == id:
                return op
        return None

    def verify_chain(self) -> tuple[bool, str | None]:
        """Walk the log and re-verify every hash link, raising on the first break found.

        For each line, checks that its ``previous_hash`` matches the
        previous line's stored hash and that recomputing the hash over its
        own payload (with the stored ``hash`` popped out first) reproduces
        that stored ``hash``. Raises ``BrokenChain`` as soon as either
        check fails, identifying the offending operation id — it does not
        collect and report all breaks in one pass. Returns ``(True, tip_hash)``
        (or ``(True, None)`` for an empty/absent log) only if the whole
        chain verifies cleanly.
        """
        anterior: str | None = None
        if not self.path.exists():
            return True, None
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                hash_armazenado = d.pop("hash", None)
                if d.get("previous_hash") != anterior:
                    raise BrokenChain(
                        f"prev_hash mismatch at {d.get('id')}"
                    )
                recomputed = self._compute_hash(d)
                if recomputed != hash_armazenado:
                    raise BrokenChain(f"hash mismatch at {d.get('id')}")
                anterior = hash_armazenado
        return True, anterior

    def find_required(self, id: str) -> Operation:
        """Like ``find``, but raise ``NotFound`` instead of returning ``None`` when not found."""
        op = self.find(id)
        if op is None:
            raise NotFound(f"operation '{id}' does not exist")
        return op
