"""Port for applying planned changes to a target server. `core.core`
depends only on this interface, so a real SSH deployer, a dry-run
no-op deployer, or a test double can be swapped in without touching the
core logic.
"""

from abc import ABC, abstractmethod

from adminforge.domain import Server, SubAction


class IDeployer(ABC):
    """Executes (or simulates executing) `SubAction`s from `planner.Planner`
    against one `Server` at a time.
    """

    @abstractmethod
    def apply(self, server: Server, sub_actions: list[SubAction]) -> list[SubAction]:
        """Apply `sub_actions` to `server` and return the same list with each
        entry's `status`/`error` filled in to reflect its own outcome.

        Expected not to raise: both implementations (`ssh_deployer.
        SSHDeployer`, `dry_run.DryRunDeployer`) report every failure --
        including connectivity failures that affect the whole batch -- as
        `SubAction.status = "failure"` rather than propagating an exception,
        so a caller can always rely on getting a same-length list back and
        does not need a try/except around this call. A mix of `"success"`
        and `"failure"` entries is a normal, recoverable outcome that
        `core.core` turns into `OperationStatus.PARTIAL_SUCCESS`.
        """
        ...

    @abstractmethod
    def inspect(self, server: Server) -> dict:
        """Return the deployer's live view of what is actually installed
        on `server`, independent of what the store/planner believe.

        This is the piece that makes `reconcile=True` in `core.core`
        meaningful: without it, AdminForge can only ever compare its own
        prior records against themselves.
        """
        ...

    @abstractmethod
    def read_authorized_keys(self, server: Server, username: str) -> tuple[str, bool]:
        """Return (conteudo, ok). ok=False when the read failed in an
        unrecoverable way (sudo blocked, SSH error). 'conteudo' should only
        be used as the base for writing when ok=True."""
