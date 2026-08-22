"""Simulated ``IDeployer``: mirrors ``SSHDeployer``'s interface with zero remote effects.

Nothing here opens a network connection, runs a subprocess, or touches any
file — this is the entire boundary between "what would happen" and "what
actually happens" on a real host. Callers (e.g. ``apply --dry-run``) swap
this in for ``SSHDeployer`` and get back the same shape of results
(``SubAction`` objects with ``status``/``error`` set) without any of
``SSHDeployer``'s side effects, so the rest of the pipeline (audit logging,
reporting) can't tell the difference except by what this class chooses to
report.
"""

from __future__ import annotations

from adminforge.domain import Server, SubAction
from adminforge.interfaces.deployer import IDeployer


class DryRunDeployer(IDeployer):
    """In-memory stand-in for ``SSHDeployer`` used to preview an ``apply`` without touching any server."""

    def __init__(self, fail_on: set[str] | None = None):
        """Set up the simulator, optionally naming hostnames whose sub-actions should simulate failure.

        ``fail_on`` exists purely for testing/preview scenarios that need
        to exercise partial-failure handling without a real unreachable
        host. ``subacoes_executadas`` accumulates every sub-action passed
        to ``apply`` across calls, so callers can inspect what would have
        been done after the fact.
        """
        self.fail_on = fail_on or set()
        self.subacoes_executadas: list[SubAction] = []

    def apply(self, server: Server, sub_actions: list[SubAction]) -> list[SubAction]:
        """Mark each sub-action ``"success"`` or (if the host is in ``fail_on``) ``"failure"``.

        Never performs any real work; this only sets ``status``/``error`` on
        each ``SubAction`` in place, records it in
        ``self.subacoes_executadas``, and returns the same list — matching
        ``SSHDeployer.apply``'s per-sub-action status semantics without
        any of the network or filesystem behavior.
        """
        for s in sub_actions:
            if server.hostname in self.fail_on:
                s.status = "failure"
                s.error = "dry-run: simulated failure"
            else:
                s.status = "success"
            self.subacoes_executadas.append(s)
        return sub_actions

    def inspect(self, server: Server) -> dict:
        """Return an empty-but-shaped inspection result, flagged with ``"dry_run": True``.

        Matches ``SSHDeployer.inspect``'s return keys so callers can
        treat both implementations uniformly, but never queries any real
        server — the ``dry_run`` flag lets a caller distinguish "genuinely
        empty server" from "this was simulated" if it needs to.
        """
        return {
            "users": [],
            "groups": [],
            "servicos": [],
            "sudoers_arquivos": [],
            "sudoers_regras": [],
            "dry_run": True,
        }

    def read_authorized_keys(self, server: Server, username: str) -> tuple[str, bool]:
        """Always report an empty authorized_keys file that was "successfully" read; never touches any server."""
        return "", True
