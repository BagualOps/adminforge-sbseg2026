from __future__ import annotations

from adminforge.domain import Servidor, Subacao
from adminforge.interfaces.deployer import IDeployer


class DryRunDeployer(IDeployer):
    def __init__(self, falhar_em: set[str] | None = None):
        self.falhar_em = falhar_em or set()
        self.subacoes_executadas: list[Subacao] = []

    def aplicar(self, servidor: Servidor, subacoes: list[Subacao]) -> list[Subacao]:
        for s in subacoes:
            if servidor.hostname in self.falhar_em:
                s.status = "falha"
                s.erro = "dry-run: falha simulada"
            else:
                s.status = "sucesso"
            self.subacoes_executadas.append(s)
        return subacoes

    def inspecionar(self, servidor: Servidor) -> dict:
        return {
            "usuarios": [],
            "grupos": [],
            "servicos": [],
            "sudoers_arquivos": [],
            "sudoers_regras": [],
            "dry_run": True,
        }
