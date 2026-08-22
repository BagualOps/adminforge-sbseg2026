"""Tests for the orchestration core: registration, grants, revocation, and apply/preview."""

from adminforge.core.core import Core
from adminforge.domain import PermissionLevel, CredentialStatus, OperationStatus, UserStatus

from .conftest import KEY_ALICE, HOST_KEY_FAKE


def test_user_duplicado(core: Core):
    core.cadastrar_user("alice", "Alice", "m@e.com")
    op = core.cadastrar_user("alice", "Outra", "x@e.com")
    assert op.status == OperationStatus.FAILURE


def test_email_invalido_e_rejeitado(core: Core):
    op = core.cadastrar_user("bob", "Bob", "nao-email")
    assert op.status == OperationStatus.FAILURE


def test_username_invalido(core: Core):
    op = core.cadastrar_user("Alice!", "M", "m@e.com")
    assert op.status == OperationStatus.FAILURE


def test_duplicate_key_rejected(core: Core):
    core.cadastrar_user("alice", "Alice", "m@e.com")
    assert core.register_key("alice", KEY_ALICE).status == OperationStatus.SUCCESS
    op = core.register_key("alice", KEY_ALICE)
    assert op.status == OperationStatus.FAILURE


def test_key_for_missing_user(core: Core):
    op = core.register_key("nao-existe", KEY_ALICE)
    assert op.status == OperationStatus.FAILURE


def test_add_member_is_idempotent(core: Core):
    core.cadastrar_user("alice", "Alice", "m@e.com")
    core.create_user_group("sa")
    op1 = core.add_member_user_group("sa", "alice")
    op2 = core.add_member_user_group("sa", "alice")
    assert op1.status == OperationStatus.SUCCESS
    assert op2.status == OperationStatus.SUCCESS
    g = core.store.get_user_group("sa")
    assert g.members.count("alice") == 1


def test_delete_group_with_permission_fails(core: Core):
    core.create_user_group("sa")
    core.create_server_group("prod")
    core.grant("sa", "prod", PermissionLevel.SHELL)
    op = core.delete_user_group("sa")
    assert op.status == OperationStatus.FAILURE
    error = next((s.error for s in op.sub_actions if s.error), "")
    # message deve list_operations a permission especifica e sugerir command exato
    assert "1 associated permission" in error
    assert "prod (shell)" in error
    assert "adminforge permission revoke --user-group sa --server-group prod" in error


def test_delete_server_group_with_permission_lists_user_groups(core: Core):
    core.create_user_group("sa")
    core.create_user_group("dba")
    core.create_server_group("prod")
    core.grant("sa", "prod", PermissionLevel.SHELL)
    core.grant("dba", "prod", PermissionLevel.SUDO)
    op = core.delete_server_group("prod")
    assert op.status == OperationStatus.FAILURE
    error = next((s.error for s in op.sub_actions if s.error), "")
    assert "2 associated permission" in error
    assert "sa (shell)" in error and "dba (sudo)" in error
    assert "adminforge permission revoke --user-group sa --server-group prod" in error
    assert "adminforge permission revoke --user-group dba --server-group prod" in error


def test_grant_updates_level_without_duplicating(core: Core):
    core.create_user_group("sa")
    core.create_server_group("prod")
    core.grant("sa", "prod", PermissionLevel.SHELL)
    core.grant("sa", "prod", PermissionLevel.SUDO)
    perms = core.store.list_permissions()
    assert len(perms) == 1
    assert perms[0].level == PermissionLevel.SUDO


def test_revoke_missing_fails(core: Core):
    op = core.revoke("inexistente", "tambem-nao")
    assert op.status == OperationStatus.FAILURE


def test_disabling_user_revokes_credentials(core: Core):
    core.cadastrar_user("alice", "Alice", "m@e.com")
    core.register_key("alice", KEY_ALICE)
    core.desabilitar_user("alice")
    a = core.store.get_user("alice")
    assert a.status == UserStatus.INACTIVE
    creds = core.store.list_credentials("alice")
    assert all(c.status == CredentialStatus.REVOKED for c in creds)


def test_server_invalid_hostname(core: Core):
    op = core.register_server("Inv@lid!", "10.0.0.1", 22, HOST_KEY_FAKE)
    assert op.status == OperationStatus.FAILURE


def test_delete_server_removes_from_groups(core: Core):
    core.register_server("web-01", "10.0.0.10", 22, HOST_KEY_FAKE)
    core.create_server_group("prod")
    core.add_member_server_group("prod", "web-01")
    core.delete_server("web-01")
    g = core.store.get_server_group("prod")
    assert "web-01" not in g.members


