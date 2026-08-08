"""Simulated ``IDeployer``: mirrors ``SSHDeployer``'s interface with zero remote effects.

Nothing here opens a network connection, runs a subprocess, or touches any
file — this is the entire boundary between "what would happen" and "what
actually happens" on a real host. Callers (e.g. ``apply --dry-run``) swap
this in for ``SSHDeployer`` and get back the same shape of results
(``Subacao`` objects with ``status``/``erro`` set) without any of
``SSHDeployer``'s side effects, so the rest of the pipeline (audit logging,
reporting) can't tell the difference except by what this class chooses to
report.
"""

from __future__ import annotations

from adminforge.domain import Servidor, Subacao
from adminforge.interfaces.deployer import IDeployer


class DryRunDeployer(IDeployer):
    """In-memory stand-in for ``SSHDeployer`` used to preview an ``apply`` without touching any server."""

    def __init__(self, falhar_em: set[str] | None = None):
        """Set up the simulator, optionally naming hostnames whose sub-actions should simulate failure.

        ``falhar_em`` exists purely for testing/preview scenarios that need
        to exercise partial-failure handling without a real unreachable
        host. ``subacoes_executadas`` accumulates every sub-action passed
        to ``aplicar`` across calls, so callers can inspect what would have
        been done after the fact.
        """
        self.falhar_em = falhar_em or set()
        self.subacoes_executadas: list[Subacao] = []

    def aplicar(self, servidor: Servidor, subacoes: list[Subacao]) -> list[Subacao]:
        """Mark each sub-action ``"sucesso"`` or (if the host is in ``falhar_em``) ``"falha"``.

        Never performs any real work; this only sets ``status``/``erro`` on
        each ``Subacao`` in place, records it in
        ``self.subacoes_executadas``, and returns the same list — matching
        ``SSHDeployer.aplicar``'s per-sub-action status semantics without
        any of the network or filesystem behavior.
        """
        for s in subacoes:
            if servidor.hostname in self.falhar_em:
                s.status = "falha"
                s.erro = "dry-run: falha simulada"
            else:
                s.status = "sucesso"
            self.subacoes_executadas.append(s)
        return subacoes

    def inspecionar(self, servidor: Servidor) -> dict:
        """Return an empty-but-shaped inspection result, flagged with ``"dry_run": True``.

        Matches ``SSHDeployer.inspecionar``'s return keys so callers can
        treat both implementations uniformly, but never queries any real
        server — the ``dry_run`` flag lets a caller distinguish "genuinely
        empty server" from "this was simulated" if it needs to.
        """
        return {
            "usuarios": [],
            "grupos": [],
            "servicos": [],
            "sudoers_arquivos": [],
            "sudoers_regras": [],
            "dry_run": True,
        }

    def ler_authorized_keys(self, servidor: Servidor, username: str) -> tuple[str, bool]:
        """Always report an empty authorized_keys file that was "successfully" read; never touches any server."""
        return "", True
