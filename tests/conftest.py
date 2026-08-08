"""Shared pytest fixtures for the unit test suite.

Every fixture here wires the fake (in-memory-on-disk) collaborators —
DryRunDeployer, JsonStore, JsonlAuditor — so unit tests exercise Nucleo's
logic without SSH or real servers.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from adminforge.auditor.jsonl_auditor import JsonlAuditor
from adminforge.core.nucleo import Nucleo
from adminforge.deployer.dry_run import DryRunDeployer
from adminforge.store.json_store import JsonStore

CHAVE_ALICE = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGZdz3+gT+Md3OSv00ku0Q9j+QUvhU3iRA9eCkP9F1Tc alice@laptop"
)
CHAVE_BOB = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIE9NK1qj7m9rwGzN9bM4LqXz0Z8c9zN0R1aB9fEdC7Yk bob@laptop"
)
HOST_KEY_FAKE = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBO4cGUzZxDpHxEyz1F4vLeXyv7yY8Ig9aB1cD2eF3gH"


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    """A fresh, empty state directory under pytest's per-test tmp_path."""
    d = tmp_path / "state"
    d.mkdir()
    return d


@pytest.fixture
def deployer() -> DryRunDeployer:
    """A Deployer that records intended SSH actions without ever opening a connection."""
    return DryRunDeployer()


@pytest.fixture
def nucleo(state_dir: Path, deployer: DryRunDeployer) -> Nucleo:
    """A Nucleo wired to a fresh JsonStore/JsonlAuditor over `state_dir` and the dry-run deployer."""
    store = JsonStore(state_dir)
    auditor = JsonlAuditor(state_dir / "history.jsonl")
    return Nucleo(store, auditor, deployer, superadmin="operador")
