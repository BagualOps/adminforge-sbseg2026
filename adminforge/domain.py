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


class UserStatus(str, Enum):
    """Lifecycle state of a `User`.

    Only `ACTIVE` users are picked up by the planner for key deployment
    (see `planner.planner.Planner.desired_state`); `INACTIVE` and
    `BLOCKED` are both non-active but kept as separate values so audits
    can distinguish a routine pause from a block for cause. Inherits from
    `str` so it serializes to its literal value in JSON/store files.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"


class CredentialStatus(str, Enum):
    """Lifecycle state of a `SshCredential`.

    Revoking a key does not delete its record: the credential is kept and
    flipped to `REVOKED` so the audit trail can tell "never granted" apart
    from "granted, then removed". Only `ACTIVE` credentials are considered
    for deployment.
    """

    ACTIVE = "active"
    REVOKED = "revoked"


class PermissionLevel(str, Enum):
    """Access level a `Permission` grants: `SHELL` for plain SSH/file
    access, `SUDO` for root via sudo.

    `SUDO` alone, with no `SudoProfile` referenced from `Permission.profile`,
    means unrestricted `NOPASSWD:ALL`; a profile narrows it to a whitelist
    of commands. See `planner.planner._merge_profile` for how level and
    profile are combined when a user holds more than one grant to the same
    server.
    """

    SHELL = "shell"
    SUDO = "sudo"


class OperationStatus(str, Enum):
    """Outcome of an `Operation` once the deployer has run it.

    `PARTIAL_SUCCESS` exists because one operation can touch several
    servers/sub_actions independently: if some succeed and others fail, the
    operation is neither a clean `SUCCESS` nor a full `FAILURE`, and callers
    (CLI, auditor) need that distinction to decide whether a retry or a
    manual fix-up is required.
    """

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL_SUCCESS = "partial_success"
    IN_PROGRESS = "in_progress"
    ABORTED = "aborted"


class ActionType(str, Enum):
    """Kind of change a `SubAction` performs against a server's
    `authorized_keys` file: add a key, remove a key, or a read-only
    inspection (`READ`) that writes nothing.
    """

    ADD_KEY = "add_key"
    REMOVE_KEY = "remove_key"
    READ = "read"


@dataclass
class User:
    """A managed operator account: the identity that SSH credentials and
    group membership (and, transitively, access grants) attach to.

    The store keys records by `username`, not by `id`; `id` is a UUID
    surrogate that is persisted alongside the record but is not used for
    lookups anywhere in this codebase (see `interfaces.store.IStore`).
    """

    username: str
    name: str
    email: str
    status: UserStatus = UserStatus.ACTIVE
    id: UUID = field(default_factory=uuid4)


@dataclass
class SshCredential:
    """An SSH public key registered for a `User`, plus its lifecycle status.

    Looked up by `fingerprint`, not by `id` (see
    `interfaces.store.IStore.get_credential_by_fingerprint`): fingerprint
    is what a user cannot register twice and what operators recognize on
    the wire. `public_key` is expected to already be in canonical form
    (see `ssh_keys.canonical_key`); this class does not normalize it.
    """

    username: str
    public_key: str
    fingerprint: str
    status: CredentialStatus = CredentialStatus.ACTIVE
    id: UUID = field(default_factory=uuid4)

    @property
    def reference(self) -> str:
        """Return the identifier operators actually use for this credential.

        Combines `username` and `fingerprint` rather than the UUID `id`,
        because that is the pair recognized in logs, CLI output and
        `authorized_keys` block markers -- a single user can hold several
        credentials, so `username` alone would not be unique.
        """
        return f"{self.username}:{self.fingerprint}"


@dataclass
class UserGroup:
    """A named set of `User.username` values: the "who" side of a
    `Permission` grant.

    `members` stores raw usernames, not references to `User.id`; nothing
    here enforces that a member still exists or is `UserStatus.ACTIVE`.
    Stale entries are not an error -- the planner silently skips
    membership that no longer resolves to an active user (see
    `planner.planner.Planner.desired_state`).
    """

    name: str
    members: list[str] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)


@dataclass
class Server:
    """A target host that AdminForge manages SSH access on.

    `host_key` pins the SSH host key expected on the wire; the deployer
    refuses to connect if it is empty or if the key it sees does not match
    (see `exceptions.HostKeyMismatch`), so this is a trust-on-first-use
    pin rather than purely informational. `installed_keys` is a cache
    of what the last successful apply left installed, written by
    `core.core` and read by the planner as the baseline for the next
    delta -- it is a snapshot, not necessarily what is on the server right
    now if it changed out of band.
    """

    hostname: str
    ipv4: str
    ssh_port: int = 22
    host_key: str = ""
    installed_keys: list = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)


@dataclass
class ServerGroup:
    """A named set of `Server.hostname` values: the "where" side of a
    `Permission` grant.

    Mirrors `UserGroup` in shape and in leniency: a membership entry
    referencing a hostname that no longer exists is skipped by the
    planner rather than treated as an error.
    """

    name: str
    members: list[str] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)


@dataclass
class SudoProfile:
    """A named whitelist of shell commands that a `PermissionLevel.SUDO`
    `Permission` can reference (via `Permission.profile`) to restrict what
    the grant allows on the target servers.

    `commands` is opaque to this module: entries are copied one per line,
    verbatim, into the remote sudoers file by the deployer (see
    `deployer.ssh_deployer.SSHDeployer._write_sudoers`), so validating
    the syntax of each command is the deployer's concern, not this
    dataclass's. A `Permission` left without a profile falls back to
    unrestricted `NOPASSWD:ALL`, so no profile is the more permissive
    state, not a safer default.
    """

    name: str
    commands: list[str] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)


@dataclass
class Permission:
    """A grant: `SHELL` or `SUDO` access from every member of
    `user_group` to every member of `server_group`, optionally scoped by
    a `SudoProfile`.

    Identified in the store by the `(user_group, server_group)` pair,
    not by `id` (see `interfaces.store.IStore.delete_permission`): there is
    at most one grant between a given pair of groups, and granting again
    for the same pair replaces it rather than adding a second grant.
    """

    user_group: str
    server_group: str
    level: PermissionLevel
    profile: str | None = None
    id: UUID = field(default_factory=uuid4)


@dataclass
class SubAction:
    """One planned or executed change to a single server, produced by the
    planner and mutated in place by the deployer as it runs.

    `status` is a free-form string (`"pending"`/`"success"`/`"failure"`),
    not the `OperationStatus` enum used by the parent `Operation` -- the two
    are not interchangeable. Most fields are optional because a given
    `SubAction` only fills in the ones relevant to its `action` (e.g.
    `public_key`/`credential` for a key add, `level`/`profile`/
    `profile_commands` for the sudo side-effect of a grant change).
    """

    server: str
    action: ActionType
    credential: str | None = None
    public_key: str | None = None
    username: str | None = None
    level: PermissionLevel | None = None
    profile: str | None = None
    profile_commands: list[str] | None = None
    status: str = "pending"
    error: str | None = None
    message: str | None = None


@dataclass
class Operation:
    """One audited unit of work: a single CLI command and everything it
    did, persisted as one entry in the auditor's log.

    `hash` and `previous_hash` chain each entry to the one before it (see
    `auditor.jsonl_auditor.JsonlAuditor`), turning the log into an
    append-only, tamper-evident sequence: `IAuditor.verify_chain`
    recomputes the chain and reports a break if any entry was edited,
    reordered or removed after the fact. `id` is a short sequential
    string (e.g. `"OP-0001"`, from `IAuditor.next_id`), not a UUID like
    the other entities in this module.
    """

    id: str
    timestamp: datetime
    superadmin: str
    command: str
    status: OperationStatus
    sub_actions: list[SubAction] = field(default_factory=list)
    previous_hash: str | None = None
    hash: str | None = None
