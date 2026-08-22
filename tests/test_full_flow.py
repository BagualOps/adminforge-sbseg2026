"""End-to-end flow: registration -> groups -> grant -> preview -> apply -> audit -> verify."""
from __future__ import annotations

from adminforge.core.core import Core
from adminforge.deployer.dry_run import DryRunDeployer
from adminforge.domain import PermissionLevel, OperationStatus, ActionType

from .conftest import KEY_ALICE, KEY_BOB, HOST_KEY_FAKE


def test_full_flow(core: Core):
    assert core.cadastrar_user("alice", "Alice", "m@empresa.com").status == OperationStatus.SUCCESS
    assert core.cadastrar_user("bob", "Bob", "bob@empresa.com").status == OperationStatus.SUCCESS

    assert core.register_key("alice", KEY_ALICE).status == OperationStatus.SUCCESS
    assert core.register_key("bob", KEY_BOB).status == OperationStatus.SUCCESS

    core.create_user_group("sysadmins")
    core.add_member_user_group("sysadmins", "alice")
    core.add_member_user_group("sysadmins", "bob")

    core.register_server("web-01", "10.0.0.10", 22, HOST_KEY_FAKE)
    core.register_server("web-02", "10.0.0.11", 22, HOST_KEY_FAKE)
    core.register_server("db-03", "10.0.0.30", 22, HOST_KEY_FAKE)
    core.create_server_group("producao")
    core.add_member_server_group("producao", "web-01")
    core.add_member_server_group("producao", "web-02")
    core.add_member_server_group("producao", "db-03")

    core.grant("sysadmins", "producao", PermissionLevel.SHELL)

    sub_actions = core.preview()
    assert len(sub_actions) == 6
    assert all(s.action == ActionType.ADD_KEY for s in sub_actions)

    op_apply = core.apply()
    assert op_apply.status == OperationStatus.SUCCESS
    assert all(s.status == "success" for s in op_apply.sub_actions)

    for hostname in ["web-01", "web-02", "db-03"]:
        server = core.store.get_server(hostname)
        assert len(server.installed_keys) == 2

    assert core.preview() == []

    op_apply_2 = core.apply()
    assert op_apply_2.status == OperationStatus.SUCCESS
    assert op_apply_2.sub_actions == []

    core.desabilitar_user("bob")
    sub_actions_to_remove = core.preview()
    assert len(sub_actions_to_remove) == 3
    assert all(s.action == ActionType.REMOVE_KEY for s in sub_actions_to_remove)
    core.apply()

    for hostname in ["web-01", "web-02", "db-03"]:
        server = core.store.get_server(hostname)
        assert len(server.installed_keys) == 1

    ok, _ = core.auditor.verify_chain()
    assert ok is True

    ops = core.auditor.list_operations()
    assert len(ops) >= 14
    assert any(op.command == "apply" for op in ops)


def test_apply_with_partial_failure(state_dir):
    from adminforge.auditor.jsonl_auditor import JsonlAuditor
    from adminforge.store.json_store import JsonStore

    deployer = DryRunDeployer(fail_on={"db-03"})
    store = JsonStore(state_dir)
    auditor = JsonlAuditor(state_dir / "history.jsonl")
    core = Core(store, auditor, deployer, superadmin="operador")

    core.cadastrar_user("alice", "Alice", "m@e.com")
    core.register_key("alice", KEY_ALICE)
    core.create_user_group("sa")
    core.add_member_user_group("sa", "alice")
    core.register_server("web-01", "10.0.0.10", 22, HOST_KEY_FAKE)
    core.register_server("db-03", "10.0.0.30", 22, HOST_KEY_FAKE)
    core.create_server_group("prod")
    core.add_member_server_group("prod", "web-01")
    core.add_member_server_group("prod", "db-03")
    core.grant("sa", "prod", PermissionLevel.SHELL)

    op = core.apply()
    assert op.status == OperationStatus.PARTIAL_SUCCESS
    assert sum(1 for s in op.sub_actions if s.status == "success") == 1
    assert sum(1 for s in op.sub_actions if s.status == "failure") == 1

    pending = core.preview()
    assert len(pending) == 1
    assert pending[0].server == "db-03"
    assert pending[0].action == ActionType.ADD_KEY


def test_audit_server_dry_run(core: Core):
    core.register_server("web-01", "10.0.0.10", 22, HOST_KEY_FAKE)
    op, report = core.audit_server("web-01")
    assert op.status == OperationStatus.SUCCESS
    for key in ("users", "groups", "servicos", "sudoers_arquivos", "sudoers_regras"):
        assert key in report
