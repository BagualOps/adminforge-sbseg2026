import pytest

from adminforge import ssh_keys
from adminforge.exceptions import FormatoInvalido

from .conftest import CHAVE_MARINA


def test_parse_ed25519_ok():
    tipo, blob, comentario = ssh_keys.parse_chave_publica(CHAVE_MARINA)
    assert tipo == "ssh-ed25519"
    assert blob.startswith("AAAA")
    assert comentario == "marina@laptop"


def test_fingerprint_estavel():
    f1 = ssh_keys.fingerprint(CHAVE_MARINA)
    f2 = ssh_keys.fingerprint(CHAVE_MARINA + "\n")
    assert f1 == f2
    assert f1.startswith("SHA256:")


def test_chave_canonica_remove_espaco_extra():
    c = ssh_keys.chave_canonica("  " + CHAVE_MARINA + "  \n")
    assert c == CHAVE_MARINA


def test_tipo_nao_suportado():
    with pytest.raises(FormatoInvalido):
        ssh_keys.parse_chave_publica("ssh-dss AAAA bla")


def test_chave_vazia():
    with pytest.raises(FormatoInvalido):
        ssh_keys.parse_chave_publica("")


def test_payload_base64_invalido():
    with pytest.raises(FormatoInvalido):
        ssh_keys.parse_chave_publica("ssh-ed25519 NAO_E_BASE64!! comentario")
