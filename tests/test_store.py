"""Tests for the JSON store: atomic writes, natural-key lookups, and locking."""

from pathlib import Path

import pytest

from adminforge.domain import UserGroup, PermissionLevel, Permission, Server, SudoProfile, User
from adminforge.exceptions import LockBusy
from adminforge.store.json_store import JsonStore


def test_lockfile_concorrencia(tmp_path: Path):
    a = JsonStore(tmp_path)
    b = JsonStore(tmp_path)
    a.lock()
    try:
        with pytest.raises(LockBusy):
            b.lock()
    finally:
        a.unlock()
    b.lock()
    b.unlock()


def test_save_user_permission_0600(tmp_path: Path):
    s = JsonStore(tmp_path)
    s.save_user(User(username="alice", name="Alice", email="m@e.com"))
    file = tmp_path / "users" / "alice.json"
    assert file.exists()
    modo = oct(file.stat().st_mode)[-3:]
    assert modo == "600"


def test_roundtrip_server(tmp_path: Path):
    s = JsonStore(tmp_path)
    serv = Server(
        hostname="web-01",
        ipv4="10.0.0.10",
        ssh_port=22,
        host_key="ssh-ed25519 AAAA...",
        installed_keys=[{"ref": "alice:fp", "username": "alice", "level": "sudo"}],
    )
    s.save_server(serv)
    lido = s.get_server("web-01")
    assert lido is not None
    assert lido.ipv4 == "10.0.0.10"
    assert lido.installed_keys[0]["ref"] == "alice:fp"


def test_permission_updates_instead_of_duplicating(tmp_path: Path):
    s = JsonStore(tmp_path)
    s.save_permission(Permission(user_group="sa", server_group="prod", level=PermissionLevel.SHELL))
    s.save_permission(Permission(user_group="sa", server_group="prod", level=PermissionLevel.SUDO))
    perms = s.list_permissions()
    assert len(perms) == 1
    assert perms[0].level == PermissionLevel.SUDO


def test_delete_group(tmp_path: Path):
    s = JsonStore(tmp_path)
    s.save_user_group(UserGroup(name="sa", members=["x"]))
    assert s.get_user_group("sa") is not None
    s.delete_user_group("sa")
    assert s.get_user_group("sa") is None


def test_sudo_profile_roundtrip(tmp_path: Path):
    s = JsonStore(tmp_path)
    profile = SudoProfile(name="read-logs", commands=["/bin/journalctl", "/bin/cat /var/log/*"])
    s.save_sudo_profile(profile)

    lido = s.get_sudo_profile("read-logs")
    assert lido is not None
    assert lido.name == "read-logs"
    assert lido.commands == ["/bin/journalctl", "/bin/cat /var/log/*"]

    file = tmp_path / "sudo-profiles" / "read-logs.json"
    assert file.exists()
    assert oct(file.stat().st_mode)[-3:] == "600"


def test_sudo_profile_list_e_delete(tmp_path: Path):
    s = JsonStore(tmp_path)
    s.save_sudo_profile(SudoProfile(name="a", commands=["/bin/a"]))
    s.save_sudo_profile(SudoProfile(name="b", commands=["/bin/b"]))
    names = sorted(p.name for p in s.list_sudo_profiles())
    assert names == ["a", "b"]

    s.delete_sudo_profile("a")
    assert s.get_sudo_profile("a") is None
    assert [p.name for p in s.list_sudo_profiles()] == ["b"]


def test_sudo_profile_inexistente_retorna_none(tmp_path: Path):
    s = JsonStore(tmp_path)
    assert s.get_sudo_profile("ghost") is None
    # delete de inexistente nao deve estourar (idempotente)
    s.delete_sudo_profile("ghost")