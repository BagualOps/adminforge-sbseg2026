"""Regressão dos 3 defeitos do cenário 'deleção manual dessincroniza Store x servidor'.

P1 verify dava OK falso em bloco órfão deixado por userdel sem -r.
P2 apply não re-aplicava após deleção manual (Store ainda acredita instalado).
P3 _escrever_authorized_keys usava install /dev/stdin (quebra em coreutils minímos).
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
from adminforge.core.nucleo import Nucleo
from adminforge.deployer.dry_run import DryRunDeployer
from adminforge.deployer.ssh_deployer import SSHDeployer
from adminforge.domain import NivelPermissao, Servidor, TipoAcao
from adminforge.store.json_store import JsonStore

from .conftest import CHAVE_ALICE, HOST_KEY_FAKE

FP_ALICE = ssh_keys.fingerprint(CHAVE_ALICE)
REF_ALICE = f"alice:{FP_ALICE}"
CHAVE_STALE = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIStale0000000000000000000000000000 alice@old"


def _setup_cli_state(state: Path):
    def run(argv):
        return _run_cli_with_state(state, argv)

    run(["user", "add", "--username", "alice", "--name", "A", "--email", "a@e.com"])
    run(["user", "key", "add", "--username", "alice", "--string", CHAVE_ALICE])
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


def _nucleo(state_dir: Path, deployer) -> Nucleo:
    store = JsonStore(state_dir)
    n = Nucleo(store, JsonlAuditor(state_dir / "history.jsonl"), deployer, "operador")
    n.cadastrar_user("alice", "Alice", "m@e.com")
    n.cadastrar_chave("alice", CHAVE_ALICE)
    n.criar_grupo_user("sa")
    n.adicionar_membro_grupo_user("sa", "alice")
    n.cadastrar_servidor("web-01", "10.0.0.10", 22, HOST_KEY_FAKE)
    n.criar_grupo_servidor("prod")
    n.adicionar_membro_grupo_servidor("prod", "web-01")
    n.conceder("sa", "prod", NivelPermissao.SHELL)
    return n


class _FakeDeployer(DryRunDeployer):
    def __init__(self, contas: set[str], ak_por_user: dict[str, str]):
        super().__init__()
        self._contas = contas
        self._ak = ak_por_user

    def inspecionar(self, servidor: Servidor) -> dict:
        return {
            "usuarios": [
                {
                    "nome": u,
                    "uid": 1000,
                    "shell": "/bin/bash",
                    "categoria": "human",
                    "grupos": [],
                    "sudo": [],
                }
                for u in sorted(self._contas)
            ],
            "grupos": [],
            "servicos": [],
            "sudoers_arquivos": [],
            "sudoers_regras": [],
        }

    def ler_authorized_keys(self, servidor: Servidor, username: str) -> tuple[str, bool]:
        return self._ak.get(username, ""), True


# --- P1: verify -----------------------------------------------------------
def test_verify_conta_ausente_nao_da_ok(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    _setup_cli_state(state)
    _run_cli_with_state(state, ["apply", "--yes", "--dry-run"])

    bloco_stale = ak.bloco(REF_ALICE, CHAVE_ALICE)
    from adminforge.deployer.dry_run import DryRunDeployer as DRD

    monkeypatch.setattr(
        DRD,
        "inspecionar",
        lambda self, s: {
            "usuarios": [
                {
                    "nome": "root",
                    "uid": 0,
                    "shell": "/bin/bash",
                    "categoria": "system",
                    "grupos": [],
                    "sudo": [],
                }
            ],
            "grupos": [],
            "servicos": [],
            "sudoers_arquivos": [],
            "sudoers_regras": [],
        },
    )
    monkeypatch.setattr(DRD, "ler_authorized_keys", lambda self, s, u: (bloco_stale, True))

    rc, out = _run_cli_with_state(state, ["apply", "verify", "--dry-run"])
    assert rc == 2, out
    assert "account missing" in out
    assert REF_ALICE in out


def test_verify_conta_presente_com_bloco_da_ok(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    _setup_cli_state(state)
    _run_cli_with_state(state, ["apply", "--yes", "--dry-run"])

    bloco = ak.bloco(REF_ALICE, CHAVE_ALICE)
    from adminforge.deployer.dry_run import DryRunDeployer as DRD

    monkeypatch.setattr(
        DRD,
        "inspecionar",
        lambda self, s: {
            "usuarios": [
                {
                    "nome": "root",
                    "uid": 0,
                    "shell": "/bin/bash",
                    "categoria": "system",
                    "grupos": [],
                    "sudo": [],
                },
                {
                    "nome": "alice",
                    "uid": 1000,
                    "shell": "/bin/bash",
                    "categoria": "human",
                    "grupos": [],
                    "sudo": [],
                },
            ],
            "grupos": [],
            "servicos": [],
            "sudoers_arquivos": [],
            "sudoers_regras": [],
        },
    )
    monkeypatch.setattr(DRD, "ler_authorized_keys", lambda self, s, u: (bloco, True))

    rc, out = _run_cli_with_state(state, ["apply", "verify", "--dry-run"])
    assert rc == 0, out
    assert REF_ALICE in out


# --- P2: force / reconcile ------------------------------------------------
def test_force_reemite_add_mesmo_em_sync(state_dir: Path):
    n = _nucleo(state_dir, DryRunDeployer())
    assert n.aplicar().status.value == "sucesso"
    assert n.preview() == []

    pendentes = n.preview(force=True)
    assert len(pendentes) == 1
    assert pendentes[0].acao == TipoAcao.ADICIONAR_CHAVE
    assert pendentes[0].username == "alice"


def test_reconcile_recria_chave_removida_manualmente(state_dir: Path):
    deployer = _FakeDeployer({"alice"}, {"alice": ""})
    n = _nucleo(state_dir, deployer)
    sv = n.store.get_servidor("web-01")
    sv.chaves_instaladas = [{"ref": REF_ALICE, "username": "alice", "nivel": "shell"}]
    n.store.save_servidor(sv)

    assert n.preview() == []
    pendentes = n.preview(reconcile=True)
    assert len(pendentes) == 1
    assert pendentes[0].acao == TipoAcao.ADICIONAR_CHAVE
    assert pendentes[0].credencial == REF_ALICE


def test_reconcile_remove_bloco_orfao(state_dir: Path):
    ref_orfao = "alice:SHA256:0000000000000000000000000000000000000000000"
    deployer = _FakeDeployer({"alice"}, {"alice": ak.bloco(ref_orfao, CHAVE_STALE)})
    n = _nucleo(state_dir, deployer)
    sv = n.store.get_servidor("web-01")
    sv.chaves_instaladas = [{"ref": REF_ALICE, "username": "alice", "nivel": "shell"}]
    n.store.save_servidor(sv)

    acoes = {(s.acao, s.credencial) for s in n.preview(reconcile=True)}
    assert (TipoAcao.ADICIONAR_CHAVE, REF_ALICE) in acoes
    assert (TipoAcao.REMOVER_CHAVE, ref_orfao) in acoes


def test_force_e_reconcile_sao_exclusivos_na_cli(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    rc, out = _run_cli_with_state(state, ["apply", "--force", "--reconcile", "--dry-run"])
    assert rc != 0
    assert "not allowed" in out.lower()


# --- P3: _escrever_authorized_keys ---------------------------------------
def test_escrever_authorized_keys_nao_usa_dev_stdin(tmp_path: Path):
    capturado: list[str] = []
    d = SSHDeployer(tmp_path / "id", tmp_path / "known_hosts")
    d._executar_ssh = lambda servidor, comando: capturado.append(comando) or (0, "", "")  # type: ignore
    servidor = Servidor(hostname="web-01", ipv4="10.0.0.1", chave_host="ssh-ed25519 AAAA x")

    d._escrever_authorized_keys(servidor, "alice", "conteudo")

    cmd = capturado[0]
    assert "/dev/stdin" not in cmd
    assert "tee" in cmd and "sudo mv" in cmd
    assert "chmod 600" in cmd and "chown" in cmd and ".bak" in cmd


def test_escrever_authorized_keys_propaga_erro(tmp_path: Path):
    d = SSHDeployer(tmp_path / "id", tmp_path / "known_hosts")
    d._executar_ssh = lambda servidor, comando: (1, "", "install: No such file or directory")  # type: ignore
    servidor = Servidor(hostname="web-01", ipv4="10.0.0.1", chave_host="ssh-ed25519 AAAA x")

    with pytest.raises(RuntimeError, match="failed to write authorized_keys"):
        d._escrever_authorized_keys(servidor, "alice", "x")
