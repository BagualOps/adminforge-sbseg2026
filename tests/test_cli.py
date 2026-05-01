"""Smoke tests da CLI via main(argv=...) — sem Click."""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from adminforge.cli.main import main

from .conftest import CHAVE_MARINA, HOST_KEY_FAKE


@pytest.fixture
def env(tmp_path: Path, monkeypatch) -> dict:
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("ADMINFORGE_STATE", str(state))
    monkeypatch.setenv("ADMINFORGE_SUPERADMIN", "cristhian")
    return {"state": str(state)}


def run_cli(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(argv)
    return rc, buf.getvalue()


def test_cli_fluxo_basico(env):
    rc, out = run_cli(["admin", "add", "marina", "--nome", "Marina", "--email", "m@e.com"])
    assert rc == 0, out

    rc, out = run_cli(["key", "add", "marina", "--string", CHAVE_MARINA])
    assert rc == 0, out

    rc, _ = run_cli(["group", "create", "sysadmins"])
    assert rc == 0
    rc, _ = run_cli(["group", "add-member", "sysadmins", "marina"])
    assert rc == 0

    rc, _ = run_cli(["server", "add", "web-01", "--ip", "10.0.0.10", "--host-key", HOST_KEY_FAKE])
    assert rc == 0

    rc, _ = run_cli(["server-group", "create", "prod"])
    assert rc == 0
    rc, _ = run_cli(["server-group", "add-member", "prod", "web-01"])
    assert rc == 0

    rc, _ = run_cli(["grant", "sysadmins", "prod", "--nivel", "shell"])
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


def test_cli_help(env, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "AdminForge" in captured.out
    assert "EXEMPLOS" in captured.out
