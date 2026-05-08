from datetime import datetime
from pathlib import Path

import pytest

from adminforge.auditor.jsonl_auditor import JsonlAuditor
from adminforge.domain import Operacao, StatusOperacao
from adminforge.exceptions import CadeiaQuebrada


def _op(id: str) -> Operacao:
    return Operacao(
        id=id,
        momento=datetime(2026, 4, 22, 14, 32),
        superadmin="operador",
        comando="user add alice",
        status=StatusOperacao.SUCESSO,
    )


def test_cadeia_de_hashes_integra(tmp_path: Path):
    a = JsonlAuditor(tmp_path / "history.jsonl")
    a.registrar(_op("OP-0001"))
    a.registrar(_op("OP-0002"))
    ok, _ = a.verificar_cadeia()
    assert ok is True


def test_proximo_id_incrementa(tmp_path: Path):
    a = JsonlAuditor(tmp_path / "history.jsonl")
    assert a.proximo_id() == "OP-0001"
    a.registrar(_op("OP-0001"))
    assert a.proximo_id() == "OP-0002"


def test_cadeia_quebrada_em_alteracao_retroativa(tmp_path: Path):
    path = tmp_path / "history.jsonl"
    a = JsonlAuditor(path)
    a.registrar(_op("OP-0001"))
    a.registrar(_op("OP-0002"))
    linhas = path.read_text(encoding="utf-8").splitlines()
    linhas[0] = linhas[0].replace("user add alice", "user add evil")
    path.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    with pytest.raises(CadeiaQuebrada):
        a.verificar_cadeia()


def test_listar_falhas(tmp_path: Path):
    a = JsonlAuditor(tmp_path / "history.jsonl")
    a.registrar(_op("OP-0001"))
    op2 = _op("OP-0002")
    op2.status = StatusOperacao.FALHA
    a.registrar(op2)
    falhos = a.listar_falhas()
    assert len(falhos) == 1
    assert falhos[0].id == "OP-0002"
