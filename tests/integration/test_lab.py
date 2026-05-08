"""Teste de integracao end-to-end no lab Docker.

Sobe 3 containers Debian via docker compose, executa o fluxo completo
(cadastros -> grupos -> grant -> apply -> revogacao -> apply) contra eles,
inspeciona dentro dos containers para validar o resultado real, e derruba.

Opt-in: so roda se ADMINFORGE_INTEGRATION=1 ou pytest -m integration.
Pula automaticamente se docker nao estiver disponivel.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from adminforge.auditor.jsonl_auditor import JsonlAuditor
from adminforge.core.nucleo import Nucleo
from adminforge.deployer.ssh_deployer import SSHDeployer
from adminforge.domain import NivelPermissao, StatusOperacao, TipoAcao
from adminforge.store.json_store import JsonStore


REPO = Path(__file__).resolve().parent.parent.parent
LAB_DIR = REPO / "infra" / "testlab"
COMPOSE_FILE = LAB_DIR / "docker-compose.yml"
KEYS_DIR = LAB_DIR / "keys"

PORTAS = {"web-01": 2201, "web-02": 2202, "db-03": 2203}

CHAVE_ALICE = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGZdz3+gT+Md3OSv00ku0Q9j+QUvhU3iRA9eCkP9F1Tc alice@laptop"
)
CHAVE_BOB = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIE9NK1qj7m9rwGzN9bM4LqXz0Z8c9zN0R1aB9fEdC7Yk bob@laptop"
)


def _docker_disponivel() -> bool:
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
    if not _docker_disponivel():
        pytest.skip("docker compose nao disponivel")

    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    chave_priv = KEYS_DIR / "adminforge_id"
    chave_pub = KEYS_DIR / "adminforge_id.pub"
    if not chave_priv.exists():
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(chave_priv), "-C", "adminforge@testlab", "-q"],
            check=True,
        )

    chave_priv_local = tmp_path_factory.mktemp("keys") / "adminforge_id"
    chave_priv_local.write_bytes(chave_priv.read_bytes())
    os.chmod(chave_priv_local, 0o600)

    env = {**os.environ, "ADMINFORGE_PUBKEY": chave_pub.read_text().strip()}

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
             "-i", str(chave_priv_local), "-p", "2201", "adminforge@127.0.0.1", "true"],
            capture_output=True,
        )
        if proc.returncode == 0:
            break
        time.sleep(1)
    else:
        subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"], env=env)
        pytest.fail("containers nao ficaram prontos em 30s")

    yield {"chave_priv": chave_priv_local, "env": env}

    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"],
        env=env, capture_output=True, timeout=60,
    )


def _capturar_host_key(porta: int) -> str:
    proc = subprocess.run(
        ["ssh-keyscan", "-T", "5", "-t", "ed25519", "-p", str(porta), "127.0.0.1"],
        capture_output=True, text=True, timeout=10,
    )
    for linha in proc.stdout.splitlines():
        partes = linha.strip().split(None, 1)
        if len(partes) == 2 and partes[1].startswith("ssh-ed25519"):
            return partes[1]
    raise RuntimeError(f"falha ao capturar host_key na porta {porta}")


def _exec_container(nome_container: str, *cmd: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["docker", "exec", nome_container, *cmd],
        capture_output=True, text=True, timeout=30,
    )
    return proc.returncode, proc.stdout


def _fazer_nucleo(state_dir: Path, chave_priv: Path) -> Nucleo:
    store = JsonStore(state_dir)
    auditor = JsonlAuditor(state_dir / "history.jsonl")
    deployer = SSHDeployer(
        chave_privada_path=chave_priv,
        known_hosts_path=state_dir / "known_hosts",
        usuario_servico="adminforge",
        timeout=10,
    )
    return Nucleo(store, auditor, deployer, superadmin="operador")


def test_fluxo_completo_em_containers(lab, tmp_path):
    nucleo = _fazer_nucleo(tmp_path / "state", lab["chave_priv"])

    assert nucleo.cadastrar_user("alice", "Alice", "m@e.com").status == StatusOperacao.SUCESSO
    assert nucleo.cadastrar_user("bob", "Bob", "bob@e.com").status == StatusOperacao.SUCESSO
    assert nucleo.cadastrar_chave("alice", CHAVE_ALICE).status == StatusOperacao.SUCESSO
    assert nucleo.cadastrar_chave("bob", CHAVE_BOB).status == StatusOperacao.SUCESSO

    nucleo.criar_grupo_user("sysadmins")
    nucleo.adicionar_membro_grupo_user("sysadmins", "alice")
    nucleo.adicionar_membro_grupo_user("sysadmins", "bob")

    for hostname, porta in PORTAS.items():
        hk = _capturar_host_key(porta)
        op = nucleo.cadastrar_servidor(hostname, "127.0.0.1", porta, hk)
        assert op.status == StatusOperacao.SUCESSO

    nucleo.criar_grupo_servidor("producao")
    for hostname in PORTAS:
        nucleo.adicionar_membro_grupo_servidor("producao", hostname)

    nucleo.conceder("sysadmins", "producao", NivelPermissao.SUDO)

    op_apply = nucleo.aplicar()
    assert op_apply.status == StatusOperacao.SUCESSO, [
        (s.servidor, s.acao.value, s.status, s.erro) for s in op_apply.subacoes
    ]
    assert len(op_apply.subacoes) == 6
    assert all(s.status == "sucesso" for s in op_apply.subacoes)

    rc, out = _exec_container(
        "adminforge-web-01", "sudo", "cat", "/home/alice/.ssh/authorized_keys"
    )
    assert rc == 0
    assert "BEGIN adminforge: alice:" in out
    assert "END adminforge: alice:" in out
    assert "alice@laptop" in out

    rc, out = _exec_container("adminforge-web-01", "sudo", "cat", "/etc/sudoers.d/adminforge-alice")
    assert rc == 0
    assert "alice ALL=(ALL) NOPASSWD:ALL" in out

    rc, _ = _exec_container("adminforge-web-01", "sudo", "visudo", "-c")
    assert rc == 0

    rc, out = _exec_container("adminforge-web-01", "id", "alice")
    assert rc == 0
    assert "uid=" in out

    assert nucleo.preview() == []

    nucleo.desabilitar_user("bob")
    pendentes = nucleo.preview()
    assert len(pendentes) == 3
    assert all(s.acao == TipoAcao.REMOVER_CHAVE and s.username == "bob" for s in pendentes)

    op_remove = nucleo.aplicar()
    assert op_remove.status == StatusOperacao.SUCESSO

    rc, out = _exec_container("adminforge-web-01", "sudo", "cat", "/home/bob/.ssh/authorized_keys")
    assert rc == 0
    assert "bob:" not in out
    assert "BEGIN adminforge: bob:" not in out

    rc, _ = _exec_container("adminforge-web-01", "ls", "/etc/sudoers.d/adminforge-bob")
    assert rc != 0

    rc, out = _exec_container("adminforge-web-01", "sudo", "cat", "/home/alice/.ssh/authorized_keys")
    assert rc == 0
    assert "BEGIN adminforge: alice:" in out

    op_audit, relatorio = nucleo.auditar_servidor("web-01")
    assert op_audit.status == StatusOperacao.SUCESSO
    assert any("adminforge" in u for u in relatorio["usuarios"])
    assert any("alice" in u for u in relatorio["usuarios"])

    ok, _ = nucleo.auditor.verificar_cadeia()
    assert ok is True
