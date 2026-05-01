from adminforge.core.nucleo import Nucleo
from adminforge.domain import NivelPermissao, StatusAdmin, TipoAcao

from .conftest import CHAVE_MARINA, CHAVE_RUI, HOST_KEY_FAKE


def _setup_basico(nucleo: Nucleo) -> None:
    assert nucleo.cadastrar_admin("marina", "Marina", "m@e.com").status.value == "sucesso"
    assert nucleo.cadastrar_admin("rui", "Rui", "r@e.com").status.value == "sucesso"
    assert nucleo.cadastrar_chave("marina", CHAVE_MARINA).status.value == "sucesso"
    assert nucleo.cadastrar_chave("rui", CHAVE_RUI).status.value == "sucesso"
    assert nucleo.criar_grupo_admin("sysadmins").status.value == "sucesso"
    assert nucleo.adicionar_membro_grupo_admin("sysadmins", "marina").status.value == "sucesso"
    assert nucleo.adicionar_membro_grupo_admin("sysadmins", "rui").status.value == "sucesso"
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


def test_admin_inativo_sai_do_estado_desejado(nucleo: Nucleo):
    _setup_basico(nucleo)
    nucleo.conceder("sysadmins", "producao", NivelPermissao.SHELL)
    nucleo.aplicar()
    nucleo.desabilitar_admin("rui")
    subacoes = nucleo.preview()
    assert len(subacoes) == 2
    assert all(s.acao == TipoAcao.REMOVER_CHAVE for s in subacoes)
    assert all(s.username == "rui" for s in subacoes)


def test_sudo_prevalece_sobre_shell(nucleo: Nucleo):
    _setup_basico(nucleo)
    nucleo.criar_grupo_admin("dba")
    nucleo.adicionar_membro_grupo_admin("dba", "marina")
    nucleo.conceder("sysadmins", "producao", NivelPermissao.SHELL)
    nucleo.conceder("dba", "producao", NivelPermissao.SUDO)
    subacoes_marina = [s for s in nucleo.preview() if s.username == "marina"]
    assert all(s.nivel == NivelPermissao.SUDO for s in subacoes_marina)
