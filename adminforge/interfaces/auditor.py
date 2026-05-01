from abc import ABC, abstractmethod

from adminforge.domain import Operacao


class IAuditor(ABC):
    @abstractmethod
    def registrar(self, operacao: Operacao) -> None: ...

    @abstractmethod
    def listar(self, limite: int = 50) -> list[Operacao]: ...

    @abstractmethod
    def listar_falhas(self, limite: int = 50) -> list[Operacao]: ...

    @abstractmethod
    def buscar(self, id: str) -> Operacao | None: ...

    @abstractmethod
    def verificar_cadeia(self) -> tuple[bool, str | None]: ...

    @abstractmethod
    def proximo_id(self) -> str: ...
