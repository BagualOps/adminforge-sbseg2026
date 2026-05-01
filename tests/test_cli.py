"""Smoke tests da CLI via Click testing utilities."""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from adminforge.cli.main import cli

from .conftest import CHAVE_MARINA, HOST_KEY_FAKE


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    state = tmp_path / "state"
    state.mkdir()
    return {
        "ADMINFORGE_STATE": str(state),
        "ADMINFORGE_SUPERADMIN": "cristhian",
        "PATH": "/usr/bin:/bin",
    }


def run(env: dict[str, str], *args: str) -> str:
    runner = CliRunner()
    result = runner.invoke(cli, list(args), env=env, catch_exceptions=False)
    if result.exit_code not in (0, 1):
        print(result.output)
    assert result.exit_code in (0, 1, 2), f"saida inesperada: {result.output}"
    return result.output


def test_cli_fluxo_basico(env):
    runner = CliRunner()
    r = runner.invoke(cli, ["admin", "add", "marina", "--nome", "Marina", "--email", "m@e.com"], env=env)
    assert r.exit_code == 0, r.output

    r = runner.invoke(cli, ["key", "add", "marina", "--string", CHAVE_MARINA], env=env)
    assert r.exit_code == 0, r.output

    r = runner.invoke(cli, ["group", "create", "sysadmins"], env=env)
    assert r.exit_code == 0, r.output

    r = runner.invoke(cli, ["group", "add-member", "sysadmins", "marina"], env=env)
    assert r.exit_code == 0, r.output

    r = runner.invoke(
        cli,
        ["server", "add", "web-01", "--ip", "10.0.0.10", "--host-key", HOST_KEY_FAKE],
        env=env,
    )
    assert r.exit_code == 0, r.output

    r = runner.invoke(cli, ["server-group", "create", "prod"], env=env)
    assert r.exit_code == 0, r.output
    r = runner.invoke(cli, ["server-group", "add-member", "prod", "web-01"], env=env)
    assert r.exit_code == 0, r.output

    r = runner.invoke(cli, ["grant", "sysadmins", "prod", "--nivel", "shell"], env=env)
    assert r.exit_code == 0, r.output

    r = runner.invoke(cli, ["preview"], env=env)
    assert r.exit_code == 0, r.output
    assert "web-01" in r.output

    r = runner.invoke(cli, ["apply", "--yes", "--dry-run"], env=env)
    assert r.exit_code == 0, r.output
    assert "SUCESSO" in r.output.upper()

    r = runner.invoke(cli, ["history", "list"], env=env)
    assert r.exit_code == 0
    assert "OP-" in r.output

    r = runner.invoke(cli, ["history", "verify"], env=env)
    assert r.exit_code == 0
    assert "integra" in r.output.lower() or "OK" in r.output


def test_cli_help_em_pt(env):
    runner = CliRunner()
    r = runner.invoke(cli, ["--help"], env=env)
    assert r.exit_code == 0
    assert "AdminForge" in r.output
    assert "EXEMPLOS" in r.output
