"""End-to-end integration test against the Docker lab.

Brings up 3 Debian containers via docker compose, runs the whole flow
(registration -> groups -> grant -> apply -> revocation -> apply) against
them, inspects inside the containers to check the real outcome, and tears
the lab down.

Opt-in: only runs with ADMINFORGE_INTEGRATION=1 or pytest -m integration.
Skips automatically when docker is unavailable.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from adminforge.auditor.jsonl_auditor import JsonlAuditor
from adminforge.core.core import Core
from adminforge.deployer.ssh_deployer import SSHDeployer
from adminforge.domain import PermissionLevel, OperationStatus, ActionType
from adminforge.store.json_store import JsonStore


REPO = Path(__file__).resolve().parent.parent.parent
LAB_DIR = REPO / "infra" / "testlab"
COMPOSE_FILE = LAB_DIR / "docker-compose.yml"
KEYS_DIR = LAB_DIR / "keys"

PORTAS = {"web-01": 2201, "web-02": 2202, "db-03": 2203}

KEY_ALICE = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGZdz3+gT+Md3OSv00ku0Q9j+QUvhU3iRA9eCkP9F1Tc alice@laptop"
)
KEY_BOB = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIE9NK1qj7m9rwGzN9bM4LqXz0Z8c9zN0R1aB9fEdC7Yk bob@laptop"
)
KEY_CAROL = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDcqfHw6TYOiNA4NqAkplI5+ZaNsZcV8LT1pQqRN+BFD carol@laptop"
)


def _run_verify(state_dir: Path, priv_key: Path) -> tuple[int, str]:
    """Run `apply verify` through the CLI against a state_dir, using the lab key."""
    import io as _io
    from contextlib import redirect_stdout

    from adminforge.cli.main import main

    env_keys = ("ADMINFORGE_STATE", "ADMINFORGE_SSH_KEY", "ADMINFORGE_SSH_USER", "ADMINFORGE_SUPERADMIN")
    saved = {k: os.environ.get(k) for k in env_keys}
    os.environ["ADMINFORGE_STATE"] = str(state_dir)
    os.environ["ADMINFORGE_SSH_KEY"] = str(priv_key)
    os.environ["ADMINFORGE_SSH_USER"] = "adminforge"
    os.environ["ADMINFORGE_SUPERADMIN"] = "operador"
    buf = _io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = main(["apply", "verify"])
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return rc, buf.getvalue()


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        subprocess.run(["docker", "compose", "version"], capture_output=True, check=True, timeout=10)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


pytestmark = pytest.mark.skipif(
    os.environ.get("ADMINFORGE_INTEGRATION") != "1",
    reason="set ADMINFORGE_INTEGRATION=1 para rodar (requer docker)",
)


@pytest.fixture(scope="module")
def lab(tmp_path_factory):
    if not _docker_available():
        pytest.skip("docker compose nao disponivel")

    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    priv_key = KEYS_DIR / "adminforge_id"
    pub_key = KEYS_DIR / "adminforge_id.pub"
    if not priv_key.exists():
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(priv_key), "-C", "adminforge@testlab", "-q"],
            check=True,
        )

    local_priv_key = tmp_path_factory.mktemp("keys") / "adminforge_id"
    local_priv_key.write_bytes(priv_key.read_bytes())
    os.chmod(local_priv_key, 0o600)

    env = {**os.environ, "ADMINFORGE_PUBKEY": pub_key.read_text().strip()}

    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"],
        env=env, capture_output=True, timeout=60,
    )
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--build"],
        env=env, check=True, timeout=300,
    )

    for _ in range(30):
        proc = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
             "-o", "BatchMode=yes", "-o", "ConnectTimeout=2",
             "-i", str(local_priv_key), "-p", "2201", "adminforge@127.0.0.1", "true"],
            capture_output=True,
        )
        if proc.returncode == 0:
            break
        time.sleep(1)
    else:
        subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"], env=env)
        pytest.fail("containers nao ficaram prontos em 30s")

    yield {"priv_key": local_priv_key, "env": env}

    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"],
        env=env, capture_output=True, timeout=60,
    )


def _capturar_host_key(porta: int) -> str:
    proc = subprocess.run(
        ["ssh-keyscan", "-T", "5", "-t", "ed25519", "-p", str(porta), "127.0.0.1"],
        capture_output=True, text=True, timeout=10,
    )
    for line in proc.stdout.splitlines():
        partes = line.strip().split(None, 1)
        if len(partes) == 2 and partes[1].startswith("ssh-ed25519"):
            return partes[1]
    raise RuntimeError(f"falha ao capturar host_key na porta {porta}")


def _exec_container(container_name: str, *cmd: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["docker", "exec", container_name, *cmd],
        capture_output=True, text=True, timeout=30,
    )
    return proc.returncode, proc.stdout


def _make_core(state_dir: Path, priv_key: Path) -> Core:
    store = JsonStore(state_dir)
    auditor = JsonlAuditor(state_dir / "history.jsonl")
    deployer = SSHDeployer(
        private_key_path=priv_key,
        known_hosts_path=state_dir / "known_hosts",
        service_user="adminforge",
        timeout=10,
    )
    return Core(store, auditor, deployer, superadmin="operador")


def test_full_flow_in_containers(lab, tmp_path):
    core = _make_core(tmp_path / "state", lab["priv_key"])

    assert core.cadastrar_user("alice", "Alice", "m@e.com").status == OperationStatus.SUCCESS
    assert core.cadastrar_user("bob", "Bob", "bob@e.com").status == OperationStatus.SUCCESS
    assert core.register_key("alice", KEY_ALICE).status == OperationStatus.SUCCESS
    assert core.register_key("bob", KEY_BOB).status == OperationStatus.SUCCESS

    core.create_user_group("sysadmins")
    core.add_member_user_group("sysadmins", "alice")
    core.add_member_user_group("sysadmins", "bob")

    for hostname, porta in PORTAS.items():
        hk = _capturar_host_key(porta)
        op = core.register_server(hostname, "127.0.0.1", porta, hk)
        assert op.status == OperationStatus.SUCCESS

    core.create_server_group("producao")
    for hostname in PORTAS:
        core.add_member_server_group("producao", hostname)

    core.grant("sysadmins", "producao", PermissionLevel.SUDO)

    op_apply = core.apply()
    assert op_apply.status == OperationStatus.SUCCESS, [
        (s.server, s.action.value, s.status, s.error) for s in op_apply.sub_actions
    ]
    assert len(op_apply.sub_actions) == 6
    assert all(s.status == "success" for s in op_apply.sub_actions)

    rc, out = _exec_container(
        "adminforge-web-01", "sudo", "cat", "/home/alice/.ssh/authorized_keys"
    )
    assert rc == 0
    assert "BEGIN adminforge: alice:" in out
    assert "END adminforge: alice:" in out
    assert "alice@laptop" in out

    # após o 1º apply criando o authorized_keys do zero, ainda não há .bak (não havia file antes)
    # agora desabilita bob e dispara um 2º edit para criar o .bak
    rc, out = _exec_container("adminforge-web-01", "sudo", "cat", "/etc/sudoers.d/adminforge-alice")
    assert rc == 0
    assert "alice ALL=(ALL) NOPASSWD:ALL" in out

    rc, _ = _exec_container("adminforge-web-01", "sudo", "visudo", "-c")
    assert rc == 0

    rc, out = _exec_container("adminforge-web-01", "id", "alice")
    assert rc == 0
    assert "uid=" in out

    assert core.preview() == []

    core.desabilitar_user("bob")
    pending = core.preview()
    assert len(pending) == 3
    assert all(s.action == ActionType.REMOVE_KEY and s.username == "bob" for s in pending)

    op_remove = core.apply()
    assert op_remove.status == OperationStatus.SUCCESS

    rc, out = _exec_container("adminforge-web-01", "sudo", "cat", "/home/bob/.ssh/authorized_keys")
    assert rc == 0
    assert "bob:" not in out
    assert "BEGIN adminforge: bob:" not in out

    # bob teve um file escrito no 1o apply e re-escrito no 2o (remove); o .bak agora existe
    rc, _ = _exec_container("adminforge-web-01", "sudo", "test", "-f", "/home/bob/.ssh/authorized_keys.bak")
    assert rc == 0, "expected authorized_keys.bak after second edit"

    rc, _ = _exec_container("adminforge-web-01", "ls", "/etc/sudoers.d/adminforge-bob")
    assert rc != 0

    rc, out = _exec_container("adminforge-web-01", "sudo", "cat", "/home/alice/.ssh/authorized_keys")
    assert rc == 0
    assert "BEGIN adminforge: alice:" in out

    op_audit, report = core.audit_server("web-01")
    assert op_audit.status == OperationStatus.SUCCESS

    user_names = {u["name"] for u in report["users"]}
    assert "adminforge" in user_names
    assert "alice" in user_names
    assert "root" in user_names  # antes era filtrado por UID>=100

    alice = next(u for u in report["users"] if u["name"] == "alice")
    assert alice["categoria"] == "human"  # UID >= 1000
    assert alice["sudo"], "alice deveria ter regra sudo (NOPASSWD:ALL)"

    group_names = {g["name"] for g in report["groups"]}
    assert "root" in group_names
    assert "adminforge" in group_names

    af_files = [a for a in report["sudoers_arquivos"] if a["adminforge"]]
    assert any(a["name"] == "adminforge-alice" for a in af_files)

    # verify: declarado vs real deve bater (so alice agora, bob foi removido)
    from adminforge import authorized_keys as ak
    web01 = core.store.get_server("web-01")
    refs_declaradas = {
        (item["ref"] if isinstance(item, dict) else item) for item in web01.installed_keys
    }
    conteudo, ok = SSHDeployer(
        private_key_path=lab["priv_key"],
        known_hosts_path=tmp_path / "kh-verify",
    ).read_authorized_keys(web01, "alice")
    assert ok, "read_authorized_keys deveria retornar ok=True (sudo NOPASSWD configurado no lab)"
    refs_reais = set(ak.parse_blocks(conteudo).keys())
    assert refs_declaradas == refs_reais, (
        f"drift: declarado={refs_declaradas} real={refs_reais}"
    )

    # Sudo profile: troca grant de full -> profile, re-aplica, valida sudoers
    core.create_sudo_profile("read-logs", ["/bin/journalctl", "/bin/cat"])
    # remove permission atual e cria nova com profile
    core.revoke("sysadmins", "producao")
    core.apply()  # remove regras antigas
    core.grant("sysadmins", "producao", PermissionLevel.SUDO, profile="read-logs")
    op_profile = core.apply()
    assert op_profile.status == OperationStatus.SUCCESS

    rc, out = _exec_container("adminforge-web-01", "sudo", "cat", "/etc/sudoers.d/adminforge-alice")
    assert rc == 0
    assert "NOPASSWD: /bin/journalctl" in out
    assert "NOPASSWD: /bin/cat" in out
    assert "NOPASSWD:ALL" not in out
    rc, _ = _exec_container("adminforge-web-01", "sudo", "visudo", "-c")
    assert rc == 0

    ok, _ = core.auditor.verify_chain()
    assert ok is True


def test_reconcile_recreates_manually_deleted_user(lab, tmp_path):
    state = tmp_path / "state_rc"
    core = _make_core(state, lab["priv_key"])

    core.cadastrar_user("carol", "Carol", "c@e.com")
    core.register_key("carol", KEY_CAROL)
    core.create_user_group("sres")
    core.add_member_user_group("sres", "carol")
    hk = _capturar_host_key(PORTAS["web-01"])
    core.register_server("web-01", "127.0.0.1", PORTAS["web-01"], hk)
    core.create_server_group("app")
    core.add_member_server_group("app", "web-01")
    core.grant("sres", "app", PermissionLevel.SUDO)

    op = core.apply()
    assert op.status == OperationStatus.SUCCESS, [
        (s.action.value, s.status, s.error) for s in op.sub_actions
    ]

    rc, out = _run_verify(state, lab["priv_key"])
    assert "carol" in out and "account missing" not in out, out

    rc, out = _exec_container("adminforge-web-01", "sudo", "cat", "/home/carol/.ssh/authorized_keys")
    assert "BEGIN adminforge: carol" in out

    rc, _ = _exec_container("adminforge-web-01", "userdel", "carol")
    assert rc == 0, "userdel carol falhou"
    rc, _ = _exec_container("adminforge-web-01", "id", "carol")
    assert rc != 0
    rc, out = _exec_container("adminforge-web-01", "sudo", "cat", "/home/carol/.ssh/authorized_keys")
    assert "BEGIN adminforge: carol" in out

    rc, out = _run_verify(state, lab["priv_key"])
    assert "carol" in out and "account missing" in out, out

    op = core.apply(reconcile=True)
    assert op.status == OperationStatus.SUCCESS, [
        (s.action.value, s.status, s.error) for s in op.sub_actions
    ]
    rc, out = _exec_container("adminforge-web-01", "id", "carol")
    assert rc == 0 and "uid=" in out

    rc, out = _run_verify(state, lab["priv_key"])
    assert "carol" in out and "account missing" not in out, out
