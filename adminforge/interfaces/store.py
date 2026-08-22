"""Port for persisting every domain entity except `Operation` (that goes
through `interfaces.auditor.IAuditor` instead). `core.core` depends
only on this interface; `store.json_store.JsonStore` is the one
implementation shipped with AdminForge.
"""

from abc import ABC, abstractmethod

from adminforge.domain import (
    SshCredential,
    ServerGroup,
    UserGroup,
    Permission,
    Server,
    SudoProfile,
    User,
)


class IStore(ABC):
    """CRUD access to users, credentials, servers, groups, permissions and
    sudo profiles, plus the process-level lock that serializes writers.

    Entities here are addressed by their natural key (`username`,
    `hostname`, group/profile `name`, credential `fingerprint`, or the
    `(user_group, server_group)` pair for a `Permission`) rather than by
    the `id` field each dataclass also carries; `core.core` never looks
    anything up by `id` through this interface. Every `save_*` method is
    an upsert: it creates the record if the key is new and overwrites it
    in place if not, there is no separate create/update pair.
    """

    @abstractmethod
    def get_user(self, username: str) -> User | None:
        """Return the user with this `username`, or `None` if there is none."""
        ...

    @abstractmethod
    def list_users(self) -> list[User]:
        """Return every user. Order is not part of the contract; callers
        that need a stable order should sort themselves."""
        ...

    @abstractmethod
    def save_user(self, user: User) -> None:
        """Create or overwrite the user identified by `user.username`."""
        ...

    @abstractmethod
    def get_server(self, hostname: str) -> Server | None:
        """Return the server with this `hostname`, or `None` if there is none."""
        ...

    @abstractmethod
    def list_servers(self) -> list[Server]:
        """Return every server."""
        ...

    @abstractmethod
    def save_server(self, server: Server) -> None:
        """Create or overwrite the server identified by `server.hostname`."""
        ...

    @abstractmethod
    def delete_server(self, hostname: str) -> None:
        """Remove the server identified by `hostname`.

        `core.core` always checks `get_server` first and raises
        `exceptions.NotFound` itself before calling this, so
        implementations are free to treat a missing hostname as a no-op
        rather than an error (that is what `JsonStore` does).
        """
        ...

    @abstractmethod
    def list_credentials(self, username: str) -> list[SshCredential]:
        """Return every credential belonging to `username`, active and
        revoked alike -- callers that only want usable ones must filter
        on `domain.CredentialStatus.ACTIVE` themselves (see
        `planner.planner.Planner.desired_state`). Returns an empty list,
        not an error, if `username` does not exist.
        """
        ...

    @abstractmethod
    def save_credential(self, cred: SshCredential) -> None:
        """Create or overwrite `cred`, keyed by `cred.id` (not
        `fingerprint`) within its owning user's credentials.

        There is no `delete_credencial`: revocation is expressed by
        saving the same credential back with
        `status=CredentialStatus.REVOKED` rather than by removing it.
        """
        ...

    @abstractmethod
    def get_credential_by_fingerprint(self, fingerprint: str) -> SshCredential | None:
        """Return a credential with this `fingerprint`, searched across
        all users, or `None` if none matches.

        `core.core.register_key` only rejects a duplicate fingerprint
        within the *same* user, not store-wide, so two different users can
        end up with credentials that share a fingerprint; this method does
        not guarantee which one it returns in that case, only that it
        returns one of them.
        """
        ...

    @abstractmethod
    def get_user_group(self, name: str) -> UserGroup | None:
        """Return the user group named `name`, or `None` if there is none."""
        ...

    @abstractmethod
    def list_user_groups(self) -> list[UserGroup]:
        """Return every user group."""
        ...

    @abstractmethod
    def save_user_group(self, group: UserGroup) -> None:
        """Create or overwrite the user group identified by `group.name`."""
        ...

    @abstractmethod
    def delete_user_group(self, name: str) -> None:
        """Remove the user group named `name`.

        As with `delete_server`, `core.core` pre-validates existence
        (and that no `Permission` still references the group) before
        calling this, so a missing name need not be treated as an error.
        """
        ...

    @abstractmethod
    def get_server_group(self, name: str) -> ServerGroup | None:
        """Return the server group named `name`, or `None` if there is none."""
        ...

    @abstractmethod
    def list_server_groups(self) -> list[ServerGroup]:
        """Return every server group."""
        ...

    @abstractmethod
    def save_server_group(self, group: ServerGroup) -> None:
        """Create or overwrite the server group identified by `group.name`."""
        ...

    @abstractmethod
    def delete_server_group(self, name: str) -> None:
        """Remove the server group named `name`; see `delete_user_group`
        for the same pre-validated-by-the-caller expectation."""
        ...

    @abstractmethod
    def list_permissions(self) -> list[Permission]:
        """Return every permission grant."""
        ...

    @abstractmethod
    def save_permission(self, permission: Permission) -> None:
        """Create or overwrite the grant identified by the
        `(user_group, server_group)` pair -- not by `permission.id`.

        Granting again for the same pair (e.g. at a different
        `PermissionLevel`) replaces the existing entry rather than adding a
        second one.
        """
        ...

    @abstractmethod
    def delete_permission(self, user_group: str, server_group: str) -> None:
        """Remove the grant for this `(user_group, server_group)` pair.

        Unlike the other `delete_*` methods here, `JsonStore` raises
        `FileNotFoundError` when there is no matching entry rather than
        treating it as a no-op, since `core.core.revoke` does not
        pre-check existence the way it does for the other entities.
        """
        ...

    @abstractmethod
    def get_sudo_profile(self, name: str) -> SudoProfile | None:
        """Return the sudo profile named `name`, or `None` if there is none."""
        ...

    @abstractmethod
    def list_sudo_profiles(self) -> list[SudoProfile]:
        """Return every sudo profile."""
        ...

    @abstractmethod
    def save_sudo_profile(self, profile: SudoProfile) -> None:
        """Create or overwrite the sudo profile identified by `profile.name`."""
        ...

    @abstractmethod
    def delete_sudo_profile(self, name: str) -> None:
        """Remove the sudo profile named `name`.

        `core.core.delete_sudo_profile` checks first that no
        `Permission` still references it, so this does not need to guard
        against deleting a profile that is in active use.
        """
        ...

    @abstractmethod
    def lock(self) -> None:
        """Acquire an exclusive, store-wide lock, raising
        `exceptions.LockBusy` if another process already holds it.

        `core.core` acquires this around every mutating operation (via
        `with self.store:`) so two AdminForge processes never interleave
        writes to the same state; note that id allocation in
        `interfaces.auditor.IAuditor.next_id` happens before this lock
        is taken, so it is not itself covered by it.
        """
        ...

    @abstractmethod
    def unlock(self) -> None:
        """Release the lock taken by `lock`.

        Expected to be safe to call even if the lock was never acquired
        (a no-op), so cleanup code does not need to track whether `lock`
        actually succeeded before calling this.
        """
        ...
