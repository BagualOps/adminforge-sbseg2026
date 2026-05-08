from abc import ABC, abstractmethod

from adminforge.domain import (
    CredencialSSH,
    GrupoServidor,
    GrupoUser,
    Permissao,
    Servidor,
    SudoProfile,
    User,
)


class IStore(ABC):
    @abstractmethod
    def get_user(self, username: str) -> User | None: ...

    @abstractmethod
    def list_users(self) -> list[User]: ...

    @abstractmethod
    def save_user(self, user: User) -> None: ...

    @abstractmethod
    def get_servidor(self, hostname: str) -> Servidor | None: ...

    @abstractmethod
    def list_servidores(self) -> list[Servidor]: ...

    @abstractmethod
    def save_servidor(self, servidor: Servidor) -> None: ...

    @abstractmethod
    def delete_servidor(self, hostname: str) -> None: ...

    @abstractmethod
    def list_credenciais(self, username: str) -> list[CredencialSSH]: ...

    @abstractmethod
    def save_credencial(self, cred: CredencialSSH) -> None: ...

    @abstractmethod
    def get_credencial_por_fingerprint(self, fingerprint: str) -> CredencialSSH | None: ...

    @abstractmethod
    def get_grupo_user(self, nome: str) -> GrupoUser | None: ...

    @abstractmethod
    def list_grupos_user(self) -> list[GrupoUser]: ...

    @abstractmethod
    def save_grupo_user(self, grupo: GrupoUser) -> None: ...

    @abstractmethod
    def delete_grupo_user(self, nome: str) -> None: ...

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
    def delete_permissao(self, grupo_user: str, grupo_servidor: str) -> None: ...

    @abstractmethod
    def get_sudo_profile(self, nome: str) -> SudoProfile | None: ...

    @abstractmethod
    def list_sudo_profiles(self) -> list[SudoProfile]: ...

    @abstractmethod
    def save_sudo_profile(self, profile: SudoProfile) -> None: ...

    @abstractmethod
    def delete_sudo_profile(self, nome: str) -> None: ...

    @abstractmethod
    def lock(self) -> None: ...

    @abstractmethod
    def unlock(self) -> None: ...
