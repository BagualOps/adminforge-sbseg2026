from abc import ABC, abstractmethod

from adminforge.domain import Servidor, Subacao


class IDeployer(ABC):
    @abstractmethod
    def aplicar(self, servidor: Servidor, subacoes: list[Subacao]) -> list[Subacao]: ...

    @abstractmethod
    def inspecionar(self, servidor: Servidor) -> dict: ...

    @abstractmethod
    def ler_authorized_keys(self, servidor: Servidor, username: str) -> str: ...
