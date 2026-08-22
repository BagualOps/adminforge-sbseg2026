"""Core orchestration layer: validate input, mutate persisted state, and audit every operation.

`Core` is the single write path for all AdminForge entities (users, SSH
keys, user-groups, servers, server-groups, permissions, sudo-profiles) and
hosts the plan/apply/reconcile pipeline built on `planner.Planner`. Every
mutating method follows the same shape: allocate an `Operation`, validate and
mutate `JsonStore` state inside `with self.store:`, and register the
resulting status through `JsonlAuditor` so the audit log always reflects what
was actually persisted. `preview`/`apply` are where the paper's central
claim is implemented: without `--reconcile` they answer "is anything
pending?" purely from the locally persisted desired-vs-installed state (no
network I/O), and `apply` applies per host independently so its cost scales
linearly with fleet size; passing `reconcile=True` swaps in the real state
fetched over SSH (`_atual_vivo`) for the comparison instead.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from adminforge import ssh_keys
from adminforge.auditor.jsonl_auditor import JsonlAuditor
from adminforge.deployer.dry_run import DryRunDeployer
from adminforge.domain import (
    SshCredential,
    ServerGroup,
    UserGroup,
    PermissionLevel,
    Operation,
    Permission,
    Server,
    CredentialStatus,
    OperationStatus,
    UserStatus,
    SubAction,
    SudoProfile,
    ActionType,
    User,
)
from adminforge.exceptions import (
    InvalidState,
    InvalidFormat,
    AlreadyExists,
    NotFound,
)
from adminforge.i18n import t as _
from adminforge.interfaces.deployer import IDeployer
from adminforge.planner.planner import Planner
from adminforge.store.json_store import JsonStore

_RE_USERNAME = re.compile(r"^[a-z_][a-z0-9_-]{0,30}$")
_RE_HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")
_RE_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_RE_GROUP_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")
_RE_IPV4 = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


def _ipv4_valido(ip: str) -> bool:
    """Return whether `ip` is a syntactically valid dotted-quad IPv4 address (each octet 0-255)."""
    if not _RE_IPV4.match(ip):
        return False
    return all(0 <= int(octeto) <= 255 for octeto in ip.split("."))


def _msg_associated_permissions(tipo: str, name: str, perms: list[Permission]) -> str:
    """Error message for a blocked delete: lists the N permissions and suggests the command."""
    pares = [(p.user_group, p.server_group, p.level.value) for p in perms]
    if tipo == "user-group":
        lines = [f"  - {gs} ({lvl})" for _gu, gs, lvl in pares]
        commands = [f"  adminforge permission revoke --user-group {name} --server-group {gs}" for _gu, gs, _ in pares]
    else:
        lines = [f"  - {gu} ({lvl})" for gu, _gs, lvl in pares]
        commands = [f"  adminforge permission revoke --user-group {gu} --server-group {name}" for gu, _gs, _ in pares]
    return (
        _("{kind} {name} has {n} associated permission(s):").format(kind=_(tipo), name=name, n=len(perms))
        + "\n" + "\n".join(lines)
        + "\n" + _("Revoke them first:") + "\n"
        + "\n".join(commands)
    )


class Core:
    """Facade over `JsonStore`, `JsonlAuditor` and `Planner` that implements every AdminForge command.

    Holds the single `JsonStore` instance (state of record), the
    `JsonlAuditor` (append-only history) and a `Planner` built on the same
    store; `deployer` is the only collaborator that touches real hosts and
    defaults to `DryRunDeployer`, so constructing a `Core` never risks
    reaching the network. Callers are the CLI subcommands; each public method
    maps to one CLI verb and returns the `Operation` that was appended to the
    audit log, success or failure alike.
    """

    def __init__(
        self,
        store: JsonStore,
        auditor: JsonlAuditor,
        deployer: IDeployer | None = None,
        superadmin: str = "unknown",
    ):
        """Store the collaborators and build a `Planner` bound to the same `store`."""
        self.store = store
        self.auditor = auditor
        self.deployer = deployer or DryRunDeployer()
        self.superadmin = superadmin
        self.planner = Planner(store)

    @classmethod
    def montar(
        cls,
        state_dir: Path,
        deployer: IDeployer | None = None,
        superadmin: str = "unknown",
    ) -> "Core":
        """Build a `Core` wired to a `JsonStore`/`JsonlAuditor` pair rooted at `state_dir`.

        Convenience constructor for the CLI entry point: derives
        `history.jsonl` from `state_dir` so callers only need to know the
        state directory, not the on-disk layout of the store and the audit
        log.
        """
        store = JsonStore(state_dir)
        auditor = JsonlAuditor(state_dir / "history.jsonl")
        return cls(store, auditor, deployer, superadmin)

    def _nova_op(self, command: str) -> Operation:
        """Allocate a new `Operation` in `IN_PROGRESS` status with a fresh id and timestamp.

        Called at the top of every command before any validation or
        mutation, so a record already exists to attach a failure to even if
        the command raises before doing any work.
        """
        return Operation(
            id=self.auditor.next_id(),
            timestamp=datetime.now().astimezone(),
            superadmin=self.superadmin,
            command=command,
            status=OperationStatus.IN_PROGRESS,
        )

    def _record(self, op: Operation, status: OperationStatus) -> Operation:
        """Set `op.status` and persist it via `self.auditor.record`, then return `op`.

        Centralizes the "write the outcome to the audit log" step so every
        command method ends the same way regardless of which status it
        reached.
        """
        op.status = status
        self.auditor.record(op)
        return op

    def _record_failure(self, op: Operation, message: str) -> Operation:
        """Attach a synthetic failed `SubAction` carrying `message` to `op` and register it as `FAILURE`.

        Used by the `except Exception` handler at the end of every command
        method, so a validation error or store exception still produces a
        `SubAction` an operator can read from the audit log instead of just a
        bare failure status with no detail.
        """
        op.sub_actions.append(
            SubAction(server="", action=ActionType.READ, status="failure", error=message)
        )
        return self._record(op, OperationStatus.FAILURE)

    def cadastrar_user(self, username: str, name: str, email: str) -> Operation:
        """Validate and persist a new active user, failing if the username or email is malformed or the username is already taken.

        Runs entirely inside a `JsonStore` transaction; any raised exception
        is caught and turned into a `FAILURE` `Operation` rather than
        propagating, so the CLI never crashes on invalid input.
        """
        op = self._nova_op(f"user add {username}")
        try:
            with self.store:
                if not _RE_USERNAME.match(username):
                    raise InvalidFormat(_("invalid username: {u}").format(u=repr(username)))
                if not name.strip():
                    raise InvalidFormat(_("name is required"))
                if not _RE_EMAIL.match(email):
                    raise InvalidFormat(_("invalid email: {e}").format(e=repr(email)))
                if self.store.get_user(username):
                    raise AlreadyExists(_("username {u} already exists").format(u=repr(username)))
                self.store.save_user(User(username=username, name=name, email=email))
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def desabilitar_user(self, username: str) -> Operation:
        """Mark `username` as `INACTIVE` and revoke all of its currently active SSH credentials.

        Revoking the credentials here, rather than leaving that to the next
        `apply`, means a disabled user shows up as revoked in the store
        immediately, before any `preview`/`apply` runs against the fleet.
        """
        op = self._nova_op(f"user disable {username}")
        try:
            with self.store:
                user = self.store.get_user(username)
                if not user:
                    raise NotFound(_("user {u} does not exist").format(u=repr(username)))
                user.status = UserStatus.INACTIVE
                self.store.save_user(user)
                for cred in self.store.list_credentials(username):
                    if cred.status == CredentialStatus.ACTIVE:
                        cred.status = CredentialStatus.REVOKED
                        self.store.save_credential(cred)
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def register_key(self, username: str, raw_key: str) -> Operation:
        """Register a new SSH public key for `username`, rejecting it if its fingerprint is already on file for that user.

        Keys are stored canonicalized (`ssh_keys.canonical_key`) and
        deduplicated by fingerprint, not by raw text, so re-submitting the
        same key with different whitespace or a different comment is still
        caught as a duplicate.
        """
        op = self._nova_op(f"user key add {username}")
        try:
            with self.store:
                user = self.store.get_user(username)
                if not user:
                    raise NotFound(_("user {u} does not exist").format(u=repr(username)))
                fp = ssh_keys.fingerprint(raw_key)
                canonica = ssh_keys.canonical_key(raw_key)
                for c in self.store.list_credentials(username):
                    if c.fingerprint == fp:
                        raise AlreadyExists(_("key already registered for {u} ({fp})").format(u=repr(username), fp=fp))
                self.store.save_credential(
                    SshCredential(
                        username=username, public_key=canonica, fingerprint=fp
                    )
                )
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def revoke_key(self, fingerprint: str) -> Operation:
        """Mark the credential identified by `fingerprint` as `REVOKED`.

        Looks the credential up across all users by fingerprint alone; the
        caller does not need to know which user it belongs to.
        """
        op = self._nova_op(f"user key revoke {fingerprint}")
        try:
            with self.store:
                cred = self.store.get_credential_by_fingerprint(fingerprint)
                if not cred:
                    raise NotFound(_("fingerprint {fp} does not exist").format(fp=repr(fingerprint)))
                cred.status = CredentialStatus.REVOKED
                self.store.save_credential(cred)
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def create_user_group(self, name: str) -> Operation:
        """Validate and persist a new, empty user-group, failing if the name is malformed or already exists."""
        op = self._nova_op(f"user-group create {name}")
        try:
            with self.store:
                if not _RE_GROUP_NAME.match(name):
                    raise InvalidFormat(_("invalid group name: {n}").format(n=repr(name)))
                if self.store.get_user_group(name):
                    raise AlreadyExists(_("user-group {n} already exists").format(n=repr(name)))
                self.store.save_user_group(UserGroup(name=name))
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def add_member_user_group(self, group: str, username: str) -> Operation:
        """Add a single user to `group`; delegates to `add_members_user_group` with a one-element list."""
        return self.add_members_user_group(group, [username])

    def add_members_user_group(self, group: str, usernames: list[str]) -> Operation:
        """Add `usernames` to `group`, failing if the group or any of the users does not exist.

        Idempotent: reports success without changing anything if every
        requested member is already in the group. Membership is stored
        sorted, so re-running with an overlapping set never changes the
        persisted member order.
        """
        op = self._nova_op(f"user-group add-member {group} {' '.join(usernames)}")
        try:
            with self.store:
                g = self.store.get_user_group(group)
                if not g:
                    raise NotFound(_("group {g} does not exist").format(g=repr(group)))
                inexistentes = [u for u in usernames if not self.store.get_user(u)]
                if inexistentes:
                    raise NotFound(_("unknown users: {u}").format(u=", ".join(inexistentes)))
                members = set(g.members)
                members.update(usernames)
                if members == set(g.members):
                    return self._record(op, OperationStatus.SUCCESS)
                g.members = sorted(members)
                self.store.save_user_group(g)
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def remove_member_user_group(self, group: str, username: str) -> Operation:
        """Remove a single user from `group`; delegates to `remove_members_user_group` with a one-element list."""
        return self.remove_members_user_group(group, [username])

    def remove_members_user_group(self, group: str, usernames: list[str]) -> Operation:
        """Remove `usernames` from `group`, failing only if the group itself does not exist.

        Silently ignores names not currently in the group (removal is
        idempotent) and, unlike the add path, does not check that the names
        are known users: membership can only reference users that already
        existed when added, and a name may have since been deleted from the
        store.
        """
        op = self._nova_op(f"user-group remove-member {group} {' '.join(usernames)}")
        try:
            with self.store:
                g = self.store.get_user_group(group)
                if not g:
                    raise NotFound(_("group {g} does not exist").format(g=repr(group)))
                alvo = set(usernames)
                novos = [m for m in g.members if m not in alvo]
                if novos == g.members:
                    return self._record(op, OperationStatus.SUCCESS)
                g.members = novos
                self.store.save_user_group(g)
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def delete_user_group(self, name: str) -> Operation:
        """Delete `name`, failing if it does not exist or still has permissions granted to it.

        The permission check exists so deleting a group can never silently
        orphan a `Permission` that references it; the error message lists
        every blocking permission and the `revoke` command needed to clear
        it (`_msg_associated_permissions`).
        """
        op = self._nova_op(f"user-group delete {name}")
        try:
            with self.store:
                if not self.store.get_user_group(name):
                    raise NotFound(f"group '{name}' does not exist")
                associadas = [p for p in self.store.list_permissions() if p.user_group == name]
                if associadas:
                    raise InvalidState(_msg_associated_permissions("user-group", name, associadas))
                self.store.delete_user_group(name)
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def register_server(
        self,
        hostname: str,
        ipv4: str,
        porta: int,
        host_key: str,
    ) -> Operation:
        """Validate and persist a new server, failing if the hostname/IPv4/port/host key is malformed or the hostname is already registered."""
        op = self._nova_op(f"server add {hostname}")
        try:
            with self.store:
                if not _RE_HOSTNAME.match(hostname):
                    raise InvalidFormat(_("invalid hostname: {h}").format(h=repr(hostname)))
                if not _ipv4_valido(ipv4):
                    raise InvalidFormat(_("invalid ipv4: {ip}").format(ip=repr(ipv4)))
                if not (1 <= porta <= 65535):
                    raise InvalidFormat(_("invalid port: {p}").format(p=porta))
                if not host_key.strip():
                    raise InvalidFormat(_("host_key is required"))
                if self.store.get_server(hostname):
                    raise AlreadyExists(_("server {h} already exists").format(h=repr(hostname)))
                self.store.save_server(
                    Server(
                        hostname=hostname,
                        ipv4=ipv4,
                        ssh_port=porta,
                        host_key=host_key.strip(),
                    )
                )
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def delete_server(self, hostname: str) -> Operation:
        """Delete `hostname` and remove it from every server-group that lists it as a member.

        Unlike `delete_user_group`/`delete_server_group`, this does not
        block on associated permissions: permissions reference server-groups,
        not individual servers, so removing a server just shrinks the groups
        it belonged to instead of leaving a dangling reference.
        """
        op = self._nova_op(f"server remove {hostname}")
        try:
            with self.store:
                if not self.store.get_server(hostname):
                    raise NotFound(_("server {h} does not exist").format(h=repr(hostname)))
                for g in self.store.list_server_groups():
                    if hostname in g.members:
                        g.members = [m for m in g.members if m != hostname]
                        self.store.save_server_group(g)
                self.store.delete_server(hostname)
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def create_server_group(self, name: str) -> Operation:
        """Validate and persist a new, empty server-group, failing if the name is malformed or already exists."""
        op = self._nova_op(f"server-group create {name}")
        try:
            with self.store:
                if not _RE_GROUP_NAME.match(name):
                    raise InvalidFormat(_("invalid group name: {n}").format(n=repr(name)))
                if self.store.get_server_group(name):
                    raise AlreadyExists(_("server-group {n} already exists").format(n=repr(name)))
                self.store.save_server_group(ServerGroup(name=name))
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def add_member_server_group(self, group: str, hostname: str) -> Operation:
        """Add a single server to `group`; delegates to `add_members_server_group` with a one-element list."""
        return self.add_members_server_group(group, [hostname])

    def add_members_server_group(self, group: str, hostnames: list[str]) -> Operation:
        """Add `hostnames` to `group`, failing if the group or any of the servers does not exist.

        Idempotent no-op if every hostname is already a member; membership is
        stored sorted, mirroring `add_members_user_group`.
        """
        op = self._nova_op(f"server-group add-member {group} {' '.join(hostnames)}")
        try:
            with self.store:
                g = self.store.get_server_group(group)
                if not g:
                    raise NotFound(_("group {g} does not exist").format(g=repr(group)))
                inexistentes = [h for h in hostnames if not self.store.get_server(h)]
                if inexistentes:
                    raise NotFound(_("unknown servers: {s}").format(s=", ".join(inexistentes)))
                members = set(g.members)
                members.update(hostnames)
                if members == set(g.members):
                    return self._record(op, OperationStatus.SUCCESS)
                g.members = sorted(members)
                self.store.save_server_group(g)
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def remove_member_server_group(self, group: str, hostname: str) -> Operation:
        """Remove a single server from `group`; delegates to `remove_members_server_group` with a one-element list."""
        return self.remove_members_server_group(group, [hostname])

    def remove_members_server_group(self, group: str, hostnames: list[str]) -> Operation:
        """Remove `hostnames` from `group`, failing only if the group itself does not exist; mirrors `remove_members_user_group`."""
        op = self._nova_op(f"server-group remove-member {group} {' '.join(hostnames)}")
        try:
            with self.store:
                g = self.store.get_server_group(group)
                if not g:
                    raise NotFound(_("group {g} does not exist").format(g=repr(group)))
                alvo = set(hostnames)
                novos = [m for m in g.members if m not in alvo]
                if novos == g.members:
                    return self._record(op, OperationStatus.SUCCESS)
                g.members = novos
                self.store.save_server_group(g)
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def delete_server_group(self, name: str) -> Operation:
        """Delete `name`, failing if it does not exist or still has permissions granted to it; mirrors `delete_user_group`."""
        op = self._nova_op(f"server-group delete {name}")
        try:
            with self.store:
                if not self.store.get_server_group(name):
                    raise NotFound(f"group '{name}' does not exist")
                associadas = [p for p in self.store.list_permissions() if p.server_group == name]
                if associadas:
                    raise InvalidState(_msg_associated_permissions("server-group", name, associadas))
                self.store.delete_server_group(name)
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def grant(
        self,
        user_group: str,
        server_group: str,
        level: PermissionLevel,
        profile: str | None = None,
    ) -> Operation:
        """Grant `level` access from `user_group` to `server_group`, optionally scoped to a sudo `profile`.

        Validates that both groups exist, that `profile` is only supplied
        when `level` is `SUDO`, and that a supplied profile actually exists
        in the store. Overwrites any existing permission for the same
        (user-group, server-group) pair rather than failing, since a
        permission is keyed on that pair and re-granting is how it is
        updated.
        """
        command = f"permission grant {user_group} {server_group} --level {level.value}"
        if profile:
            command += f" --profile {profile}"
        op = self._nova_op(command)
        try:
            with self.store:
                if not self.store.get_user_group(user_group):
                    raise NotFound(_("user-group {g} does not exist").format(g=repr(user_group)))
                if not self.store.get_server_group(server_group):
                    raise NotFound(_("server-group {g} does not exist").format(g=repr(server_group)))
                if profile is not None:
                    if level != PermissionLevel.SUDO:
                        raise InvalidFormat(_("--profile only applies when --level is sudo"))
                    if not self.store.get_sudo_profile(profile):
                        raise NotFound(_("sudo-profile {n} does not exist").format(n=repr(profile)))
                self.store.save_permission(
                    Permission(
                        user_group=user_group,
                        server_group=server_group,
                        level=level,
                        profile=profile,
                    )
                )
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def create_sudo_profile(self, name: str, commands: list[str]) -> Operation:
        """Validate and persist a new sudo command profile, failing on a malformed name, an empty command list, or a non-absolute or control-character-bearing command.

        The control-character check exists specifically to stop sudoers rule
        injection: `visudo -c` validates syntax but does not distinguish one
        sudoers line from two, so a command smuggling in an embedded
        `\\n`/`\\r`/NUL could otherwise add a second, attacker-controlled
        rule while still passing validation.
        """
        op = self._nova_op(f"sudo-profile create {name}")
        try:
            with self.store:
                if not _RE_GROUP_NAME.match(name):
                    raise InvalidFormat(_("invalid sudo-profile name: {n}").format(n=repr(name)))
                if not commands:
                    raise InvalidFormat(_("at least one --command is required"))
                for c in commands:
                    if not c.startswith("/"):
                        raise InvalidFormat(_("command must be absolute path: {c} (sudoers requires absolute paths)").format(c=repr(c)))
                    # Blocks injection of new sudoers rules via newline/CR.
                    # 'visudo -c' validates syntax but does not tell 1 rule with \n apart from 2
                    # legitimate rules; as long as one of the lines is valid, it passes.
                    if any(ch in c for ch in ("\n", "\r", "\x00")):
                        raise InvalidFormat(_("command contains forbidden control character: {c}").format(c=repr(c)))
                if self.store.get_sudo_profile(name):
                    raise AlreadyExists(_("sudo-profile {n} already exists").format(n=repr(name)))
                self.store.save_sudo_profile(SudoProfile(name=name, commands=list(commands)))
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def delete_sudo_profile(self, name: str) -> Operation:
        """Delete `name`, failing if it does not exist or is still referenced by a permission.

        Mirrors the group-deletion guards: a profile in use is never deleted
        by silently nulling out the permissions that reference it, since that
        would promote them to unrestricted sudo instead of failing loudly.
        """
        op = self._nova_op(f"sudo-profile delete {name}")
        try:
            with self.store:
                if not self.store.get_sudo_profile(name):
                    raise NotFound(f"sudo-profile '{name}' does not exist")
                em_uso = [
                    p for p in self.store.list_permissions() if p.profile == name
                ]
                if em_uso:
                    raise InvalidState(_("sudo-profile {n} is in use by {k} permission(s); update or revoke them first").format(n=repr(name), k=len(em_uso)))
                self.store.delete_sudo_profile(name)
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def revoke(self, user_group: str, server_group: str) -> Operation:
        """Delete the permission for the (`user_group`, `server_group`) pair, failing with a friendly error if it does not exist.

        Catches `FileNotFoundError` specifically (raised by the store when
        the pair has no permission) and reports it as a normal `Operation`
        failure rather than letting it propagate as an unrelated I/O error.
        """
        op = self._nova_op(f"permission revoke {user_group} {server_group}")
        try:
            with self.store:
                self.store.delete_permission(user_group, server_group)
                return self._record(op, OperationStatus.SUCCESS)
        except FileNotFoundError:
            return self._record_failure(op, _("permission does not exist"))
        except Exception as e:
            return self._record_failure(op, str(e))

    def preview(self, force: bool = False, reconcile: bool = False) -> list[SubAction]:
        """Compute the pending `SubAction` list without applying it -- the "is anything pending?" check the paper measures.

        With `reconcile=True`, compares desired state against the real state
        fetched live over SSH (`_atual_vivo`); otherwise the comparison is
        entirely against the state already persisted in `JsonStore`
        (`installed_keys`, last written by `apply`), so no host is
        contacted and the check stays fast regardless of fleet size. `force`
        is passed through to `Planner.calculate_delta` to treat every desired
        credential as if nothing were installed.
        """
        if reconcile:
            return self.planner.calculate_delta(atual_override=self._atual_vivo())
        return self.planner.calculate_delta(force=force)

    def _atual_vivo(self) -> dict[str, dict]:
        """Real per-server state ({host: {ref: InstalledKey}}) fetched over SSH, for the
        planner to use as the current state under --reconcile."""
        from adminforge import authorized_keys as ak
        from adminforge.planner.planner import InstalledKey

        prefixo = "adminforge-"
        desejado = self.planner.desired_state()
        out: dict[str, dict[str, InstalledKey]] = {}
        for server in self.store.list_servers():
            alvo = desejado.get(server.hostname, {})
            if not alvo:
                continue
            rel = self.deployer.inspect(server)
            ok_rel = isinstance(rel, dict) and "error" not in rel
            real_users = {u["name"] for u in rel.get("users", [])} if ok_rel else set()
            sudo_users = {a["name"][len(prefixo):] for a in rel.get("sudoers_arquivos", [])
                          if a.get("adminforge") and a.get("name", "").startswith(prefixo)}
            atual: dict[str, InstalledKey] = {}
            for username in sorted({ci.username for ci in alvo.values()}):
                if username not in real_users:
                    continue
                conteudo, ok = self.deployer.read_authorized_keys(server, username)
                if not ok:
                    continue
                level = PermissionLevel.SUDO if username in sudo_users else PermissionLevel.SHELL
                for ref in ak.parse_blocks(conteudo):
                    atual[ref] = InstalledKey(ref=ref, username=username, level=level)
            out[server.hostname] = atual
        return out

    def apply(
        self,
        jobs: int = 1,
        force: bool = False,
        reconcile: bool = False,
        sub_actions: list[SubAction] | None = None,
    ) -> Operation:
        """Compute (or accept) the pending subactions and apply them to each host, updating the persisted installed-keys state.

        Computes the delta the same way `preview` does unless `sub_actions` is
        supplied by the caller, so a previously computed preview can be
        re-applied without recomputing it. Deployment is grouped per host
        and, when `jobs > 1` and more than one host has work, fanned out over
        a bounded `ThreadPoolExecutor` -- this is the step whose cost the
        paper claims is linear per host, since each host's SSH round-trip is
        independent, and the `Store` update that follows stays serial and
        deterministic regardless of `jobs`, so the persisted result is
        identical whether hosts were applied in parallel or not. A host
        removed from the store between planning and apply is reported as a
        failed subaction rather than raising, so a partially stale plan
        degrades to `PARTIAL_SUCCESS` instead of aborting the whole run.
        """
        op = self._nova_op("apply")
        try:
            with self.store:
                if sub_actions is None:
                    if reconcile:
                        sub_actions = self.planner.calculate_delta(atual_override=self._atual_vivo())
                    else:
                        sub_actions = self.planner.calculate_delta(force=force)
                if not sub_actions:
                    return self._record(op, OperationStatus.SUCCESS)

                by_server: dict[str, list[SubAction]] = {}
                for s in sub_actions:
                    by_server.setdefault(s.server, []).append(s)

                from adminforge.planner.planner import InstalledKey

                # Resolve each host's target state once, in a deterministic order.
                hostnames = list(by_server)
                servers = {h: self.store.get_server(h) for h in hostnames}

                # The SSH work (deployer.apply) is independent per host and is
                # the wall-clock cost; run it with a bounded thread pool when
                # jobs > 1. The Store update below stays serial and ordered, so
                # the result is identical regardless of jobs. ThreadPoolExecutor
                # is part of the standard library, preserving the zero-dependency
                # runtime.
                pending = {h: lote for h, lote in by_server.items() if servers[h] is not None}
                if jobs > 1 and len(pending) > 1:
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor(max_workers=min(jobs, len(pending))) as pool:
                        resultados = dict(zip(
                            pending,
                            pool.map(lambda h: self.deployer.apply(servers[h], pending[h]), pending),
                        ))
                else:
                    resultados = {h: self.deployer.apply(servers[h], lote) for h, lote in pending.items()}

                for hostname, lote in by_server.items():
                    server = servers[hostname]
                    if server is None:
                        for s in lote:
                            s.status = "failure"
                            s.error = _("server {h} does not exist").format(h=repr(hostname))
                        op.sub_actions.extend(lote)
                        continue

                    aplicadas = resultados[hostname]
                    op.sub_actions.extend(aplicadas)

                    installed = {
                        ci.ref: ci
                        for ci in (
                            InstalledKey.de_dict(item) if isinstance(item, dict)
                            else InstalledKey(
                                ref=item,
                                username=item.split(":", 1)[0],
                                level=PermissionLevel.SHELL,
                            )
                            for item in server.installed_keys
                        )
                    }
                    for s in aplicadas:
                        if s.status != "success" or s.credential is None:
                            continue
                        if s.action == ActionType.ADD_KEY:
                            installed[s.credential] = InstalledKey(
                                ref=s.credential,
                                username=s.username or "",
                                level=s.level or PermissionLevel.SHELL,
                                profile=s.profile,
                            )
                        elif s.action == ActionType.REMOVE_KEY:
                            installed.pop(s.credential, None)
                    server.installed_keys = [c.para_dict() for c in installed.values()]
                    self.store.save_server(server)

                successes = sum(1 for s in op.sub_actions if s.status == "success")
                total = len(op.sub_actions)
                if successes == total:
                    status = OperationStatus.SUCCESS
                elif successes == 0:
                    status = OperationStatus.FAILURE
                else:
                    status = OperationStatus.PARTIAL_SUCCESS
                return self._record(op, status)
        except Exception as e:
            return self._record_failure(op, str(e))

    # ---------------------------------------------------------------------------
    # Edits / renames
    # ---------------------------------------------------------------------------
    def editar_user(self, username: str, name: str | None = None, email: str | None = None) -> Operation:
        """Update `name` and/or `email` on an existing user, validating whichever fields are supplied; fields left as `None` are unchanged."""
        op = self._nova_op(f"user edit {username}")
        try:
            with self.store:
                user = self.store.get_user(username)
                if not user:
                    raise NotFound(_("user {u} does not exist").format(u=repr(username)))
                if name is not None:
                    if not name.strip():
                        raise InvalidFormat(_("name is required"))
                    user.name = name
                if email is not None:
                    if not _RE_EMAIL.match(email):
                        raise InvalidFormat(_("invalid email: {e}").format(e=repr(email)))
                    user.email = email
                self.store.save_user(user)
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def rename_user(self, de: str, para: str) -> Operation:
        """Rename a user from `de` to `para` and update their membership in every user-group.

        No-op success if `de == para`. Fails if `para` is invalid or already
        taken, or if `de` does not exist.
        """
        op = self._nova_op(f"user rename {de} -> {para}")
        try:
            with self.store:
                if de == para:
                    return self._record(op, OperationStatus.SUCCESS)
                if not _RE_USERNAME.match(para):
                    raise InvalidFormat(_("invalid username: {u}").format(u=repr(para)))
                if not self.store.get_user(de):
                    raise NotFound(_("user {u} does not exist").format(u=repr(de)))
                if self.store.get_user(para):
                    raise AlreadyExists(_("username {u} already exists").format(u=repr(para)))
                self.store.rename_user(de, para)
                for g in self.store.list_user_groups():
                    if de in g.members:
                        g.members = [para if m == de else m for m in g.members]
                        self.store.save_user_group(g)
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def edit_server(
        self,
        hostname: str,
        ipv4: str | None = None,
        porta: int | None = None,
        host_key: str | None = None,
    ) -> Operation:
        """Update `ipv4`, `porta` and/or `host_key` on an existing server, validating whichever fields are supplied; fields left as `None` are unchanged."""
        op = self._nova_op(f"server edit {hostname}")
        try:
            with self.store:
                server = self.store.get_server(hostname)
                if not server:
                    raise NotFound(_("server {h} does not exist").format(h=repr(hostname)))
                if ipv4 is not None:
                    if not _ipv4_valido(ipv4):
                        raise InvalidFormat(_("invalid ipv4: {ip}").format(ip=repr(ipv4)))
                    server.ipv4 = ipv4
                if porta is not None:
                    if not (1 <= porta <= 65535):
                        raise InvalidFormat(_("invalid port: {p}").format(p=porta))
                    server.ssh_port = porta
                if host_key is not None:
                    if not host_key.strip():
                        raise InvalidFormat(_("host_key is required"))
                    server.host_key = host_key.strip()
                self.store.save_server(server)
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def rename_server(self, de: str, para: str) -> Operation:
        """Rename a server from `de` to `para` and update its membership in every server-group; mirrors `rename_user`."""
        op = self._nova_op(f"server rename {de} -> {para}")
        try:
            with self.store:
                if de == para:
                    return self._record(op, OperationStatus.SUCCESS)
                if not _RE_HOSTNAME.match(para):
                    raise InvalidFormat(_("invalid hostname: {h}").format(h=repr(para)))
                if not self.store.get_server(de):
                    raise NotFound(_("server {h} does not exist").format(h=repr(de)))
                if self.store.get_server(para):
                    raise AlreadyExists(_("server {h} already exists").format(h=repr(para)))
                self.store.rename_server(de, para)
                for g in self.store.list_server_groups():
                    if de in g.members:
                        g.members = [para if m == de else m for m in g.members]
                        self.store.save_server_group(g)
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def _rename_group(
        self,
        tipo: str,
        de: str,
        para: str,
        get,
        rename,
        update_permission,
    ) -> Operation:
        """Shared rename implementation for user-groups and server-groups: validate, rename via `rename`, and repoint every `Permission` that referenced the old name.

        `get`/`rename` are the store accessors for the specific group kind
        being renamed; `update_permission` is a callback that mutates a
        `Permission` in place if it references `de`, so the same generic pass
        over `self.store.list_permissions()` works for both user-groups
        (matching `user_group`) and server-groups (matching
        `server_group`). `tipo` is used only for the command string and
        error messages.
        """
        op = self._nova_op(f"{tipo} rename {de} -> {para}")
        try:
            with self.store:
                if de == para:
                    return self._record(op, OperationStatus.SUCCESS)
                if not _RE_GROUP_NAME.match(para):
                    raise InvalidFormat(_("invalid group name: {n}").format(n=repr(para)))
                if not get(de):
                    raise NotFound(_("{kind} {n} does not exist").format(kind=tipo, n=repr(de)))
                if get(para):
                    raise AlreadyExists(_("{kind} {n} already exists").format(kind=tipo, n=repr(para)))
                rename(de, para)
                perms = self.store.list_permissions()
                for p in perms:
                    update_permission(p, de, para)
                self.store.replace_permissions(perms)
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def rename_user_group(self, de: str, para: str) -> Operation:
        """Rename a user-group from `de` to `para`, repointing permissions via `_rename_group`."""
        def _swap(p, antigo, novo):
            """Repoint `p.user_group` to `novo` in place if it currently references `antigo`."""
            if p.user_group == antigo:
                p.user_group = novo
        return self._rename_group(
            "user-group", de, para,
            self.store.get_user_group, self.store.rename_user_group, _swap,
        )

    def rename_server_group(self, de: str, para: str) -> Operation:
        """Rename a server-group from `de` to `para`, repointing permissions via `_rename_group`."""
        def _swap(p, antigo, novo):
            """Repoint `p.server_group` to `novo` in place if it currently references `antigo`."""
            if p.server_group == antigo:
                p.server_group = novo
        return self._rename_group(
            "server-group", de, para,
            self.store.get_server_group, self.store.rename_server_group, _swap,
        )

    def rename_sudo_profile(self, de: str, para: str) -> Operation:
        """Rename a sudo-profile from `de` to `para` and repoint every `Permission.profile` that referenced the old name.

        Does not reuse `_rename_group` because a sudo-profile is not a
        group with membership.
        """
        op = self._nova_op(f"sudo-profile rename {de} -> {para}")
        try:
            with self.store:
                if de == para:
                    return self._record(op, OperationStatus.SUCCESS)
                if not _RE_GROUP_NAME.match(para):
                    raise InvalidFormat(_("invalid sudo-profile name: {n}").format(n=repr(para)))
                if not self.store.get_sudo_profile(de):
                    raise NotFound(_("sudo-profile {n} does not exist").format(n=repr(de)))
                if self.store.get_sudo_profile(para):
                    raise AlreadyExists(_("sudo-profile {n} already exists").format(n=repr(para)))
                self.store.rename_sudo_profile(de, para)
                perms = self.store.list_permissions()
                for p in perms:
                    if p.profile == de:
                        p.profile = para
                self.store.replace_permissions(perms)
                return self._record(op, OperationStatus.SUCCESS)
        except Exception as e:
            return self._record_failure(op, str(e))

    def audit_server(self, hostname: str) -> tuple[Operation, dict]:
        """Inspect `hostname` live over SSH and return both the resulting `Operation` and the raw report from `deployer.inspect`.

        Unlike the other command methods, this does not open a `JsonStore`
        transaction (`with self.store:`): it only reads the store via
        `get_server` and never persists anything, so no transaction is
        needed. On failure it also returns the exception as a dict with an
        `"error"` key, not just the failed `Operation`, since the caller needs
        a report shape even when inspection could not run.
        """
        op = self._nova_op(f"audit server {hostname}")
        try:
            server = self.store.get_server(hostname)
            if not server:
                raise NotFound(_("server {h} does not exist").format(h=repr(hostname)))
            report = self.deployer.inspect(server)
            sub = SubAction(
                server=hostname,
                action=ActionType.READ,
                status="success" if "error" not in report else "failure",
                error=report.get("error"),
                message=_("{u} users, {g} groups, {s} services, {r} sudo rules").format(u=len(report.get("users", [])), g=len(report.get("groups", [])), s=len(report.get("servicos", [])), r=len(report.get("sudoers_regras", []))),
            )
            op.sub_actions.append(sub)
            status = OperationStatus.SUCCESS if "error" not in report else OperationStatus.FAILURE
            self._record(op, status)
            return op, report
        except Exception as e:
            return self._record_failure(op, str(e)), {"error": str(e)}
