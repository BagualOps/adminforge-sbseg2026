from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4


class StatusUser(str, Enum):
    ATIVO = "ativo"
    INATIVO = "inativo"
    BLOQUEADO = "bloqueado"


class StatusCredencial(str, Enum):
    ATIVA = "ativa"
    REVOGADA = "revogada"


class NivelPermissao(str, Enum):
    SHELL = "shell"
    SUDO = "sudo"


class StatusOperacao(str, Enum):
    SUCESSO = "sucesso"
    FALHA = "falha"
    SUCESSO_PARCIAL = "sucesso_parcial"
    EM_ANDAMENTO = "em_andamento"
    ABORTADA = "abortada"


class TipoAcao(str, Enum):
    ADICIONAR_CHAVE = "adicionar_chave"
    REMOVER_CHAVE = "remover_chave"
    LEITURA = "leitura"


@dataclass
class User:
    username: str
    nome: str
    email: str
    status: StatusUser = StatusUser.ATIVO
    id: UUID = field(default_factory=uuid4)


@dataclass
class CredencialSSH:
    username: str
    chave_publica: str
    fingerprint: str
    status: StatusCredencial = StatusCredencial.ATIVA
    id: UUID = field(default_factory=uuid4)

    @property
    def referencia(self) -> str:
        return f"{self.username}:{self.fingerprint}"


@dataclass
class GrupoUser:
    nome: str
    membros: list[str] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)


@dataclass
class Servidor:
    hostname: str
    ipv4: str
    porta_ssh: int = 22
    chave_host: str = ""
    chaves_instaladas: list = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)


@dataclass
class GrupoServidor:
    nome: str
    membros: list[str] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)


@dataclass
class SudoProfile:
    nome: str
    comandos: list[str] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)


@dataclass
class Permissao:
    grupo_user: str
    grupo_servidor: str
    nivel: NivelPermissao
    profile: str | None = None
    id: UUID = field(default_factory=uuid4)


@dataclass
class Subacao:
    servidor: str
    acao: TipoAcao
    credencial: str | None = None
    chave_publica: str | None = None
    username: str | None = None
    nivel: NivelPermissao | None = None
    profile: str | None = None
    profile_comandos: list[str] | None = None
    status: str = "pendente"
    erro: str | None = None
    mensagem: str | None = None


@dataclass
class Operacao:
    id: str
    momento: datetime
    superadmin: str
    comando: str
    status: StatusOperacao
    subacoes: list[Subacao] = field(default_factory=list)
    hash_anterior: str | None = None
    hash: str | None = None
