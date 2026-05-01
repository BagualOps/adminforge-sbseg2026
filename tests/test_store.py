import os
from pathlib import Path

import pytest

from adminforge.domain import Admin, GrupoAdmin, NivelPermissao, Permissao, Servidor
from adminforge.exceptions import LockOcupado
from adminforge.store.yaml_store import YamlStore


def test_lockfile_concorrencia(tmp_path: Path):
    a = YamlStore(tmp_path)
    b = YamlStore(tmp_path)
    a.lock()
    try:
        with pytest.raises(LockOcupado):
            b.lock()
    finally:
        a.unlock()
    b.lock()
    b.unlock()


def test_save_admin_permissao_0600(tmp_path: Path):
    s = YamlStore(tmp_path)
    s.save_admin(Admin(username="marina", nome="Marina", email="m@e.com"))
    arquivo = tmp_path / "admins" / "marina.yaml"
    assert arquivo.exists()
    modo = oct(arquivo.stat().st_mode)[-3:]
    assert modo == "600"


def test_roundtrip_servidor(tmp_path: Path):
    s = YamlStore(tmp_path)
    serv = Servidor(
        hostname="web-01",
        ipv4="10.0.0.10",
        porta_ssh=22,
        chave_host="ssh-ed25519 AAAA...",
        chaves_instaladas=[{"ref": "marina:fp", "username": "marina", "nivel": "sudo"}],
    )
    s.save_servidor(serv)
    lido = s.get_servidor("web-01")
    assert lido is not None
    assert lido.ipv4 == "10.0.0.10"
    assert lido.chaves_instaladas[0]["ref"] == "marina:fp"


def test_permissao_atualiza_em_vez_de_duplicar(tmp_path: Path):
    s = YamlStore(tmp_path)
    s.save_permissao(Permissao(grupo_admin="sa", grupo_servidor="prod", nivel=NivelPermissao.SHELL))
    s.save_permissao(Permissao(grupo_admin="sa", grupo_servidor="prod", nivel=NivelPermissao.SUDO))
    perms = s.list_permissoes()
    assert len(perms) == 1
    assert perms[0].nivel == NivelPermissao.SUDO


def test_delete_grupo(tmp_path: Path):
    s = YamlStore(tmp_path)
    s.save_grupo_admin(GrupoAdmin(nome="sa", membros=["x"]))
    assert s.get_grupo_admin("sa") is not None
    s.delete_grupo_admin("sa")
    assert s.get_grupo_admin("sa") is None
