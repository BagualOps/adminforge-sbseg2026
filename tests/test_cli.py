"""Smoke tests da CLI via main(argv=...) — sem Click."""
from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from adminforge.cli.main import main

from .conftest import CHAVE_ALICE, HOST_KEY_FAKE


@pytest.fixture
def env(tmp_path: Path, monkeypatch) -> dict:
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("ADMINFORGE_STATE", str(state))
    monkeypatch.setenv("ADMINFORGE_SUPERADMIN", "operador")
    return {"state": str(state)}


def run_cli(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(argv)
    return rc, buf.getvalue()


def test_cli_fluxo_basico(env):
    rc, out = run_cli(["user", "add", "--username", "alice", "--name", "Alice", "--email", "m@e.com"])
    assert rc == 0, out

    rc, out = run_cli(["user", "key", "add", "--username", "alice", "--string", CHAVE_ALICE])
    assert rc == 0, out

    rc, _ = run_cli(["user-group", "create", "--name", "sysadmins"])
    assert rc == 0
    rc, _ = run_cli(["user-group", "add-member", "--group", "sysadmins", "--username", "alice"])
    assert rc == 0

    rc, _ = run_cli(["server", "add", "--hostname", "web-01", "--ip", "10.0.0.10", "--host-key", HOST_KEY_FAKE])
    assert rc == 0

    rc, _ = run_cli(["server-group", "create", "--name", "prod"])
    assert rc == 0
    rc, _ = run_cli(["server-group", "add-member", "--group", "prod", "--hostname", "web-01"])
    assert rc == 0

    rc, _ = run_cli(["grant", "--user-group", "sysadmins", "--server-group", "prod", "--level", "shell"])
    assert rc == 0

    rc, out = run_cli(["preview"])
    assert rc == 0
    assert "web-01" in out

    rc, out = run_cli(["apply", "--yes", "--dry-run"])
    assert rc == 0
    assert "SUCESSO" in out.upper()

    rc, out = run_cli(["history", "list"])
    assert rc == 0
    assert "OP-" in out

    rc, out = run_cli(["history", "verify"])
    assert rc == 0
    assert "integra" in out.lower() or "OK" in out


def test_cli_add_member_n_de_uma_vez(env):
    rc, _ = run_cli(["user", "add", "--username", "alice", "--name", "A", "--email", "a@e.com"])
    assert rc == 0
    rc, _ = run_cli(["user", "add", "--username", "bob", "--name", "B", "--email", "b@e.com"])
    assert rc == 0
    rc, _ = run_cli(["user-group", "create", "--name", "sa"])
    assert rc == 0
    rc, _ = run_cli(["user-group", "add-member", "--group", "sa", "--username", "alice", "bob"])
    assert rc == 0
    rc, out = run_cli(["user-group", "list"])
    assert rc == 0
    assert "alice" in out and "bob" in out


def test_cli_help(env, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "AdminForge" in captured.out
    assert "EXEMPLOS" in captured.out
