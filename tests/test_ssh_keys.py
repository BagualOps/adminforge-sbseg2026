"""Tests for SSH key parsing, fingerprinting, and validation."""

import pytest

from adminforge import ssh_keys
from adminforge.exceptions import InvalidFormat

from .conftest import KEY_ALICE


def test_parse_ed25519_ok():
    tipo, blob, comentario = ssh_keys.parse_public_key(KEY_ALICE)
    assert tipo == "ssh-ed25519"
    assert blob.startswith("AAAA")
    assert comentario == "alice@laptop"


def test_fingerprint_estavel():
    f1 = ssh_keys.fingerprint(KEY_ALICE)
    f2 = ssh_keys.fingerprint(KEY_ALICE + "\n")
    assert f1 == f2
    assert f1.startswith("SHA256:")


def test_canonical_key_strips_extra_space():
    c = ssh_keys.canonical_key("  " + KEY_ALICE + "  \n")
    assert c == KEY_ALICE


def test_tipo_nao_suportado():
    with pytest.raises(InvalidFormat):
        ssh_keys.parse_public_key("ssh-dss AAAA bla")


def test_empty_key():
    with pytest.raises(InvalidFormat):
        ssh_keys.parse_public_key("")


def test_payload_base64_invalido():
    with pytest.raises(InvalidFormat):
        ssh_keys.parse_public_key("ssh-ed25519 NAO_E_BASE64!! comentario")