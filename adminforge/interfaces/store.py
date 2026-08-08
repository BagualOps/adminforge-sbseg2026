"""Port for persisting every domain entity except `Operacao` (that goes
through `interfaces.auditor.IAuditor` instead). `core.nucleo` depends
only on this interface; `store.json_store.JsonStore` is the one
implementation shipped with AdminForge.
"""

from abc import ABC, abstractmethod

from adminforge.domain import (
    CredencialSSH,
    GrupoServidor,
    GrupoUser,
    Permissao,
    Servidor,
    SudoProfile,
    User,
)


class IStore(ABC):
    """CRUD access to users, credentials, servers, groups, permissions and
    sudo profiles, plus the process-level lock that serializes writers.

    Entities here are addressed by their natural key (`username`,
    `hostname`, group/profile `nome`, credential `fingerprint`, or the
    `(grupo_user, grupo_servidor)` pair for a `Permissao`) rather than by
    the `id` field each dataclass also carries; `core.nucleo` never looks
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
    def get_servidor(self, hostname: str) -> Servidor | None:
        """Return the server with this `hostname`, or `None` if there is none."""
        ...

    @abstractmethod
    def list_servidores(self) -> list[Servidor]:
        """Return every server."""
        ...

    @abstractmethod
    def save_servidor(self, servidor: Servidor) -> None:
        """Create or overwrite the server identified by `servidor.hostname`."""
        ...

    @abstractmethod
    def delete_servidor(self, hostname: str) -> None:
        """Remove the server identified by `hostname`.

        `core.nucleo` always checks `get_servidor` first and raises
        `exceptions.NaoExiste` itself before calling this, so
        implementations are free to treat a missing hostname as a no-op
        rather than an error (that is what `JsonStore` does).
        """
        ...

    @abstractmethod
    def list_credenciais(self, username: str) -> list[CredencialSSH]:
        """Return every credential belonging to `username`, active and
        revoked alike -- callers that only want usable ones must filter
        on `domain.StatusCredencial.ATIVA` themselves (see
        `planner.planner.Planner.estado_desejado`). Returns an empty list,
        not an error, if `username` does not exist.
        """
        ...

    @abstractmethod
    def save_credencial(self, cred: CredencialSSH) -> None:
        """Create or overwrite `cred`, keyed by `cred.id` (not
        `fingerprint`) within its owning user's credentials.

        There is no `delete_credencial`: revocation is expressed by
        saving the same credential back with
        `status=StatusCredencial.REVOGADA` rather than by removing it.
        """
        ...

    @abstractmethod
    def get_credencial_por_fingerprint(self, fingerprint: str) -> CredencialSSH | None:
        """Return a credential with this `fingerprint`, searched across
        all users, or `None` if none matches.

        `core.nucleo.cadastrar_chave` only rejects a duplicate fingerprint
        within the *same* user, not store-wide, so two different users can
        end up with credentials that share a fingerprint; this method does
        not guarantee which one it returns in that case, only that it
        returns one of them.
        """
        ...

    @abstractmethod
    def get_grupo_user(self, nome: str) -> GrupoUser | None:
        """Return the user group named `nome`, or `None` if there is none."""
        ...

    @abstractmethod
    def list_grupos_user(self) -> list[GrupoUser]:
        """Return every user group."""
        ...

    @abstractmethod
    def save_grupo_user(self, grupo: GrupoUser) -> None:
        """Create or overwrite the user group identified by `grupo.nome`."""
        ...

    @abstractmethod
    def delete_grupo_user(self, nome: str) -> None:
        """Remove the user group named `nome`.

        As with `delete_servidor`, `core.nucleo` pre-validates existence
        (and that no `Permissao` still references the group) before
        calling this, so a missing name need not be treated as an error.
        """
        ...

    @abstractmethod
    def get_grupo_servidor(self, nome: str) -> GrupoServidor | None:
        """Return the server group named `nome`, or `None` if there is none."""
        ...

    @abstractmethod
    def list_grupos_servidor(self) -> list[GrupoServidor]:
        """Return every server group."""
        ...

    @abstractmethod
    def save_grupo_servidor(self, grupo: GrupoServidor) -> None:
        """Create or overwrite the server group identified by `grupo.nome`."""
        ...

    @abstractmethod
    def delete_grupo_servidor(self, nome: str) -> None:
        """Remove the server group named `nome`; see `delete_grupo_user`
        for the same pre-validated-by-the-caller expectation."""
        ...

    @abstractmethod
    def list_permissoes(self) -> list[Permissao]:
        """Return every permission grant."""
        ...

    @abstractmethod
    def save_permissao(self, permissao: Permissao) -> None:
        """Create or overwrite the grant identified by the
        `(grupo_user, grupo_servidor)` pair -- not by `permissao.id`.

        Granting again for the same pair (e.g. at a different
        `NivelPermissao`) replaces the existing entry rather than adding a
        second one.
        """
        ...

    @abstractmethod
    def delete_permissao(self, grupo_user: str, grupo_servidor: str) -> None:
        """Remove the grant for this `(grupo_user, grupo_servidor)` pair.

        Unlike the other `delete_*` methods here, `JsonStore` raises
        `FileNotFoundError` when there is no matching entry rather than
        treating it as a no-op, since `core.nucleo.revogar` does not
        pre-check existence the way it does for the other entities.
        """
        ...

    @abstractmethod
    def get_sudo_profile(self, nome: str) -> SudoProfile | None:
        """Return the sudo profile named `nome`, or `None` if there is none."""
        ...

    @abstractmethod
    def list_sudo_profiles(self) -> list[SudoProfile]:
        """Return every sudo profile."""
        ...

    @abstractmethod
    def save_sudo_profile(self, profile: SudoProfile) -> None:
        """Create or overwrite the sudo profile identified by `profile.nome`."""
        ...

    @abstractmethod
    def delete_sudo_profile(self, nome: str) -> None:
        """Remove the sudo profile named `nome`.

        `core.nucleo.excluir_sudo_profile` checks first that no
        `Permissao` still references it, so this does not need to guard
        against deleting a profile that is in active use.
        """
        ...

    @abstractmethod
    def lock(self) -> None:
        """Acquire an exclusive, store-wide lock, raising
        `exceptions.LockOcupado` if another process already holds it.

        `core.nucleo` acquires this around every mutating operation (via
        `with self.store:`) so two AdminForge processes never interleave
        writes to the same state; note that id allocation in
        `interfaces.auditor.IAuditor.proximo_id` happens before this lock
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
