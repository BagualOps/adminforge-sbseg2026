"""Port for the audit log: recording each `Operacao` and querying the
resulting tamper-evident history. `core.nucleo` depends only on this
interface, not on any concrete log format.
"""

from abc import ABC, abstractmethod

from adminforge.domain import Operacao


class IAuditor(ABC):
    """Append-only, queryable log of `Operacao` records.

    Implementations are expected to make `registrar` durable before it
    returns (`core.nucleo` calls it once per operation, right after
    mutating the store) and to chain entries so tampering is detectable
    via `verificar_cadeia`.
    """

    @abstractmethod
    def registrar(self, operacao: Operacao) -> None:
        """Persist `operacao` as the next entry in the log.

        Expected to fill in whatever chaining/id fields the concrete
        format needs (e.g. linking to the previous entry) as a side
        effect on `operacao` itself, not just write it out.
        """
        ...

    @abstractmethod
    def listar(self, limite: int = 50) -> list[Operacao]:
        """Return up to `limite` most recent operations, newest first.

        `limite=0` (or another falsy value) means "no limit" -- callers
        relying on this to bound memory/output size should pass a
        positive value explicitly.
        """
        ...

    @abstractmethod
    def listar_falhas(self, limite: int = 50) -> list[Operacao]:
        """Return up to `limite` most recent operations whose status is
        not a clean success, newest first.

        Includes partial failures, not only total ones, so an operator
        scanning for "anything that needs attention" does not have to
        also call `listar` and filter client-side.
        """
        ...

    @abstractmethod
    def buscar(self, id: str) -> Operacao | None:
        """Return the operation with the given `id`, or `None` if it is
        not in the log.

        `None` on a miss, not an exception: callers that need a hard
        failure on a missing id should raise `exceptions.NaoExiste`
        themselves (see `JsonlAuditor.buscar_obrigatorio` for that
        wrapper).
        """
        ...

    @abstractmethod
    def verificar_cadeia(self) -> tuple[bool, str | None]:
        """Recompute the log's hash chain from scratch and confirm it is
        intact.

        Expected to raise `exceptions.CadeiaQuebrada` rather than return a
        falsy result when a break is found; the boolean in the return
        value is for the success path, and the paired string is the hash
        of the last verified entry (or `None` for an empty log).
        """
        ...

    @abstractmethod
    def proximo_id(self) -> str:
        """Return the id the next `registrar`ed operation should use.

        Callers must allocate this before building the `Operacao` they
        intend to register. Note that `core.nucleo._nova_op` calls this
        before acquiring the store's lock (`interfaces.store.IStore.lock`),
        so id allocation is not itself covered by that lock; a concrete
        implementation that wants collision-free ids under concurrent
        callers has to provide that guarantee on its own.
        """
        ...
