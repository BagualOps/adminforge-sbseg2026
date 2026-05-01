from __future__ import annotations

from pathlib import Path

import pytest

from adminforge.auditor.jsonl_auditor import JsonlAuditor
from adminforge.core.nucleo import Nucleo
from adminforge.deployer.dry_run import DryRunDeployer
from adminforge.store.json_store import JsonStore

CHAVE_MARINA = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGZdz3+gT+Md3OSv00ku0Q9j+QUvhU3iRA9eCkP9F1Tc marina@laptop"
)
CHAVE_RUI = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIE9NK1qj7m9rwGzN9bM4LqXz0Z8c9zN0R1aB9fEdC7Yk rui@laptop"
)
HOST_KEY_FAKE = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBO4cGUzZxDpHxEyz1F4vLeXyv7yY8Ig9aB1cD2eF3gH"


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    return d


@pytest.fixture
def deployer() -> DryRunDeployer:
    return DryRunDeployer()


@pytest.fixture
def nucleo(state_dir: Path, deployer: DryRunDeployer) -> Nucleo:
    store = JsonStore(state_dir)
    auditor = JsonlAuditor(state_dir / "history.jsonl")
    return Nucleo(store, auditor, deployer, superadmin="cristhian")
