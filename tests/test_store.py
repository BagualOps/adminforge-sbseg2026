from pathlib import Path

import pytest

from adminforge.domain import GrupoUser, NivelPermissao, Permissao, Servidor, SudoProfile, User
from adminforge.exceptions import LockOcupado
from adminforge.store.json_store import JsonStore


def test_lockfile_concorrencia(tmp_path: Path):
    a = JsonStore(tmp_path)
    b = JsonStore(tmp_path)
    a.lock()
    try:
        with pytest.raises(LockOcupado):
            b.lock()
    finally:
        a.unlock()
    b.lock()
    b.unlock()


def test_save_user_permissao_0600(tmp_path: Path):
    s = JsonStore(tmp_path)
    s.save_user(User(username="alice", nome="Alice", email="m@e.com"))
    arquivo = tmp_path / "users" / "alice.json"
    assert arquivo.exists()
    modo = oct(arquivo.stat().st_mode)[-3:]
    assert modo == "600"


def test_roundtrip_servidor(tmp_path: Path):
    s = JsonStore(tmp_path)
    serv = Servidor(
        hostname="web-01",
        ipv4="10.0.0.10",
        porta_ssh=22,
        chave_host="ssh-ed25519 AAAA...",
        chaves_instaladas=[{"ref": "alice:fp", "username": "alice", "nivel": "sudo"}],
    )
    s.save_servidor(serv)
    lido = s.get_servidor("web-01")
    assert lido is not None
    assert lido.ipv4 == "10.0.0.10"
    assert lido.chaves_instaladas[0]["ref"] == "alice:fp"


def test_permissao_atualiza_em_vez_de_duplicar(tmp_path: Path):
    s = JsonStore(tmp_path)
    s.save_permissao(Permissao(grupo_user="sa", grupo_servidor="prod", nivel=NivelPermissao.SHELL))
    s.save_permissao(Permissao(grupo_user="sa", grupo_servidor="prod", nivel=NivelPermissao.SUDO))
    perms = s.list_permissoes()
    assert len(perms) == 1
    assert perms[0].nivel == NivelPermissao.SUDO


def test_delete_grupo(tmp_path: Path):
    s = JsonStore(tmp_path)
    s.save_grupo_user(GrupoUser(nome="sa", membros=["x"]))
    assert s.get_grupo_user("sa") is not None
    s.delete_grupo_user("sa")
    assert s.get_grupo_user("sa") is None


def test_sudo_profile_roundtrip(tmp_path: Path):
    s = JsonStore(tmp_path)
    profile = SudoProfile(nome="read-logs", comandos=["/bin/journalctl", "/bin/cat /var/log/*"])
    s.save_sudo_profile(profile)

    lido = s.get_sudo_profile("read-logs")
    assert lido is not None
    assert lido.nome == "read-logs"
    assert lido.comandos == ["/bin/journalctl", "/bin/cat /var/log/*"]

    arquivo = tmp_path / "sudo-profiles" / "read-logs.json"
    assert arquivo.exists()
    assert oct(arquivo.stat().st_mode)[-3:] == "600"


def test_sudo_profile_list_e_delete(tmp_path: Path):
    s = JsonStore(tmp_path)
    s.save_sudo_profile(SudoProfile(nome="a", comandos=["/bin/a"]))
    s.save_sudo_profile(SudoProfile(nome="b", comandos=["/bin/b"]))
    nomes = sorted(p.nome for p in s.list_sudo_profiles())
    assert nomes == ["a", "b"]

    s.delete_sudo_profile("a")
    assert s.get_sudo_profile("a") is None
    assert [p.nome for p in s.list_sudo_profiles()] == ["b"]


def test_sudo_profile_inexistente_retorna_none(tmp_path: Path):
    s = JsonStore(tmp_path)
    assert s.get_sudo_profile("ghost") is None
    # delete de inexistente nao deve estourar (idempotente)
    s.delete_sudo_profile("ghost")
