from argparse import Namespace
from pathlib import Path

from adminforge.cli import completers
from adminforge.core.nucleo import Nucleo
from adminforge.deployer.dry_run import DryRunDeployer
from adminforge.auditor.jsonl_auditor import JsonlAuditor
from adminforge.store.json_store import JsonStore

from .conftest import CHAVE_ALICE, HOST_KEY_FAKE


def _seed(state_dir: Path) -> Nucleo:
    nucleo = Nucleo(JsonStore(state_dir), JsonlAuditor(state_dir / "history.jsonl"), DryRunDeployer(), "op")
    nucleo.cadastrar_user("alice", "Alice", "a@e.com")
    nucleo.cadastrar_user("alfred", "Alfred", "alf@e.com")
    nucleo.cadastrar_user("bob", "Bob", "b@e.com")
    nucleo.cadastrar_chave("alice", CHAVE_ALICE)
    nucleo.criar_grupo_user("sysadmins")
    nucleo.criar_grupo_user("dba")
    nucleo.cadastrar_servidor("web-01", "10.0.0.10", 22, HOST_KEY_FAKE)
    nucleo.cadastrar_servidor("web-02", "10.0.0.11", 22, HOST_KEY_FAKE)
    nucleo.criar_grupo_servidor("producao")
    return nucleo


def test_usernames_completer(state_dir: Path):
    _seed(state_dir)
    args = Namespace(state=str(state_dir))
    assert completers.usernames("", args) == ["alfred", "alice", "bob"]
    assert completers.usernames("al", args) == ["alfred", "alice"]
    assert completers.usernames("z", args) == []


def test_hostnames_completer(state_dir: Path):
    _seed(state_dir)
    args = Namespace(state=str(state_dir))
    assert completers.hostnames("", args) == ["web-01", "web-02"]
    assert completers.hostnames("web-0", args) == ["web-01", "web-02"]


def test_user_groups_completer(state_dir: Path):
    _seed(state_dir)
    args = Namespace(state=str(state_dir))
    assert completers.user_groups("", args) == ["dba", "sysadmins"]
    assert completers.user_groups("sys", args) == ["sysadmins"]


def test_server_groups_completer(state_dir: Path):
    _seed(state_dir)
    args = Namespace(state=str(state_dir))
    assert completers.server_groups("", args) == ["producao"]


def test_sudo_profiles_completer(state_dir: Path):
    nucleo = _seed(state_dir)
    nucleo.criar_sudo_profile("read-logs", ["/bin/journalctl"])
    nucleo.criar_sudo_profile("restart-web", ["/bin/systemctl restart nginx"])
    args = Namespace(state=str(state_dir))
    assert completers.sudo_profiles("", args) == ["read-logs", "restart-web"]
    assert completers.sudo_profiles("re", args) == ["read-logs", "restart-web"]
    assert completers.sudo_profiles("read", args) == ["read-logs"]
    assert completers.sudo_profiles("z", args) == []


def test_fingerprints_completer(state_dir: Path):
    _seed(state_dir)
    args = Namespace(state=str(state_dir))
    fps = completers.fingerprints("", args)
    assert len(fps) == 1
    assert fps[0].startswith("SHA256:")


def test_completer_state_inexistente(tmp_path: Path):
    args = Namespace(state=str(tmp_path / "nao-existe"))
    assert completers.usernames("", args) == []
    assert completers.fingerprints("", args) == []
