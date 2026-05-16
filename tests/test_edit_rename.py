"""Edits e renames de entidades (user, server, grupos, sudo-profile) — incluindo
cascateamento das referencias (membros de grupos, permissoes)."""
from __future__ import annotations

from adminforge.core.nucleo import Nucleo
from adminforge.domain import NivelPermissao, StatusOperacao

from .conftest import CHAVE_ALICE, HOST_KEY_FAKE


def _setup(nucleo: Nucleo) -> None:
    nucleo.cadastrar_user("alice", "Alice", "alice@e.com")
    nucleo.cadastrar_chave("alice", CHAVE_ALICE)
    nucleo.criar_grupo_user("sa")
    nucleo.adicionar_membro_grupo_user("sa", "alice")
    nucleo.cadastrar_servidor("web-01", "10.0.0.10", 22, HOST_KEY_FAKE)
    nucleo.criar_grupo_servidor("prod")
    nucleo.adicionar_membro_grupo_servidor("prod", "web-01")
    nucleo.conceder("sa", "prod", NivelPermissao.SUDO)


# ---------- editar_user ----------

def test_editar_user_nome_e_email(nucleo: Nucleo):
    _setup(nucleo)
    op = nucleo.editar_user("alice", nome="Alice Souza", email="alice@empresa.com")
    assert op.status == StatusOperacao.SUCESSO
    u = nucleo.store.get_user("alice")
    assert u.nome == "Alice Souza" and u.email == "alice@empresa.com"


def test_editar_user_preserva_credenciais(nucleo: Nucleo):
    _setup(nucleo)
    creds_antes = nucleo.store.list_credenciais("alice")
    nucleo.editar_user("alice", nome="Alice S.")
    assert nucleo.store.list_credenciais("alice") == creds_antes


def test_editar_user_email_invalido_falha(nucleo: Nucleo):
    _setup(nucleo)
    op = nucleo.editar_user("alice", email="nao-email")
    assert op.status == StatusOperacao.FALHA


def test_editar_user_inexistente_falha(nucleo: Nucleo):
    op = nucleo.editar_user("fantasma", nome="X")
    assert op.status == StatusOperacao.FALHA


# ---------- renomear_user ----------

def test_renomear_user_cascateia_para_grupos(nucleo: Nucleo):
    _setup(nucleo)
    op = nucleo.renomear_user("alice", "alicia")
    assert op.status == StatusOperacao.SUCESSO
    assert nucleo.store.get_user("alice") is None
    assert nucleo.store.get_user("alicia") is not None
    assert "alicia" in nucleo.store.get_grupo_user("sa").membros
    assert "alice" not in nucleo.store.get_grupo_user("sa").membros


def test_renomear_user_preserva_credenciais(nucleo: Nucleo):
    _setup(nucleo)
    fps_antes = {c.fingerprint for c in nucleo.store.list_credenciais("alice")}
    nucleo.renomear_user("alice", "alicia")
    fps_depois = {c.fingerprint for c in nucleo.store.list_credenciais("alicia")}
    assert fps_antes == fps_depois


def test_renomear_user_para_existente_falha(nucleo: Nucleo):
    _setup(nucleo)
    nucleo.cadastrar_user("bob", "Bob", "b@e.com")
    op = nucleo.renomear_user("alice", "bob")
    assert op.status == StatusOperacao.FALHA
    assert nucleo.store.get_user("alice") is not None


def test_renomear_user_invalido_falha(nucleo: Nucleo):
    _setup(nucleo)
    op = nucleo.renomear_user("alice", "Alice!")
    assert op.status == StatusOperacao.FALHA


def test_renomear_user_idempotente_mesmo_nome(nucleo: Nucleo):
    _setup(nucleo)
    op = nucleo.renomear_user("alice", "alice")
    assert op.status == StatusOperacao.SUCESSO


# ---------- editar_servidor ----------

