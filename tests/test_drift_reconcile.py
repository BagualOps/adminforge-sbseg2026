"""Regression for the 3 defects in the 'manual deletion desyncs Store vs server' scenario.

P1 verify reported a false OK on an orphan block left by userdel without -r.
P2 apply did not re-apply after a manual deletion (the Store still believes it is installed).
P3 _write_authorized_keys used install /dev/stdin (breaks on minimal coreutils).
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from adminforge import authorized_keys as ak
from adminforge import ssh_keys
from adminforge.auditor.jsonl_auditor import JsonlAuditor
from adminforge.cli.main import main
from adminforge.core.core import Core
from adminforge.deployer.dry_run import DryRunDeployer
from adminforge.deployer.ssh_deployer import SSHDeployer
from adminforge.domain import PermissionLevel, Server, ActionType
from adminforge.store.json_store import JsonStore

from .conftest import KEY_ALICE, HOST_KEY_FAKE

FP_ALICE = ssh_keys.fingerprint(KEY_ALICE)
REF_ALICE = f"alice:{FP_ALICE}"
KEY_STALE = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIStale0000000000000000000000000000 alice@old"


def _setup_cli_state(state: Path):
    def run(argv):
        return _run_cli_with_state(state, argv)

    run(["user", "add", "--username", "alice", "--name", "A", "--email", "a@e.com"])
    run(["user", "key", "add", "--username", "alice", "--string", KEY_ALICE])
    run(["user-group", "create", "--name", "sa"])
    run(["user-group", "add-member", "--group", "sa", "--username", "alice"])
    run(["server", "add", "--hostname", "web-01", "--ip", "10.0.0.10", "--host-key", HOST_KEY_FAKE])
    run(["server-group", "create", "--name", "prod"])
    run(["server-group", "add-member", "--group", "prod", "--hostname", "web-01"])
    run(["permission", "grant", "--user-group", "sa", "--server-group", "prod", "--level", "shell"])


def _run_cli_with_state(state: Path, argv: list[str]) -> tuple[int, str]:
    import os

    old_state = os.environ.get("ADMINFORGE_STATE")
    os.environ["ADMINFORGE_STATE"] = str(state)
    os.environ["ADMINFORGE_SUPERADMIN"] = "operador"
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                rc = main(argv)
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 2
    finally:
        if old_state is None:
            os.environ.pop("ADMINFORGE_STATE", None)
        else:
            os.environ["ADMINFORGE_STATE"] = old_state
    return rc, out.getvalue() + err.getvalue()


def _core(state_dir: Path, deployer) -> Core:
    store = JsonStore(state_dir)
    n = Core(store, JsonlAuditor(state_dir / "history.jsonl"), deployer, "operador")
    n.cadastrar_user("alice", "Alice", "m@e.com")
    n.register_key("alice", KEY_ALICE)
    n.create_user_group("sa")
    n.add_member_user_group("sa", "alice")
    n.register_server("web-01", "10.0.0.10", 22, HOST_KEY_FAKE)
    n.create_server_group("prod")
    n.add_member_server_group("prod", "web-01")
    n.grant("sa", "prod", PermissionLevel.SHELL)
    return n


class _FakeDeployer(DryRunDeployer):
    def __init__(self, contas: set[str], ak_por_user: dict[str, str]):
        super().__init__()
        self._contas = contas
        self._ak = ak_por_user

    def inspect(self, server: Server) -> dict:
        return {
            "users": [
                {
                    "name": u,
                    "uid": 1000,
                    "shell": "/bin/bash",
                    "categoria": "human",
                    "groups": [],
                    "sudo": [],
                }
                for u in sorted(self._contas)
            ],
            "groups": [],
            "servicos": [],
            "sudoers_arquivos": [],
            "sudoers_regras": [],
        }

    def read_authorized_keys(self, server: Server, username: str) -> tuple[str, bool]:
        return self._ak.get(username, ""), True


# --- P1: verify -----------------------------------------------------------
def test_verify_conta_ausente_nao_da_ok(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    _setup_cli_state(state)
    _run_cli_with_state(state, ["apply", "--yes", "--dry-run"])

    stale_block = ak.block(REF_ALICE, KEY_ALICE)
    from adminforge.deployer.dry_run import DryRunDeployer as DRD

    monkeypatch.setattr(
        DRD,
        "inspect",
        lambda self, s: {
            "users": [
                {
                    "name": "root",
                    "uid": 0,
                    "shell": "/bin/bash",
                    "categoria": "system",
                    "groups": [],
                    "sudo": [],
                }
            ],
            "groups": [],
            "servicos": [],
            "sudoers_arquivos": [],
            "sudoers_regras": [],
        },
    )
    monkeypatch.setattr(DRD, "read_authorized_keys", lambda self, s, u: (stale_block, True))

    rc, out = _run_cli_with_state(state, ["apply", "verify", "--dry-run"])
    assert rc == 2, out
    assert "account missing" in out
    assert REF_ALICE in out


def test_verify_account_present_with_block_is_ok(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    _setup_cli_state(state)
    _run_cli_with_state(state, ["apply", "--yes", "--dry-run"])

    block = ak.block(REF_ALICE, KEY_ALICE)
    from adminforge.deployer.dry_run import DryRunDeployer as DRD

    monkeypatch.setattr(
        DRD,
        "inspect",
        lambda self, s: {
            "users": [
                {
                    "name": "root",
                    "uid": 0,
                    "shell": "/bin/bash",
                    "categoria": "system",
                    "groups": [],
                    "sudo": [],
                },
                {
                    "name": "alice",
                    "uid": 1000,
                    "shell": "/bin/bash",
                    "categoria": "human",
                    "groups": [],
                    "sudo": [],
                },
            ],
            "groups": [],
            "servicos": [],
            "sudoers_arquivos": [],
            "sudoers_regras": [],
        },
    )
    monkeypatch.setattr(DRD, "read_authorized_keys", lambda self, s, u: (block, True))

    rc, out = _run_cli_with_state(state, ["apply", "verify", "--dry-run"])
    assert rc == 0, out
    assert REF_ALICE in out


# --- P2: force / reconcile ------------------------------------------------
def test_force_reemite_add_mesmo_em_sync(state_dir: Path):
    n = _core(state_dir, DryRunDeployer())
    assert n.apply().status.value == "success"
    assert n.preview() == []

    pending = n.preview(force=True)
    assert len(pending) == 1
    assert pending[0].action == ActionType.ADD_KEY
    assert pending[0].username == "alice"


def test_reconcile_recreates_manually_removed_key(state_dir: Path):
    deployer = _FakeDeployer({"alice"}, {"alice": ""})
    n = _core(state_dir, deployer)
    sv = n.store.get_server("web-01")
    sv.installed_keys = [{"ref": REF_ALICE, "username": "alice", "level": "shell"}]
    n.store.save_server(sv)

    assert n.preview() == []
    pending = n.preview(reconcile=True)
    assert len(pending) == 1
    assert pending[0].action == ActionType.ADD_KEY
    assert pending[0].credential == REF_ALICE


def test_reconcile_removes_orphan_block(state_dir: Path):
    ref_orfao = "alice:SHA256:0000000000000000000000000000000000000000000"
    deployer = _FakeDeployer({"alice"}, {"alice": ak.block(ref_orfao, KEY_STALE)})
    n = _core(state_dir, deployer)
    sv = n.store.get_server("web-01")
    sv.installed_keys = [{"ref": REF_ALICE, "username": "alice", "level": "shell"}]
    n.store.save_server(sv)

    acoes = {(s.action, s.credential) for s in n.preview(reconcile=True)}
    assert (ActionType.ADD_KEY, REF_ALICE) in acoes
    assert (ActionType.REMOVE_KEY, ref_orfao) in acoes


def test_force_e_reconcile_sao_exclusivos_na_cli(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    rc, out = _run_cli_with_state(state, ["apply", "--force", "--reconcile", "--dry-run"])
    assert rc != 0
    assert "not allowed" in out.lower()


# --- P3: _write_authorized_keys ---------------------------------------
def test_write_authorized_keys_avoids_dev_stdin(tmp_path: Path):
    capturado: list[str] = []
    d = SSHDeployer(tmp_path / "id", tmp_path / "known_hosts")
    d._run_ssh = lambda server, command: capturado.append(command) or (0, "", "")  # type: ignore
    server = Server(hostname="web-01", ipv4="10.0.0.1", host_key="ssh-ed25519 AAAA x")

    d._write_authorized_keys(server, "alice", "conteudo")

    cmd = capturado[0]
    assert "/dev/stdin" not in cmd
    assert "tee" in cmd and "sudo mv" in cmd
    assert "chmod 600" in cmd and "chown" in cmd and ".bak" in cmd


def test_write_authorized_keys_propagates_error(tmp_path: Path):
    d = SSHDeployer(tmp_path / "id", tmp_path / "known_hosts")
    d._run_ssh = lambda server, command: (1, "", "install: No such file or directory")  # type: ignore
    server = Server(hostname="web-01", ipv4="10.0.0.1", host_key="ssh-ed25519 AAAA x")

    with pytest.raises(RuntimeError, match="failed to write authorized_keys"):
        d._write_authorized_keys(server, "alice", "x")
