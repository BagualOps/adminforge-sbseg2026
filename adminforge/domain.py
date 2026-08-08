"""Domain model for AdminForge: the entities the tool manages -- users, SSH
credentials ("keys"), servers, groups (of users and of servers) and access
grants -- plus the audit trail of operations performed against them.

These are plain dataclasses and enums with no behavior of their own; the
rest of the codebase (planner, deployer, store, auditor) operates on these
shapes rather than on raw dicts, so this module is the place to look up
the exact fields and invariants of each entity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4


class StatusUser(str, Enum):
    """Lifecycle state of a `User`.

    Only `ATIVO` users are picked up by the planner for key deployment
    (see `planner.planner.Planner.estado_desejado`); `INATIVO` and
    `BLOQUEADO` are both non-active but kept as separate values so audits
    can distinguish a routine pause from a block for cause. Inherits from
    `str` so it serializes to its literal value in JSON/store files.
    """

    ATIVO = "ativo"
    INATIVO = "inativo"
    BLOQUEADO = "bloqueado"


class StatusCredencial(str, Enum):
    """Lifecycle state of a `CredencialSSH`.

    Revoking a key does not delete its record: the credential is kept and
    flipped to `REVOGADA` so the audit trail can tell "never granted" apart
    from "granted, then removed". Only `ATIVA` credentials are considered
    for deployment.
    """

    ATIVA = "ativa"
    REVOGADA = "revogada"


class NivelPermissao(str, Enum):
    """Access level a `Permissao` grants: `SHELL` for plain SSH/file
    access, `SUDO` for root via sudo.

    `SUDO` alone, with no `SudoProfile` referenced from `Permissao.profile`,
    means unrestricted `NOPASSWD:ALL`; a profile narrows it to a whitelist
    of commands. See `planner.planner._merge_profile` for how level and
    profile are combined when a user holds more than one grant to the same
    server.
    """

    SHELL = "shell"
    SUDO = "sudo"


class StatusOperacao(str, Enum):
    """Outcome of an `Operacao` once the deployer has run it.

    `SUCESSO_PARCIAL` exists because one operation can touch several
    servers/subacoes independently: if some succeed and others fail, the
    operation is neither a clean `SUCESSO` nor a full `FALHA`, and callers
    (CLI, auditor) need that distinction to decide whether a retry or a
    manual fix-up is required.
    """

    SUCESSO = "sucesso"
    FALHA = "falha"
    SUCESSO_PARCIAL = "sucesso_parcial"
    EM_ANDAMENTO = "em_andamento"
    ABORTADA = "abortada"


class TipoAcao(str, Enum):
    """Kind of change a `Subacao` performs against a server's
    `authorized_keys` file: add a key, remove a key, or a read-only
    inspection (`LEITURA`) that writes nothing.
    """

    ADICIONAR_CHAVE = "adicionar_chave"
    REMOVER_CHAVE = "remover_chave"
    LEITURA = "leitura"


@dataclass
class User:
    """A managed operator account: the identity that SSH credentials and
    group membership (and, transitively, access grants) attach to.

    The store keys records by `username`, not by `id`; `id` is a UUID
    surrogate that is persisted alongside the record but is not used for
    lookups anywhere in this codebase (see `interfaces.store.IStore`).
    """

    username: str
    nome: str
    email: str
    status: StatusUser = StatusUser.ATIVO
    id: UUID = field(default_factory=uuid4)


@dataclass
class CredencialSSH:
    """An SSH public key registered for a `User`, plus its lifecycle status.

    Looked up by `fingerprint`, not by `id` (see
    `interfaces.store.IStore.get_credencial_por_fingerprint`): fingerprint
    is what a user cannot register twice and what operators recognize on
    the wire. `chave_publica` is expected to already be in canonical form
    (see `ssh_keys.chave_canonica`); this class does not normalize it.
    """

    username: str
    chave_publica: str
    fingerprint: str
    status: StatusCredencial = StatusCredencial.ATIVA
    id: UUID = field(default_factory=uuid4)

    @property
    def referencia(self) -> str:
        """Return the identifier operators actually use for this credential.

        Combines `username` and `fingerprint` rather than the UUID `id`,
        because that is the pair recognized in logs, CLI output and
        `authorized_keys` block markers -- a single user can hold several
        credentials, so `username` alone would not be unique.
        """
        return f"{self.username}:{self.fingerprint}"


@dataclass
class GrupoUser:
    """A named set of `User.username` values: the "who" side of a
    `Permissao` grant.

    `membros` stores raw usernames, not references to `User.id`; nothing
    here enforces that a member still exists or is `StatusUser.ATIVO`.
    Stale entries are not an error -- the planner silently skips
    membership that no longer resolves to an active user (see
    `planner.planner.Planner.estado_desejado`).
    """

    nome: str
    membros: list[str] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)


@dataclass
class Servidor:
    """A target host that AdminForge manages SSH access on.

    `chave_host` pins the SSH host key expected on the wire; the deployer
    refuses to connect if it is empty or if the key it sees does not match
    (see `exceptions.HostKeyDivergente`), so this is a trust-on-first-use
    pin rather than purely informational. `chaves_instaladas` is a cache
    of what the last successful apply left installed, written by
    `core.nucleo` and read by the planner as the baseline for the next
    delta -- it is a snapshot, not necessarily what is on the server right
    now if it changed out of band.
    """

    hostname: str
    ipv4: str
    porta_ssh: int = 22
    chave_host: str = ""
    chaves_instaladas: list = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)


@dataclass
class GrupoServidor:
    """A named set of `Servidor.hostname` values: the "where" side of a
    `Permissao` grant.

    Mirrors `GrupoUser` in shape and in leniency: a membership entry
    referencing a hostname that no longer exists is skipped by the
    planner rather than treated as an error.
    """

    nome: str
    membros: list[str] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)


@dataclass
class SudoProfile:
    """A named whitelist of shell commands that a `NivelPermissao.SUDO`
    `Permissao` can reference (via `Permissao.profile`) to restrict what
    the grant allows on the target servers.

    `comandos` is opaque to this module: entries are copied one per line,
    verbatim, into the remote sudoers file by the deployer (see
    `deployer.ssh_deployer.SSHDeployer._escrever_sudoers`), so validating
    the syntax of each command is the deployer's concern, not this
    dataclass's. A `Permissao` left without a profile falls back to
    unrestricted `NOPASSWD:ALL`, so no profile is the more permissive
    state, not a safer default.
    """

    nome: str
    comandos: list[str] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)


@dataclass
class Permissao:
    """A grant: `SHELL` or `SUDO` access from every member of
    `grupo_user` to every member of `grupo_servidor`, optionally scoped by
    a `SudoProfile`.

    Identified in the store by the `(grupo_user, grupo_servidor)` pair,
    not by `id` (see `interfaces.store.IStore.delete_permissao`): there is
    at most one grant between a given pair of groups, and granting again
    for the same pair replaces it rather than adding a second grant.
    """

    grupo_user: str
    grupo_servidor: str
    nivel: NivelPermissao
    profile: str | None = None
    id: UUID = field(default_factory=uuid4)


@dataclass
class Subacao:
    """One planned or executed change to a single server, produced by the
    planner and mutated in place by the deployer as it runs.

    `status` is a free-form string (`"pendente"`/`"sucesso"`/`"falha"`),
    not the `StatusOperacao` enum used by the parent `Operacao` -- the two
    are not interchangeable. Most fields are optional because a given
    `Subacao` only fills in the ones relevant to its `acao` (e.g.
    `chave_publica`/`credencial` for a key add, `nivel`/`profile`/
    `profile_comandos` for the sudo side-effect of a grant change).
    """

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
    """One audited unit of work: a single CLI command and everything it
    did, persisted as one entry in the auditor's log.

    `hash` and `hash_anterior` chain each entry to the one before it (see
    `auditor.jsonl_auditor.JsonlAuditor`), turning the log into an
    append-only, tamper-evident sequence: `IAuditor.verificar_cadeia`
    recomputes the chain and reports a break if any entry was edited,
    reordered or removed after the fact. `id` is a short sequential
    string (e.g. `"OP-0001"`, from `IAuditor.proximo_id`), not a UUID like
    the other entities in this module.
    """

    id: str
    momento: datetime
    superadmin: str
    comando: str
    status: StatusOperacao
    subacoes: list[Subacao] = field(default_factory=list)
    hash_anterior: str | None = None
    hash: str | None = None