def test_editar_servidor_ip_porta(nucleo: Nucleo):
    _setup(nucleo)
    op = nucleo.editar_servidor("web-01", ipv4="10.0.0.99", porta=2222)
    assert op.status == StatusOperacao.SUCESSO
    s = nucleo.store.get_servidor("web-01")
    assert s.ipv4 == "10.0.0.99" and s.porta_ssh == 2222


def test_editar_servidor_porta_invalida_falha(nucleo: Nucleo):
    _setup(nucleo)
    op = nucleo.editar_servidor("web-01", porta=70000)
    assert op.status == StatusOperacao.FALHA


def test_editar_servidor_ipv4_octeto_fora_de_faixa_falha(nucleo: Nucleo):
    _setup(nucleo)
    op = nucleo.editar_servidor("web-01", ipv4="999.999.999.999")
    assert op.status == StatusOperacao.FALHA
    assert nucleo.store.get_servidor("web-01").ipv4 == "10.0.0.10"


def test_cadastrar_servidor_ipv4_octeto_fora_de_faixa_falha(nucleo: Nucleo):
    op = nucleo.cadastrar_servidor("web-99", "10.0.0.300", 22, HOST_KEY_FAKE)
    assert op.status == StatusOperacao.FALHA


def test_editar_servidor_preserva_chaves_instaladas(nucleo: Nucleo):
    _setup(nucleo)
    s = nucleo.store.get_servidor("web-01")
    s.chaves_instaladas = [{"ref": "alice:SHA256:x", "username": "alice", "nivel": "sudo"}]
    nucleo.store.save_servidor(s)
    nucleo.editar_servidor("web-01", ipv4="10.0.0.99")
    assert nucleo.store.get_servidor("web-01").chaves_instaladas == [
        {"ref": "alice:SHA256:x", "username": "alice", "nivel": "sudo"}
    ]


# ---------- renomear_servidor ----------

def test_renomear_servidor_cascateia_para_server_group(nucleo: Nucleo):
    _setup(nucleo)
    op = nucleo.renomear_servidor("web-01", "web-001")
    assert op.status == StatusOperacao.SUCESSO
    assert nucleo.store.get_servidor("web-01") is None
    assert nucleo.store.get_servidor("web-001") is not None
    assert "web-001" in nucleo.store.get_grupo_servidor("prod").membros


# ---------- renomear_grupo_user ----------

def test_renomear_grupo_user_cascateia_para_permissoes(nucleo: Nucleo):
    _setup(nucleo)
    op = nucleo.renomear_grupo_user("sa", "sysadmins")
    assert op.status == StatusOperacao.SUCESSO
    assert nucleo.store.get_grupo_user("sa") is None
    assert nucleo.store.get_grupo_user("sysadmins") is not None
    perms = nucleo.store.list_permissoes()
    assert any(p.grupo_user == "sysadmins" for p in perms)
    assert not any(p.grupo_user == "sa" for p in perms)


# ---------- renomear_grupo_servidor ----------

def test_renomear_grupo_servidor_cascateia_para_permissoes(nucleo: Nucleo):
    _setup(nucleo)
    op = nucleo.renomear_grupo_servidor("prod", "producao")
    assert op.status == StatusOperacao.SUCESSO
    perms = nucleo.store.list_permissoes()
    assert all(p.grupo_servidor == "producao" for p in perms)


# ---------- renomear_sudo_profile ----------

def test_renomear_sudo_profile_cascateia_para_permissoes(nucleo: Nucleo):
    _setup(nucleo)
    nucleo.criar_sudo_profile("db-ops", ["/bin/journalctl"])
    nucleo.conceder("sa", "prod", NivelPermissao.SUDO, profile="db-ops")
    op = nucleo.renomear_sudo_profile("db-ops", "logs")
    assert op.status == StatusOperacao.SUCESSO
    assert nucleo.store.get_sudo_profile("db-ops") is None
    assert nucleo.store.get_sudo_profile("logs") is not None
    perms = nucleo.store.list_permissoes()
    assert perms[0].profile == "logs"
