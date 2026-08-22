"""Port for the audit log: recording each `Operation` and querying the
resulting tamper-evident history. `core.core` depends only on this
interface, not on any concrete log format.
"""

from abc import ABC, abstractmethod

from adminforge.domain import Operation


class IAuditor(ABC):
    """Append-only, queryable log of `Operation` records.

    Implementations are expected to make `record` durable before it
    returns (`core.core` calls it once per operation, right after
    mutating the store) and to chain entries so tampering is detectable
    via `verify_chain`.
    """

    @abstractmethod
    def record(self, operation: Operation) -> None:
        """Persist `operation` as the next entry in the log.

        Expected to fill in whatever chaining/id fields the concrete
        format needs (e.g. linking to the previous entry) as a side
        effect on `operation` itself, not just write it out.
        """
        ...

    @abstractmethod
    def list_operations(self, limit: int = 50) -> list[Operation]:
        """Return up to `limit` most recent operations, newest first.

        `limit=0` (or another falsy value) means "no limit" -- callers
        relying on this to bound memory/output size should pass a
        positive value explicitly.
        """
        ...

    @abstractmethod
    def list_failures(self, limit: int = 50) -> list[Operation]:
        """Return up to `limit` most recent operations whose status is
        not a clean success, newest first.

        Includes partial failures, not only total ones, so an operator
        scanning for "anything that needs attention" does not have to
        also call `list_operations` and filter client-side.
        """
        ...

    @abstractmethod
    def find(self, id: str) -> Operation | None:
        """Return the operation with the given `id`, or `None` if it is
        not in the log.

        `None` on a miss, not an exception: callers that need a hard
        failure on a missing id should raise `exceptions.NotFound`
        themselves (see `JsonlAuditor.find_required` for that
        wrapper).
        """
        ...

    @abstractmethod
    def verify_chain(self) -> tuple[bool, str | None]:
        """Recompute the log's hash chain from scratch and confirm it is
        intact.

        Expected to raise `exceptions.BrokenChain` rather than return a
        falsy result when a break is found; the boolean in the return
        value is for the success path, and the paired string is the hash
        of the last verified entry (or `None` for an empty log).
        """
        ...

    @abstractmethod
    def next_id(self) -> str:
        """Return the id the next `record`ed operation should use.

        Callers must allocate this before building the `Operation` they
        intend to register. Note that `core.core._nova_op` calls this
        before acquiring the store's lock (`interfaces.store.IStore.lock`),
        so id allocation is not itself covered by that lock; a concrete
        implementation that wants collision-free ids under concurrent
        callers has to provide that guarantee on its own.
        """
        ...
