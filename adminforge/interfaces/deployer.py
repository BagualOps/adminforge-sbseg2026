"""Port for applying planned changes to a target server. `core.nucleo`
depends only on this interface, so a real SSH deployer, a dry-run
no-op deployer, or a test double can be swapped in without touching the
core logic.
"""

from abc import ABC, abstractmethod

from adminforge.domain import Servidor, Subacao


class IDeployer(ABC):
    """Executes (or simulates executing) `Subacao`s from `planner.Planner`
    against one `Servidor` at a time.
    """

    @abstractmethod
    def aplicar(self, servidor: Servidor, subacoes: list[Subacao]) -> list[Subacao]:
        """Apply `subacoes` to `servidor` and return the same list with each
        entry's `status`/`erro` filled in to reflect its own outcome.

        Expected not to raise: both implementations (`ssh_deployer.
        SSHDeployer`, `dry_run.DryRunDeployer`) report every failure --
        including connectivity failures that affect the whole batch -- as
        `Subacao.status = "falha"` rather than propagating an exception,
        so a caller can always rely on getting a same-length list back and
        does not need a try/except around this call. A mix of `"sucesso"`
        and `"falha"` entries is a normal, recoverable outcome that
        `core.nucleo` turns into `StatusOperacao.SUCESSO_PARCIAL`.
        """
        ...

    @abstractmethod
    def inspecionar(self, servidor: Servidor) -> dict:
        """Return the deployer's live view of what is actually installed
        on `servidor`, independent of what the store/planner believe.

        This is the piece that makes `reconcile=True` in `core.nucleo`
        meaningful: without it, AdminForge can only ever compare its own
        prior records against themselves.
        """
        ...

    @abstractmethod
    def ler_authorized_keys(self, servidor: Servidor, username: str) -> tuple[str, bool]:
        """Return (conteudo, ok). ok=False when the read failed in an
        unrecoverable way (sudo blocked, SSH error). 'conteudo' should only
        be used as the base for writing when ok=True."""
