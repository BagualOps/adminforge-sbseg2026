import pytest

from adminforge.core.nucleo import Nucleo
from adminforge.domain import NivelPermissao, TipoAcao
from adminforge.planner.planner import ChaveInstalada, _merge_profile

from .conftest import CHAVE_ALICE, CHAVE_BOB, HOST_KEY_FAKE


SHELL = NivelPermissao.SHELL
SUDO = NivelPermissao.SUDO


def _ch(nivel: NivelPermissao, profile: str | None) -> ChaveInstalada:
    return ChaveInstalada(ref="x:fp", username="x", nivel=nivel, profile=profile)


@pytest.mark.parametrize("existente,perm_nivel,perm_profile,nivel_final,esperado", [
    # apenas shell — profile nao se aplica
    (None,             SHELL, None, SHELL, None),
    (_ch(SHELL, None), SHELL, None, SHELL, None),
    # primeira vez (existente=None) com SUDO
    (None,             SUDO,  None, SUDO,  None),
    (None,             SUDO,  "p1", SUDO,  "p1"),
    # SHELL preexistente + entrante SUDO -> profile do entrante (regressao da PR)
    (_ch(SHELL, None), SUDO,  "p2", SUDO,  "p2"),
    (_ch(SHELL, None), SUDO,  None, SUDO,  None),
    # SUDO existente + entrante SHELL -> mantem profile existente (max nivel = SUDO)
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
def test_merge_profile(existente, perm_nivel, perm_profile, nivel_final, esperado):
    assert _merge_profile(existente, perm_nivel, perm_profile, nivel_final) == esperado


def _setup_basico(nucleo: Nucleo) -> None:
    assert nucleo.cadastrar_user("alice", "Alice", "m@e.com").status.value == "sucesso"
    assert nucleo.cadastrar_user("bob", "Bob", "r@e.com").status.value == "sucesso"
    assert nucleo.cadastrar_chave("alice", CHAVE_ALICE).status.value == "sucesso"
    assert nucleo.cadastrar_chave("bob", CHAVE_BOB).status.value == "sucesso"
    assert nucleo.criar_grupo_user("sysadmins").status.value == "sucesso"
    assert nucleo.adicionar_membro_grupo_user("sysadmins", "alice").status.value == "sucesso"
    assert nucleo.adicionar_membro_grupo_user("sysadmins", "bob").status.value == "sucesso"
    assert nucleo.cadastrar_servidor("web-01", "10.0.0.10", 22, HOST_KEY_FAKE).status.value == "sucesso"
    assert nucleo.cadastrar_servidor("web-02", "10.0.0.11", 22, HOST_KEY_FAKE).status.value == "sucesso"
    assert nucleo.criar_grupo_servidor("producao").status.value == "sucesso"
    assert nucleo.adicionar_membro_grupo_servidor("producao", "web-01").status.value == "sucesso"
    assert nucleo.adicionar_membro_grupo_servidor("producao", "web-02").status.value == "sucesso"


def test_preview_vazio_sem_permissao(nucleo: Nucleo):
    _setup_basico(nucleo)
    assert nucleo.preview() == []


def test_preview_lista_subacoes_apos_grant(nucleo: Nucleo):
    _setup_basico(nucleo)
    nucleo.conceder("sysadmins", "producao", NivelPermissao.SHELL)
    subacoes = nucleo.preview()
    assert len(subacoes) == 4
    servidores = {s.servidor for s in subacoes}
    assert servidores == {"web-01", "web-02"}
    assert all(s.acao == TipoAcao.ADICIONAR_CHAVE for s in subacoes)


def test_user_inativo_sai_do_estado_desejado(nucleo: Nucleo):
    _setup_basico(nucleo)
    nucleo.conceder("sysadmins", "producao", NivelPermissao.SHELL)
    nucleo.aplicar()
    nucleo.desabilitar_user("bob")
    subacoes = nucleo.preview()
    assert len(subacoes) == 2
    assert all(s.acao == TipoAcao.REMOVER_CHAVE for s in subacoes)
    assert all(s.username == "bob" for s in subacoes)


def test_profile_propagado_para_subacao(nucleo: Nucleo):
    _setup_basico(nucleo)
    nucleo.criar_sudo_profile("read-logs", ["/bin/journalctl"])
    nucleo.conceder("sysadmins", "producao", NivelPermissao.SUDO, profile="read-logs")
    subs = [s for s in nucleo.preview() if s.acao == TipoAcao.ADICIONAR_CHAVE]
    assert subs
    for s in subs:
        assert s.profile == "read-logs"
        assert s.profile_comandos == ["/bin/journalctl"]


def test_shell_existente_nao_engole_profile_de_novo_sudo(nucleo: Nucleo):
    """Regressao: SHELL pre-existente + SUDO(profile) entrante NAO pode virar full sudo."""
    _setup_basico(nucleo)
    nucleo.criar_sudo_profile("limited", ["/bin/journalctl"])
    nucleo.criar_grupo_user("ops")
    nucleo.adicionar_membro_grupo_user("ops", "alice")
    # primeiro: shell para sysadmins (alice esta dentro)
    nucleo.conceder("sysadmins", "producao", NivelPermissao.SHELL)
    # depois: sudo restrito para ops
    nucleo.conceder("ops", "producao", NivelPermissao.SUDO, profile="limited")
    alice = [s for s in nucleo.preview() if s.username == "alice"]
    assert alice
    for s in alice:
        # nivel final eh sudo, MAS profile do entrante deve ser preservado
        assert s.nivel == NivelPermissao.SUDO
        assert s.profile == "limited"
        assert s.profile_comandos == ["/bin/journalctl"]


def test_profile_inexistente_falha_em_vez_de_virar_full_sudo(nucleo: Nucleo):
    """Regressao: profile referenciado mas ausente do state nao pode virar NOPASSWD:ALL."""
    from adminforge.exceptions import EstadoInvalido
    _setup_basico(nucleo)
    nucleo.criar_sudo_profile("p", ["/bin/journalctl"])
    nucleo.conceder("sysadmins", "producao", NivelPermissao.SUDO, profile="p")
    # apaga profile direto no store, simulando state corrompido
    nucleo.store.delete_sudo_profile("p")
    with pytest.raises(EstadoInvalido):
        nucleo.preview()


def test_full_sudo_prevalece_sobre_profile(nucleo: Nucleo):
    _setup_basico(nucleo)
    nucleo.criar_sudo_profile("limited", ["/bin/journalctl"])
    nucleo.criar_grupo_user("ops")
    nucleo.adicionar_membro_grupo_user("ops", "alice")
    nucleo.conceder("sysadmins", "producao", NivelPermissao.SUDO, profile="limited")
    nucleo.conceder("ops", "producao", NivelPermissao.SUDO)  # full sudo
    alice = [s for s in nucleo.preview() if s.username == "alice"]
    assert alice
    for s in alice:
        assert s.profile is None
        assert s.profile_comandos is None


def test_sudo_prevalece_sobre_shell(nucleo: Nucleo):
    _setup_basico(nucleo)
    nucleo.criar_grupo_user("dba")
    nucleo.adicionar_membro_grupo_user("dba", "alice")
    nucleo.conceder("sysadmins", "producao", NivelPermissao.SHELL)
    nucleo.conceder("dba", "producao", NivelPermissao.SUDO)
    subacoes_alice = [s for s in nucleo.preview() if s.username == "alice"]
    assert all(s.nivel == NivelPermissao.SUDO for s in subacoes_alice)
