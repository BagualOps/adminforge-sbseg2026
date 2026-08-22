"""Tests for the planner: desired state, delta against the observed state, and the resulting subactions."""

import pytest

from adminforge.core.core import Core
from adminforge.domain import PermissionLevel, ActionType
from adminforge.planner.planner import InstalledKey, _merge_profile

from .conftest import KEY_ALICE, KEY_BOB, HOST_KEY_FAKE


SHELL = PermissionLevel.SHELL
SUDO = PermissionLevel.SUDO


def _ch(level: PermissionLevel, profile: str | None) -> InstalledKey:
    return InstalledKey(ref="x:fp", username="x", level=level, profile=profile)


@pytest.mark.parametrize("existente,perm_level,perm_profile,final_level,esperado", [
    # apenas shell — profile nao se aplica
    (None,             SHELL, None, SHELL, None),
    (_ch(SHELL, None), SHELL, None, SHELL, None),
    # primeira vez (existente=None) com SUDO
    (None,             SUDO,  None, SUDO,  None),
    (None,             SUDO,  "p1", SUDO,  "p1"),
    # SHELL preexistente + entrante SUDO -> profile do entrante (regressao da PR)
    (_ch(SHELL, None), SUDO,  "p2", SUDO,  "p2"),
    (_ch(SHELL, None), SUDO,  None, SUDO,  None),
    # SUDO existente + entrante SHELL -> mantem profile existente (max level = SUDO)
    (_ch(SUDO, "p1"),  SHELL, None, SUDO,  "p1"),
    (_ch(SUDO, None),  SHELL, None, SUDO,  None),
    # ambos SUDO, full prevalece (qualquer um sem profile -> None)
    (_ch(SUDO, "p1"),  SUDO,  None, SUDO,  None),
    (_ch(SUDO, None),  SUDO,  "p2", SUDO,  None),
    (_ch(SUDO, None),  SUDO,  None, SUDO,  None),
    # ambos SUDO com profile -> mantem existente (estavel, ordem de processamento nao quebra)
    (_ch(SUDO, "p1"),  SUDO,  "p2", SUDO,  "p1"),
    (_ch(SUDO, "p1"),  SUDO,  "p1", SUDO,  "p1"),
])
def test_merge_profile(existente, perm_level, perm_profile, final_level, esperado):
    assert _merge_profile(existente, perm_level, perm_profile, final_level) == esperado


def _setup_basico(core: Core) -> None:
    assert core.cadastrar_user("alice", "Alice", "m@e.com").status.value == "success"
    assert core.cadastrar_user("bob", "Bob", "r@e.com").status.value == "success"
    assert core.register_key("alice", KEY_ALICE).status.value == "success"
    assert core.register_key("bob", KEY_BOB).status.value == "success"
    assert core.create_user_group("sysadmins").status.value == "success"
    assert core.add_member_user_group("sysadmins", "alice").status.value == "success"
    assert core.add_member_user_group("sysadmins", "bob").status.value == "success"
    assert core.register_server("web-01", "10.0.0.10", 22, HOST_KEY_FAKE).status.value == "success"
    assert core.register_server("web-02", "10.0.0.11", 22, HOST_KEY_FAKE).status.value == "success"
    assert core.create_server_group("producao").status.value == "success"
    assert core.add_member_server_group("producao", "web-01").status.value == "success"
    assert core.add_member_server_group("producao", "web-02").status.value == "success"


def test_empty_preview_without_permission(core: Core):
    _setup_basico(core)
    assert core.preview() == []


def test_preview_lista_subacoes_apos_grant(core: Core):
    _setup_basico(core)
    core.grant("sysadmins", "producao", PermissionLevel.SHELL)
    sub_actions = core.preview()
    assert len(sub_actions) == 4
    servers = {s.server for s in sub_actions}
    assert servers == {"web-01", "web-02"}
    assert all(s.action == ActionType.ADD_KEY for s in sub_actions)


def test_inactive_user_leaves_desired_state(core: Core):
    _setup_basico(core)
    core.grant("sysadmins", "producao", PermissionLevel.SHELL)
    core.apply()
    core.desabilitar_user("bob")
    sub_actions = core.preview()
    assert len(sub_actions) == 2
    assert all(s.action == ActionType.REMOVE_KEY for s in sub_actions)
    assert all(s.username == "bob" for s in sub_actions)


def test_profile_propagated_to_sub_action(core: Core):
    _setup_basico(core)
    core.create_sudo_profile("read-logs", ["/bin/journalctl"])
    core.grant("sysadmins", "producao", PermissionLevel.SUDO, profile="read-logs")
    subs = [s for s in core.preview() if s.action == ActionType.ADD_KEY]
    assert subs
    for s in subs:
        assert s.profile == "read-logs"
        assert s.profile_commands == ["/bin/journalctl"]


def test_existing_shell_does_not_swallow_new_sudo_profile(core: Core):
    """Regression: a pre-existing SHELL plus an incoming SUDO(profile) must not become full sudo."""
    _setup_basico(core)
    core.create_sudo_profile("limited", ["/bin/journalctl"])
    core.create_user_group("ops")
    core.add_member_user_group("ops", "alice")
    # primeiro: shell para sysadmins (alice esta dentro)
    core.grant("sysadmins", "producao", PermissionLevel.SHELL)
    # depois: sudo restrito para ops
    core.grant("ops", "producao", PermissionLevel.SUDO, profile="limited")
    alice = [s for s in core.preview() if s.username == "alice"]
    assert alice
    for s in alice:
        # level final eh sudo, MAS profile do entrante deve ser preservado
        assert s.level == PermissionLevel.SUDO
        assert s.profile == "limited"
        assert s.profile_commands == ["/bin/journalctl"]


def test_missing_profile_fails_instead_of_full_sudo(core: Core):
    """Regression: a profile that is referenced but absent from the state must not become NOPASSWD:ALL."""
    from adminforge.exceptions import InvalidState
    _setup_basico(core)
    core.create_sudo_profile("p", ["/bin/journalctl"])
    core.grant("sysadmins", "producao", PermissionLevel.SUDO, profile="p")
    # apaga profile direto no store, simulando state corrompido
    core.store.delete_sudo_profile("p")
    with pytest.raises(InvalidState):
        core.preview()


def test_full_sudo_prevalece_sobre_profile(core: Core):
    _setup_basico(core)
    core.create_sudo_profile("limited", ["/bin/journalctl"])
    core.create_user_group("ops")
    core.add_member_user_group("ops", "alice")
    core.grant("sysadmins", "producao", PermissionLevel.SUDO, profile="limited")
    core.grant("ops", "producao", PermissionLevel.SUDO)  # full sudo
    alice = [s for s in core.preview() if s.username == "alice"]
    assert alice
    for s in alice:
        assert s.profile is None
        assert s.profile_commands is None


def test_sudo_prevalece_sobre_shell(core: Core):
    _setup_basico(core)
    core.create_user_group("dba")
    core.add_member_user_group("dba", "alice")
    core.grant("sysadmins", "producao", PermissionLevel.SHELL)
    core.grant("dba", "producao", PermissionLevel.SUDO)
    subacoes_alice = [s for s in core.preview() if s.username == "alice"]
    assert all(s.level == PermissionLevel.SUDO for s in subacoes_alice)