"""Localizacao da CLI (pt-br). Garante que: default e ingles; ADMINFORGE_LANG=pt
traduz help e mensagens; chave sem traducao cai para o ingles; o ingles preserva
o texto original (para nao quebrar quem faz grep na saida)."""
from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from adminforge import i18n
from adminforge.cli.main import main


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("ADMINFORGE_STATE", str(state))
    monkeypatch.setenv("ADMINFORGE_SUPERADMIN", "operador")
    monkeypatch.delenv("ADMINFORGE_LANG", raising=False)
    return {"state": str(state)}


@pytest.fixture(autouse=True)
def _reset_lang():
    i18n.set_lang(None)
    yield
    i18n.set_lang(None)


def _run(argv, lang=None):
    if lang is not None:
        i18n.set_lang(lang)
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            main(argv)
    except SystemExit:
        pass
    return buf.getvalue()


def test_t_default_en():
    assert i18n.t("List users.") == "List users."


def test_t_pt_traduz():
    i18n.set_lang("pt")
    assert i18n.t("List users.") == "Lista usuarios."
    i18n.set_lang("pt_BR")
    assert i18n.t("List users.") == "Lista usuarios."


def test_t_chave_desconhecida_cai_para_ingles():
    i18n.set_lang("pt")
    assert i18n.t("this string is not in the catalog") == "this string is not in the catalog"


def test_help_ingles_por_padrao(env):
    out = _run(["--help"])
    assert "privileged identity management" in out
    assert "gestao de identidades" not in out


def test_help_portugues_com_lang(env):
    out = _run(["permission", "--help"], lang="pt")
    assert "Concede acesso" in out  # help do subcomando grant, traduzido
    assert "Manage permissions" not in out


def test_mensagem_de_erro_traduzida(env):
    out = _run(["user", "add", "--username", "Bad!", "--name", "x", "--email", "no"], lang="pt")
    assert "username invalido" in out


def test_mensagem_de_erro_ingles_por_padrao(env):
    out = _run(["user", "add", "--username", "Bad!", "--name", "x", "--email", "no"])
    assert "invalid username" in out
