"""Tests for the append-only audit log: hash-chain integrity, id allocation, and failure listing."""

from datetime import datetime
from pathlib import Path

import pytest

from adminforge.auditor.jsonl_auditor import JsonlAuditor
from adminforge.domain import Operation, OperationStatus
from adminforge.exceptions import BrokenChain


def _op(id: str) -> Operation:
    return Operation(
        id=id,
        timestamp=datetime(2026, 4, 22, 14, 32),
        superadmin="operador",
        command="user add alice",
        status=OperationStatus.SUCCESS,
    )


def test_hash_chain_intact(tmp_path: Path):
    a = JsonlAuditor(tmp_path / "history.jsonl")
    a.record(_op("OP-0001"))
    a.record(_op("OP-0002"))
    ok, _ = a.verify_chain()
    assert ok is True


def test_proximo_id_incrementa(tmp_path: Path):
    a = JsonlAuditor(tmp_path / "history.jsonl")
    assert a.next_id() == "OP-0001"
    a.record(_op("OP-0001"))
    assert a.next_id() == "OP-0002"


def test_broken_chain_on_retroactive_change(tmp_path: Path):
    path = tmp_path / "history.jsonl"
    a = JsonlAuditor(path)
    a.record(_op("OP-0001"))
    a.record(_op("OP-0002"))
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace("user add alice", "user add evil")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(BrokenChain):
        a.verify_chain()


def test_list_failures(tmp_path: Path):
    a = JsonlAuditor(tmp_path / "history.jsonl")
    a.record(_op("OP-0001"))
    op2 = _op("OP-0002")
    op2.status = OperationStatus.FAILURE
    a.record(op2)
    falhos = a.list_failures()
    assert len(falhos) == 1
    assert falhos[0].id == "OP-0002"