from adminforge.core.nucleo import Nucleo
from adminforge.domain import NivelPermissao, StatusCredencial, StatusOperacao, StatusUser

from .conftest import CHAVE_ALICE, HOST_KEY_FAKE


def test_user_duplicado(nucleo: Nucleo):
    nucleo.cadastrar_user("alice", "Alice", "m@e.com")
    op = nucleo.cadastrar_user("alice", "Outra", "x@e.com")
    assert op.status == StatusOperacao.FALHA


def test_email_invalido_e_rejeitado(nucleo: Nucleo):
    op = nucleo.cadastrar_user("bob", "Bob", "nao-email")
    assert op.status == StatusOperacao.FALHA


def test_username_invalido(nucleo: Nucleo):
    op = nucleo.cadastrar_user("Alice!", "M", "m@e.com")
    assert op.status == StatusOperacao.FALHA


def test_chave_duplicada_rejeita(nucleo: Nucleo):
    nucleo.cadastrar_user("alice", "Alice", "m@e.com")
    assert nucleo.cadastrar_chave("alice", CHAVE_ALICE).status == StatusOperacao.SUCESSO
    op = nucleo.cadastrar_chave("alice", CHAVE_ALICE)
    assert op.status == StatusOperacao.FALHA


def test_chave_para_user_inexistente(nucleo: Nucleo):
    op = nucleo.cadastrar_chave("nao-existe", CHAVE_ALICE)
    assert op.status == StatusOperacao.FALHA


def test_add_membro_idempotente(nucleo: Nucleo):
    nucleo.cadastrar_user("alice", "Alice", "m@e.com")
    nucleo.criar_grupo_user("sa")
    op1 = nucleo.adicionar_membro_grupo_user("sa", "alice")
    op2 = nucleo.adicionar_membro_grupo_user("sa", "alice")
    assert op1.status == StatusOperacao.SUCESSO
    assert op2.status == StatusOperacao.SUCESSO
    g = nucleo.store.get_grupo_user("sa")
    assert g.membros.count("alice") == 1


def test_excluir_grupo_com_permissao_associada_falha(nucleo: Nucleo):
    nucleo.criar_grupo_user("sa")
    nucleo.criar_grupo_servidor("prod")
    nucleo.conceder("sa", "prod", NivelPermissao.SHELL)
    op = nucleo.excluir_grupo_user("sa")
    assert op.status == StatusOperacao.FALHA


def test_grant_atualiza_nivel_sem_duplicar(nucleo: Nucleo):
    nucleo.criar_grupo_user("sa")
    nucleo.criar_grupo_servidor("prod")
    nucleo.conceder("sa", "prod", NivelPermissao.SHELL)
    nucleo.conceder("sa", "prod", NivelPermissao.SUDO)
    perms = nucleo.store.list_permissoes()
    assert len(perms) == 1
    assert perms[0].nivel == NivelPermissao.SUDO


def test_revoke_inexistente_falha(nucleo: Nucleo):
    op = nucleo.revogar("inexistente", "tambem-nao")
    assert op.status == StatusOperacao.FALHA


def test_desabilitar_user_revoga_credenciais(nucleo: Nucleo):
    nucleo.cadastrar_user("alice", "Alice", "m@e.com")
    nucleo.cadastrar_chave("alice", CHAVE_ALICE)
    nucleo.desabilitar_user("alice")
    a = nucleo.store.get_user("alice")
    assert a.status == StatusUser.INATIVO
    creds = nucleo.store.list_credenciais("alice")
    assert all(c.status == StatusCredencial.REVOGADA for c in creds)


def test_servidor_hostname_invalido(nucleo: Nucleo):
    op = nucleo.cadastrar_servidor("Inv@lid!", "10.0.0.1", 22, HOST_KEY_FAKE)
    assert op.status == StatusOperacao.FALHA


def test_excluir_servidor_remove_de_grupos(nucleo: Nucleo):
    nucleo.cadastrar_servidor("web-01", "10.0.0.10", 22, HOST_KEY_FAKE)
    nucleo.criar_grupo_servidor("prod")
    nucleo.adicionar_membro_grupo_servidor("prod", "web-01")
    nucleo.excluir_servidor("web-01")
    g = nucleo.store.get_grupo_servidor("prod")
    assert "web-01" not in g.membros


def test_adicionar_n_membros_de_uma_vez(nucleo: Nucleo):
    nucleo.cadastrar_user("alice", "Alice", "a@e.com")
    nucleo.cadastrar_user("bob", "Bob", "b@e.com")
    nucleo.cadastrar_user("carla", "Carla", "c@e.com")
    nucleo.criar_grupo_user("sa")
    op = nucleo.adicionar_membros_grupo_user("sa", ["alice", "bob", "carla"])
    assert op.status == StatusOperacao.SUCESSO
    g = nucleo.store.get_grupo_user("sa")
    assert g.membros == ["alice", "bob", "carla"]


def test_n_membros_falha_atomica_se_um_inexiste(nucleo: Nucleo):
    nucleo.cadastrar_user("alice", "Alice", "a@e.com")
    nucleo.criar_grupo_user("sa")
    op = nucleo.adicionar_membros_grupo_user("sa", ["alice", "fantasma"])
    assert op.status == StatusOperacao.FALHA
    g = nucleo.store.get_grupo_user("sa")
    assert g.membros == []


def test_sudo_profile_create_e_concede(nucleo: Nucleo):
    op = nucleo.criar_sudo_profile("dba-postgres", ["/bin/systemctl restart postgresql", "/usr/bin/psql"])
    assert op.status == StatusOperacao.SUCESSO
    nucleo.criar_grupo_user("dba")
    nucleo.criar_grupo_servidor("banco")
    op = nucleo.conceder("dba", "banco", NivelPermissao.SUDO, profile="dba-postgres")
    assert op.status == StatusOperacao.SUCESSO
    perms = nucleo.store.list_permissoes()
    assert perms[0].profile == "dba-postgres"


def test_sudo_profile_rejeita_comando_relativo(nucleo: Nucleo):
    op = nucleo.criar_sudo_profile("bad", ["systemctl restart nginx"])
    assert op.status == StatusOperacao.FALHA


def test_sudo_profile_rejeita_se_em_uso(nucleo: Nucleo):
    nucleo.criar_sudo_profile("p1", ["/bin/true"])
    nucleo.criar_grupo_user("g")
    nucleo.criar_grupo_servidor("s")
    nucleo.conceder("g", "s", NivelPermissao.SUDO, profile="p1")
    op = nucleo.excluir_sudo_profile("p1")
    assert op.status == StatusOperacao.FALHA


def test_profile_so_com_sudo(nucleo: Nucleo):
    nucleo.criar_sudo_profile("p", ["/bin/true"])
    nucleo.criar_grupo_user("g")
    nucleo.criar_grupo_servidor("s")
    op = nucleo.conceder("g", "s", NivelPermissao.SHELL, profile="p")
    assert op.status == StatusOperacao.FALHA


def test_remover_n_membros_de_uma_vez(nucleo: Nucleo):
    for u in ("alice", "bob", "carla"):
        nucleo.cadastrar_user(u, u.title(), f"{u}@e.com")
    nucleo.criar_grupo_user("sa")
    nucleo.adicionar_membros_grupo_user("sa", ["alice", "bob", "carla"])
    nucleo.remover_membros_grupo_user("sa", ["alice", "carla"])
    g = nucleo.store.get_grupo_user("sa")
    assert g.membros == ["bob"]
