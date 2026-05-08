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


def test_cli_add_member_aceita_virgula(env):
    for u in ("alice", "bob", "carla"):
        run_cli(["user", "add", "--username", u, "--name", u.title(), "--email", f"{u}@e.com"])
    run_cli(["user-group", "create", "--name", "sa"])
    rc, _ = run_cli(["user-group", "add-member", "--group", "sa", "--username", "alice,bob,carla"])
    assert rc == 0
    rc, out = run_cli(["user-group", "list"])
    assert rc == 0
    assert "alice" in out and "bob" in out and "carla" in out


def test_cli_add_member_misto_virgula_e_espaco(env):
    for u in ("alice", "bob", "carla", "diego"):
        run_cli(["user", "add", "--username", u, "--name", u.title(), "--email", f"{u}@e.com"])
    run_cli(["user-group", "create", "--name", "sa"])
    rc, _ = run_cli(["user-group", "add-member", "--group", "sa", "--username", "alice,bob", "carla,diego"])
    assert rc == 0
    rc, out = run_cli(["user-group", "list"])
    assert rc == 0
    for u in ("alice", "bob", "carla", "diego"):
        assert u in out


def test_cli_apply_verify_dry_run(env):
    # cenario: estado declarado, DryRun.ler_authorized_keys == "" => tudo divergente
    run_cli(["user", "add", "--username", "alice", "--name", "A", "--email", "a@e.com"])
    run_cli(["user", "key", "add", "--username", "alice", "--string", CHAVE_ALICE])
    run_cli(["user-group", "create", "--name", "sa"])
    run_cli(["user-group", "add-member", "--group", "sa", "--username", "alice"])
    run_cli(["server", "add", "--hostname", "web-01", "--ip", "10.0.0.10", "--host-key", HOST_KEY_FAKE])
    run_cli(["server-group", "create", "--name", "prod"])
    run_cli(["server-group", "add-member", "--group", "prod", "--hostname", "web-01"])
    run_cli(["grant", "--user-group", "sa", "--server-group", "prod", "--level", "shell"])
    run_cli(["apply", "--yes", "--dry-run"])

    rc, out = run_cli(["apply", "verify", "--dry-run"])
    # DryRun retorna "" → blocos nao existem real → divergencia → rc=2
    assert rc == 2
    assert "divergences" in out
    assert "declared but not present" in out


def test_cli_apply_diff(env):
    run_cli(["user", "add", "--username", "alice", "--name", "A", "--email", "a@e.com"])
    run_cli(["user", "key", "add", "--username", "alice", "--string", CHAVE_ALICE])
    run_cli(["user-group", "create", "--name", "sa"])
    run_cli(["user-group", "add-member", "--group", "sa", "--username", "alice"])
    run_cli(["server", "add", "--hostname", "web-01", "--ip", "10.0.0.10", "--host-key", HOST_KEY_FAKE])
    run_cli(["server-group", "create", "--name", "prod"])
    run_cli(["server-group", "add-member", "--group", "prod", "--hostname", "web-01"])
    run_cli(["grant", "--user-group", "sa", "--server-group", "prod", "--level", "shell"])

    rc, out = run_cli(["apply", "--yes", "--dry-run", "--diff"])
    assert rc == 0
    assert "Diff" in out
    assert "web-01:alice" in out
    # com DryRun.ler_authorized_keys=='', tudo eh nova adicao
    assert "+# BEGIN adminforge: alice:" in out


def test_cli_dump_json(env):
    run_cli(["user", "add", "--username", "alice", "--name", "A", "--email", "a@e.com"])
    run_cli(["user", "key", "add", "--username", "alice", "--string", CHAVE_ALICE])
    run_cli(["user-group", "create", "--name", "sa"])
    run_cli(["user-group", "add-member", "--group", "sa", "--username", "alice"])
    run_cli(["server", "add", "--hostname", "web-01", "--ip", "10.0.0.10", "--host-key", HOST_KEY_FAKE])
    run_cli(["server-group", "create", "--name", "prod"])
    run_cli(["server-group", "add-member", "--group", "prod", "--hostname", "web-01"])
    run_cli(["grant", "--user-group", "sa", "--server-group", "prod", "--level", "shell"])

    import json as _json
    rc, out = run_cli(["dump", "--format", "json"])
    assert rc == 0
    data = _json.loads(out)
    assert {u["username"] for u in data["users"]} == {"alice"}
    assert data["user_groups"][0]["members"] == ["alice"]
    assert data["permissions"][0]["level"] == "shell"


def test_cli_dump_table(env):
    run_cli(["user", "add", "--username", "alice", "--name", "A", "--email", "a@e.com"])
    rc, out = run_cli(["dump"])
    assert rc == 0
    assert "Users" in out and "alice" in out


def test_cli_permission_list_update_delete(env):
    run_cli(["user-group", "create", "--name", "sa"])
    run_cli(["server-group", "create", "--name", "prod"])

    rc, out = run_cli(["permission", "list"])
    assert rc == 0
    assert "(empty)" in out or "USER_GROUP" in out

    rc, _ = run_cli(["permission", "update", "--user-group", "sa", "--server-group", "prod", "--level", "shell"])
    assert rc == 0

    rc, out = run_cli(["permission", "list"])
    assert rc == 0
    assert "sa" in out and "prod" in out and "shell" in out

    rc, _ = run_cli(["permission", "update", "--user-group", "sa", "--server-group", "prod", "--level", "sudo"])
    assert rc == 0
    rc, out = run_cli(["permission", "list"])
    assert rc == 0
    assert "sudo" in out and "shell" not in out.split("sudo")[1]

    rc, _ = run_cli(["permission", "delete", "--user-group", "sa", "--server-group", "prod", "--yes"])
    assert rc == 0
    rc, out = run_cli(["permission", "list"])
    assert "sa" not in out or "prod" not in out


def test_cli_help(env, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "AdminForge" in captured.out
    assert "EXAMPLES" in captured.out