def test_add_n_members_at_once(core: Core):
    core.cadastrar_user("alice", "Alice", "a@e.com")
    core.cadastrar_user("bob", "Bob", "b@e.com")
    core.cadastrar_user("carla", "Carla", "c@e.com")
    core.create_user_group("sa")
    op = core.add_members_user_group("sa", ["alice", "bob", "carla"])
    assert op.status == OperationStatus.SUCCESS
    g = core.store.get_user_group("sa")
    assert g.members == ["alice", "bob", "carla"]


def test_n_members_atomic_failure_if_one_missing(core: Core):
    core.cadastrar_user("alice", "Alice", "a@e.com")
    core.create_user_group("sa")
    op = core.add_members_user_group("sa", ["alice", "fantasma"])
    assert op.status == OperationStatus.FAILURE
    g = core.store.get_user_group("sa")
    assert g.members == []


def test_sudo_profile_create_e_concede(core: Core):
    op = core.create_sudo_profile("dba-postgres", ["/bin/systemctl restart postgresql", "/usr/bin/psql"])
    assert op.status == OperationStatus.SUCCESS
    core.create_user_group("dba")
    core.create_server_group("banco")
    op = core.grant("dba", "banco", PermissionLevel.SUDO, profile="dba-postgres")
    assert op.status == OperationStatus.SUCCESS
    perms = core.store.list_permissions()
    assert perms[0].profile == "dba-postgres"


def test_sudo_profile_rejects_relative_command(core: Core):
    op = core.create_sudo_profile("bad", ["systemctl restart nginx"])
    assert op.status == OperationStatus.FAILURE


def test_sudo_profile_rejects_newline_in_command(core: Core):
    """Regression: a \\n in the command would inject a new sudoers rule (and pass 'visudo -c')."""
    op = core.create_sudo_profile("evil", ["/bin/true\nbad ALL=(ALL) NOPASSWD:ALL"])
    assert op.status == OperationStatus.FAILURE
    op = core.create_sudo_profile("evil2", ["/bin/true\rfoo"])
    assert op.status == OperationStatus.FAILURE


def test_apply_fails_if_authorized_keys_read_failed(state_dir, monkeypatch):
    """Regression: when read_authorized_keys reports ok=False (sudo blocked, etc), apply
    must not overwrite the file from an empty string, which would wipe pre-existing
    AdminForge blocks. The sub-action fails in a controlled way instead."""
    from adminforge.auditor.jsonl_auditor import JsonlAuditor
    from adminforge.deployer.dry_run import DryRunDeployer
    from adminforge.store.json_store import JsonStore

    class DeployerSemLeitura(DryRunDeployer):
        def read_authorized_keys(self, server, username):
            return "", False  # simula sudo bloqueado

        def apply(self, server, sub_actions):
            # roda a logica real do adicionar_chave/remover_chave em vez de simular
            for s in sub_actions:
                try:
                    atual, ok = self.read_authorized_keys(server, s.username)
                    if not ok:
                        raise RuntimeError("failed to read authorized_keys")
                    s.status = "success"
                except Exception as e:
                    s.status = "failure"
                    s.error = str(e)
            return sub_actions

    core = Core(JsonStore(state_dir), JsonlAuditor(state_dir / "history.jsonl"),
                    DeployerSemLeitura(), "op")
    core.cadastrar_user("alice", "Alice", "a@e.com")
    core.register_key("alice", KEY_ALICE)
    core.create_user_group("sa")
    core.add_member_user_group("sa", "alice")
    core.register_server("web-01", "10.0.0.10", 22, HOST_KEY_FAKE)
    core.create_server_group("prod")
    core.add_member_server_group("prod", "web-01")
    core.grant("sa", "prod", PermissionLevel.SHELL)

    op = core.apply()
    assert op.status == OperationStatus.FAILURE
    assert any("failed to read" in (s.error or "") for s in op.sub_actions)


def test_sudo_profile_rejects_if_in_use(core: Core):
    core.create_sudo_profile("p1", ["/bin/true"])
    core.create_user_group("g")
    core.create_server_group("s")
    core.grant("g", "s", PermissionLevel.SUDO, profile="p1")
    op = core.delete_sudo_profile("p1")
    assert op.status == OperationStatus.FAILURE


def test_profile_only_with_sudo(core: Core):
    core.create_sudo_profile("p", ["/bin/true"])
    core.create_user_group("g")
    core.create_server_group("s")
    op = core.grant("g", "s", PermissionLevel.SHELL, profile="p")
    assert op.status == OperationStatus.FAILURE


def test_remove_n_members_at_once(core: Core):
    for u in ("alice", "bob", "carla"):
        core.cadastrar_user(u, u.title(), f"{u}@e.com")
    core.create_user_group("sa")
    core.add_members_user_group("sa", ["alice", "bob", "carla"])
    core.remove_members_user_group("sa", ["alice", "carla"])
    g = core.store.get_user_group("sa")
    assert g.members == ["bob"]