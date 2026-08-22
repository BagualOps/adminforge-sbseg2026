"""Edits and renames of entities (user, server, groups, sudo-profile), including
how references cascade (group members, permissions)."""
from __future__ import annotations

from adminforge.core.core import Core
from adminforge.domain import PermissionLevel, OperationStatus

from .conftest import KEY_ALICE, HOST_KEY_FAKE


def _setup(core: Core) -> None:
    core.cadastrar_user("alice", "Alice", "alice@e.com")
    core.register_key("alice", KEY_ALICE)
    core.create_user_group("sa")
    core.add_member_user_group("sa", "alice")
    core.register_server("web-01", "10.0.0.10", 22, HOST_KEY_FAKE)
    core.create_server_group("prod")
    core.add_member_server_group("prod", "web-01")
    core.grant("sa", "prod", PermissionLevel.SUDO)


# ---------- editar_user ----------

def test_edit_user_name_and_email(core: Core):
    _setup(core)
    op = core.editar_user("alice", name="Alice Souza", email="alice@empresa.com")
    assert op.status == OperationStatus.SUCCESS
    u = core.store.get_user("alice")
    assert u.name == "Alice Souza" and u.email == "alice@empresa.com"


def test_edit_user_preserves_credentials(core: Core):
    _setup(core)
    creds_antes = core.store.list_credentials("alice")
    core.editar_user("alice", name="Alice S.")
    assert core.store.list_credentials("alice") == creds_antes


def test_edit_user_invalid_email_fails(core: Core):
    _setup(core)
    op = core.editar_user("alice", email="nao-email")
    assert op.status == OperationStatus.FAILURE


def test_edit_missing_user_fails(core: Core):
    op = core.editar_user("fantasma", name="X")
    assert op.status == OperationStatus.FAILURE


# ---------- rename_user ----------

def test_rename_user_cascades_to_groups(core: Core):
    _setup(core)
    op = core.rename_user("alice", "alicia")
    assert op.status == OperationStatus.SUCCESS
    assert core.store.get_user("alice") is None
    assert core.store.get_user("alicia") is not None
    assert "alicia" in core.store.get_user_group("sa").members
    assert "alice" not in core.store.get_user_group("sa").members


def test_rename_user_preserves_credentials(core: Core):
    _setup(core)
    fps_antes = {c.fingerprint for c in core.store.list_credentials("alice")}
    core.rename_user("alice", "alicia")
    fps_depois = {c.fingerprint for c in core.store.list_credentials("alicia")}
    assert fps_antes == fps_depois


def test_rename_user_to_existing_fails(core: Core):
    _setup(core)
    core.cadastrar_user("bob", "Bob", "b@e.com")
    op = core.rename_user("alice", "bob")
    assert op.status == OperationStatus.FAILURE
    assert core.store.get_user("alice") is not None


def test_rename_user_invalid_fails(core: Core):
    _setup(core)
    op = core.rename_user("alice", "Alice!")
    assert op.status == OperationStatus.FAILURE


def test_rename_user_idempotent_same_name(core: Core):
    _setup(core)
    op = core.rename_user("alice", "alice")
    assert op.status == OperationStatus.SUCCESS


# ---------- edit_server ----------

def test_edit_server_ip_and_port(core: Core):
    _setup(core)
    op = core.edit_server("web-01", ipv4="10.0.0.99", porta=2222)
    assert op.status == OperationStatus.SUCCESS
    s = core.store.get_server("web-01")
    assert s.ipv4 == "10.0.0.99" and s.ssh_port == 2222


def test_edit_server_invalid_port_fails(core: Core):
    _setup(core)
    op = core.edit_server("web-01", porta=70000)
    assert op.status == OperationStatus.FAILURE


def test_edit_server_ipv4_octet_out_of_range_fails(core: Core):
    _setup(core)
    op = core.edit_server("web-01", ipv4="999.999.999.999")
    assert op.status == OperationStatus.FAILURE
    assert core.store.get_server("web-01").ipv4 == "10.0.0.10"


def test_register_server_ipv4_octet_out_of_range_fails(core: Core):
    op = core.register_server("web-99", "10.0.0.300", 22, HOST_KEY_FAKE)
    assert op.status == OperationStatus.FAILURE


def test_edit_server_preserves_installed_keys(core: Core):
    _setup(core)
    s = core.store.get_server("web-01")
    s.installed_keys = [{"ref": "alice:SHA256:x", "username": "alice", "level": "sudo"}]
    core.store.save_server(s)
    core.edit_server("web-01", ipv4="10.0.0.99")
    assert core.store.get_server("web-01").installed_keys == [
        {"ref": "alice:SHA256:x", "username": "alice", "level": "sudo"}
    ]


# ---------- rename_server ----------

def test_rename_server_cascades_to_server_group(core: Core):
    _setup(core)
    op = core.rename_server("web-01", "web-001")
    assert op.status == OperationStatus.SUCCESS
    assert core.store.get_server("web-01") is None
    assert core.store.get_server("web-001") is not None
    assert "web-001" in core.store.get_server_group("prod").members


# ---------- rename_user_group ----------

def test_rename_user_group_cascades_to_permissions(core: Core):
    _setup(core)
    op = core.rename_user_group("sa", "sysadmins")
    assert op.status == OperationStatus.SUCCESS
    assert core.store.get_user_group("sa") is None
    assert core.store.get_user_group("sysadmins") is not None
    perms = core.store.list_permissions()
    assert any(p.user_group == "sysadmins" for p in perms)
    assert not any(p.user_group == "sa" for p in perms)


# ---------- rename_server_group ----------

def test_rename_server_group_cascades_to_permissions(core: Core):
    _setup(core)
    op = core.rename_server_group("prod", "producao")
    assert op.status == OperationStatus.SUCCESS
    perms = core.store.list_permissions()
    assert all(p.server_group == "producao" for p in perms)


# ---------- rename_sudo_profile ----------

def test_rename_sudo_profile_cascades_to_permissions(core: Core):
    _setup(core)
    core.create_sudo_profile("db-ops", ["/bin/journalctl"])
    core.grant("sa", "prod", PermissionLevel.SUDO, profile="db-ops")
    op = core.rename_sudo_profile("db-ops", "logs")
    assert op.status == OperationStatus.SUCCESS
    assert core.store.get_sudo_profile("db-ops") is None
    assert core.store.get_sudo_profile("logs") is not None
    perms = core.store.list_permissions()
    assert perms[0].profile == "logs"
