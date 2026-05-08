"""Fluxo end-to-end: cadastro -> grupos -> grant -> preview -> apply -> audit -> verify."""
from __future__ import annotations

from adminforge.core.nucleo import Nucleo
from adminforge.deployer.dry_run import DryRunDeployer
from adminforge.domain import NivelPermissao, StatusOperacao, TipoAcao

from .conftest import CHAVE_ALICE, CHAVE_BOB, HOST_KEY_FAKE


def test_fluxo_completo(nucleo: Nucleo):
    assert nucleo.cadastrar_user("alice", "Alice", "m@empresa.com").status == StatusOperacao.SUCESSO
    assert nucleo.cadastrar_user("bob", "Bob", "bob@empresa.com").status == StatusOperacao.SUCESSO

    assert nucleo.cadastrar_chave("alice", CHAVE_ALICE).status == StatusOperacao.SUCESSO
    assert nucleo.cadastrar_chave("bob", CHAVE_BOB).status == StatusOperacao.SUCESSO

    nucleo.criar_grupo_user("sysadmins")
    nucleo.adicionar_membro_grupo_user("sysadmins", "alice")
    nucleo.adicionar_membro_grupo_user("sysadmins", "bob")

    nucleo.cadastrar_servidor("web-01", "10.0.0.10", 22, HOST_KEY_FAKE)
    nucleo.cadastrar_servidor("web-02", "10.0.0.11", 22, HOST_KEY_FAKE)
    nucleo.cadastrar_servidor("db-03", "10.0.0.30", 22, HOST_KEY_FAKE)
    nucleo.criar_grupo_servidor("producao")
    nucleo.adicionar_membro_grupo_servidor("producao", "web-01")
    nucleo.adicionar_membro_grupo_servidor("producao", "web-02")
    nucleo.adicionar_membro_grupo_servidor("producao", "db-03")

    nucleo.conceder("sysadmins", "producao", NivelPermissao.SHELL)

    subacoes = nucleo.preview()
    assert len(subacoes) == 6
    assert all(s.acao == TipoAcao.ADICIONAR_CHAVE for s in subacoes)

    op_apply = nucleo.aplicar()
    assert op_apply.status == StatusOperacao.SUCESSO
    assert all(s.status == "sucesso" for s in op_apply.subacoes)

    for hostname in ["web-01", "web-02", "db-03"]:
        servidor = nucleo.store.get_servidor(hostname)
        assert len(servidor.chaves_instaladas) == 2

    assert nucleo.preview() == []

    op_apply_2 = nucleo.aplicar()
    assert op_apply_2.status == StatusOperacao.SUCESSO
    assert op_apply_2.subacoes == []

    nucleo.desabilitar_user("bob")
    subacoes_remover = nucleo.preview()
    assert len(subacoes_remover) == 3
    assert all(s.acao == TipoAcao.REMOVER_CHAVE for s in subacoes_remover)
    nucleo.aplicar()

    for hostname in ["web-01", "web-02", "db-03"]:
        servidor = nucleo.store.get_servidor(hostname)
        assert len(servidor.chaves_instaladas) == 1

    ok, _ = nucleo.auditor.verificar_cadeia()
    assert ok is True

    ops = nucleo.auditor.listar()
    assert len(ops) >= 14
    assert any(op.comando == "apply" for op in ops)


def test_apply_com_falha_parcial(state_dir):
    from adminforge.auditor.jsonl_auditor import JsonlAuditor
    from adminforge.store.json_store import JsonStore

    deployer = DryRunDeployer(falhar_em={"db-03"})
    store = JsonStore(state_dir)
    auditor = JsonlAuditor(state_dir / "history.jsonl")
    nucleo = Nucleo(store, auditor, deployer, superadmin="operador")

    nucleo.cadastrar_user("alice", "Alice", "m@e.com")
    nucleo.cadastrar_chave("alice", CHAVE_ALICE)
    nucleo.criar_grupo_user("sa")
    nucleo.adicionar_membro_grupo_user("sa", "alice")
    nucleo.cadastrar_servidor("web-01", "10.0.0.10", 22, HOST_KEY_FAKE)
    nucleo.cadastrar_servidor("db-03", "10.0.0.30", 22, HOST_KEY_FAKE)
    nucleo.criar_grupo_servidor("prod")
    nucleo.adicionar_membro_grupo_servidor("prod", "web-01")
    nucleo.adicionar_membro_grupo_servidor("prod", "db-03")
    nucleo.conceder("sa", "prod", NivelPermissao.SHELL)

    op = nucleo.aplicar()
    assert op.status == StatusOperacao.SUCESSO_PARCIAL
    assert sum(1 for s in op.subacoes if s.status == "sucesso") == 1
    assert sum(1 for s in op.subacoes if s.status == "falha") == 1

    pendentes = nucleo.preview()
    assert len(pendentes) == 1
    assert pendentes[0].servidor == "db-03"
    assert pendentes[0].acao == TipoAcao.ADICIONAR_CHAVE


def test_audit_server_dry_run(nucleo: Nucleo):
    nucleo.cadastrar_servidor("web-01", "10.0.0.10", 22, HOST_KEY_FAKE)
    op, relatorio = nucleo.auditar_servidor("web-01")
    assert op.status == StatusOperacao.SUCESSO
    for chave in ("usuarios", "grupos", "servicos", "sudoers_arquivos", "sudoers_regras"):
        assert chave in relatorio
