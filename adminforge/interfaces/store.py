from abc import ABC, abstractmethod

from adminforge.domain import (
    Admin,
    CredencialSSH,
    GrupoAdmin,
    GrupoServidor,
    Permissao,
    Servidor,
)


class IStore(ABC):
    @abstractmethod
    def get_admin(self, username: str) -> Admin | None: ...

    @abstractmethod
    def list_admins(self) -> list[Admin]: ...

    @abstractmethod
    def save_admin(self, admin: Admin) -> None: ...

    @abstractmethod
    def get_servidor(self, hostname: str) -> Servidor | None: ...

    @abstractmethod
    def list_servidores(self) -> list[Servidor]: ...

    @abstractmethod
    def save_servidor(self, servidor: Servidor) -> None: ...

    @abstractmethod
    def delete_servidor(self, hostname: str) -> None: ...

    @abstractmethod
    def list_credenciais(self, admin_username: str) -> list[CredencialSSH]: ...

    @abstractmethod
    def save_credencial(self, cred: CredencialSSH) -> None: ...

    @abstractmethod
    def get_credencial_por_fingerprint(self, fingerprint: str) -> CredencialSSH | None: ...

    @abstractmethod
    def get_grupo_admin(self, nome: str) -> GrupoAdmin | None: ...

    @abstractmethod
    def list_grupos_admin(self) -> list[GrupoAdmin]: ...

    @abstractmethod
    def save_grupo_admin(self, grupo: GrupoAdmin) -> None: ...

    @abstractmethod
    def delete_grupo_admin(self, nome: str) -> None: ...

    @abstractmethod
    def get_grupo_servidor(self, nome: str) -> GrupoServidor | None: ...

    @abstractmethod
    def list_grupos_servidor(self) -> list[GrupoServidor]: ...

    @abstractmethod
    def save_grupo_servidor(self, grupo: GrupoServidor) -> None: ...

    @abstractmethod
    def delete_grupo_servidor(self, nome: str) -> None: ...

    @abstractmethod
    def list_permissoes(self) -> list[Permissao]: ...

    @abstractmethod
    def save_permissao(self, permissao: Permissao) -> None: ...

    @abstractmethod
    def delete_permissao(self, grupo_admin: str, grupo_servidor: str) -> None: ...

    @abstractmethod
    def lock(self) -> None: ...

    @abstractmethod
    def unlock(self) -> None: ...
