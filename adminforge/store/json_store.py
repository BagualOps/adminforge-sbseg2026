from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from uuid import UUID

from adminforge.domain import (
    CredencialSSH,
    GrupoServidor,
    GrupoUser,
    NivelPermissao,
    Permissao,
    Servidor,
    StatusCredencial,
    StatusUser,
    SudoProfile,
    User,
)
from adminforge.exceptions import LockOcupado
from adminforge.interfaces.store import IStore
from adminforge.store.atomic import write_atomic


class JsonStore(IStore):
    EXTENSAO = ".json"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.dir_users = self.root / "users"
        self.dir_user_groups = self.root / "user-groups"
        self.dir_servers = self.root / "servers"
        self.dir_server_groups = self.root / "server-groups"
        self.dir_sudo_profiles = self.root / "sudo-profiles"
        self.file_permissions = self.root / "permissions.json"
        self.file_lock = self.root / ".lock"
        self._lock_fd: int | None = None
        self._init_dirs()

    def _init_dirs(self) -> None:
        for d in (
            self.root,
            self.dir_users,
            self.dir_user_groups,
            self.dir_servers,
            self.dir_server_groups,
            self.dir_sudo_profiles,
        ):
            d.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(d, 0o700)
            except PermissionError:
                pass

    def lock(self) -> None:
        self.file_lock.touch(exist_ok=True)
        os.chmod(self.file_lock, 0o600)
        fd = os.open(self.file_lock, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise LockOcupado("another AdminForge instance is running") from None
        self._lock_fd = fd

    def unlock(self) -> None:
        if self._lock_fd is not None:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            self._lock_fd = None

    def __enter__(self) -> JsonStore:
        self.lock()
        return self

    def __exit__(self, *_) -> None:
        self.unlock()

    def _dump(self, data: dict) -> str:
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    def _load(self, path: Path) -> dict:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)

    def get_user(self, username: str) -> User | None:
        data = self._load(self.dir_users / f"{username}.json")
        if not data:
            return None
        return User(
            username=data["username"],
            nome=data["nome"],
            email=data["email"],
            status=StatusUser(data.get("status", "ativo")),
            id=UUID(data["id"]),
        )

    def list_users(self) -> list[User]:
        users = []
        for arquivo in sorted(self.dir_users.glob("*.json")):
            u = self.get_user(arquivo.stem)
            if u is not None:
                users.append(u)
        return users

    def save_user(self, user: User) -> None:
        data: dict = {
            "id": str(user.id),
            "username": user.username,
            "nome": user.nome,
            "email": user.email,
            "status": user.status.value,
            "credenciais": [],
        }
        path = self.dir_users / f"{user.username}.json"
        existente = self._load(path)
        if "credenciais" in existente:
            data["credenciais"] = existente["credenciais"]
        write_atomic(path, self._dump(data))

    def list_credenciais(self, username: str) -> list[CredencialSSH]:
        data = self._load(self.dir_users / f"{username}.json")
        creds = []
        for c in data.get("credenciais", []):
            creds.append(
                CredencialSSH(
                    id=UUID(c["id"]),
                    username=username,
                    chave_publica=c["chave_publica"],
                    fingerprint=c["fingerprint"],
                    status=StatusCredencial(c.get("status", "ativa")),
                )
            )
        return creds

    def save_credencial(self, cred: CredencialSSH) -> None:
        path = self.dir_users / f"{cred.username}.json"
        data = self._load(path)
        if not data:
            raise FileNotFoundError(f"user '{cred.username}' does not exist")
        creds = data.setdefault("credenciais", [])
        encontrou = False
        for c in creds:
            if c["id"] == str(cred.id):
                c["chave_publica"] = cred.chave_publica
                c["fingerprint"] = cred.fingerprint
                c["status"] = cred.status.value
                encontrou = True
                break
        if not encontrou:
            creds.append(
                {
                    "id": str(cred.id),
                    "chave_publica": cred.chave_publica,
                    "fingerprint": cred.fingerprint,
                    "status": cred.status.value,
                }
            )
        write_atomic(path, self._dump(data))

    def get_credencial_por_fingerprint(self, fingerprint: str) -> CredencialSSH | None:
        for user in self.list_users():
            for c in self.list_credenciais(user.username):
                if c.fingerprint == fingerprint:
                    return c
        return None

    def get_servidor(self, hostname: str) -> Servidor | None:
        data = self._load(self.dir_servers / f"{hostname}.json")
        if not data:
            return None
        return Servidor(
            id=UUID(data["id"]),
            hostname=data["hostname"],
            ipv4=data["ipv4"],
            porta_ssh=data.get("porta_ssh", 22),
            chave_host=data.get("chave_host", ""),
            chaves_instaladas=list(data.get("chaves_instaladas", [])),
        )

    def list_servidores(self) -> list[Servidor]:
        out = []
        for arquivo in sorted(self.dir_servers.glob("*.json")):
            s = self.get_servidor(arquivo.stem)
            if s is not None:
                out.append(s)
        return out

    def save_servidor(self, servidor: Servidor) -> None:
        data = {
            "id": str(servidor.id),
            "hostname": servidor.hostname,
            "ipv4": servidor.ipv4,
            "porta_ssh": servidor.porta_ssh,
            "chave_host": servidor.chave_host,
            "chaves_instaladas": list(servidor.chaves_instaladas),
        }
        write_atomic(self.dir_servers / f"{servidor.hostname}.json", self._dump(data))

    def delete_servidor(self, hostname: str) -> None:
        (self.dir_servers / f"{hostname}.json").unlink(missing_ok=True)

    def get_grupo_user(self, nome: str) -> GrupoUser | None:
        data = self._load(self.dir_user_groups / f"{nome}.json")
        if not data:
            return None
        return GrupoUser(
            id=UUID(data["id"]), nome=data["nome"], membros=list(data.get("membros", []))
        )

    def list_grupos_user(self) -> list[GrupoUser]:
        out = []
        for arquivo in sorted(self.dir_user_groups.glob("*.json")):
            g = self.get_grupo_user(arquivo.stem)
            if g is not None:
                out.append(g)
        return out

    def save_grupo_user(self, grupo: GrupoUser) -> None:
        data = {"id": str(grupo.id), "nome": grupo.nome, "membros": list(grupo.membros)}
        write_atomic(self.dir_user_groups / f"{grupo.nome}.json", self._dump(data))

    def delete_grupo_user(self, nome: str) -> None:
        (self.dir_user_groups / f"{nome}.json").unlink(missing_ok=True)

    def get_grupo_servidor(self, nome: str) -> GrupoServidor | None:
        data = self._load(self.dir_server_groups / f"{nome}.json")
        if not data:
            return None
        return GrupoServidor(
            id=UUID(data["id"]), nome=data["nome"], membros=list(data.get("membros", []))
        )

    def list_grupos_servidor(self) -> list[GrupoServidor]:
        out = []
        for arquivo in sorted(self.dir_server_groups.glob("*.json")):
            g = self.get_grupo_servidor(arquivo.stem)
            if g is not None:
                out.append(g)
        return out

    def save_grupo_servidor(self, grupo: GrupoServidor) -> None:
        data = {"id": str(grupo.id), "nome": grupo.nome, "membros": list(grupo.membros)}
        write_atomic(self.dir_server_groups / f"{grupo.nome}.json", self._dump(data))

    def delete_grupo_servidor(self, nome: str) -> None:
        (self.dir_server_groups / f"{nome}.json").unlink(missing_ok=True)

    def list_permissoes(self) -> list[Permissao]:
        data = self._load(self.file_permissions)
        out = []
        for p in data.get("permissoes", []):
            out.append(
                Permissao(
                    id=UUID(p["id"]),
                    grupo_user=p["grupo_user"],
                    grupo_servidor=p["grupo_servidor"],
                    nivel=NivelPermissao(p["nivel"]),
                    profile=p.get("profile"),
                )
            )
        return out

    def save_permissao(self, permissao: Permissao) -> None:
        data = self._load(self.file_permissions) or {"permissoes": []}
        permissoes = data.setdefault("permissoes", [])
        atualizou = False
        for p in permissoes:
            if (
                p["grupo_user"] == permissao.grupo_user
                and p["grupo_servidor"] == permissao.grupo_servidor
            ):
                p["nivel"] = permissao.nivel.value
                p["profile"] = permissao.profile
                atualizou = True
                break
        if not atualizou:
            permissoes.append(
                {
                    "id": str(permissao.id),
                    "grupo_user": permissao.grupo_user,
                    "grupo_servidor": permissao.grupo_servidor,
                    "nivel": permissao.nivel.value,
                    "profile": permissao.profile,
                }
            )
        write_atomic(self.file_permissions, self._dump(data))

    def delete_permissao(self, grupo_user: str, grupo_servidor: str) -> None:
        data = self._load(self.file_permissions) or {"permissoes": []}
        antes = len(data.get("permissoes", []))
        data["permissoes"] = [
            p
            for p in data.get("permissoes", [])
            if not (p["grupo_user"] == grupo_user and p["grupo_servidor"] == grupo_servidor)
        ]
        if len(data["permissoes"]) == antes:
            raise FileNotFoundError("permission does not exist")
        write_atomic(self.file_permissions, self._dump(data))

    def get_sudo_profile(self, nome: str) -> SudoProfile | None:
        data = self._load(self.dir_sudo_profiles / f"{nome}.json")
        if not data:
            return None
        return SudoProfile(
            id=UUID(data["id"]),
            nome=data["nome"],
            comandos=list(data.get("comandos", [])),
        )

    def list_sudo_profiles(self) -> list[SudoProfile]:
        out = []
        for arquivo in sorted(self.dir_sudo_profiles.glob("*.json")):
            p = self.get_sudo_profile(arquivo.stem)
            if p is not None:
                out.append(p)
        return out

    def save_sudo_profile(self, profile: SudoProfile) -> None:
        data = {"id": str(profile.id), "nome": profile.nome, "comandos": list(profile.comandos)}
        write_atomic(self.dir_sudo_profiles / f"{profile.nome}.json", self._dump(data))

    def delete_sudo_profile(self, nome: str) -> None:
        (self.dir_sudo_profiles / f"{nome}.json").unlink(missing_ok=True)

    # ---------------------------------------------------------------------------
    # Renomeacao em lote: cada uma faz move atomico do arquivo + atualiza o campo
    # de nome dentro do JSON. Cascata de referencias e responsabilidade do Nucleo.
    # ---------------------------------------------------------------------------
    def _renomear_entidade(self, diretorio: Path, de: str, para: str, campo: str) -> None:
        antigo = diretorio / f"{de}.json"
        novo = diretorio / f"{para}.json"
        if not antigo.exists():
            raise FileNotFoundError(antigo)
        if novo.exists():
            raise FileExistsError(novo)
        data = self._load(antigo)
        data[campo] = para
        write_atomic(novo, self._dump(data))
        antigo.unlink()

    def rename_user(self, de: str, para: str) -> None:
        self._renomear_entidade(self.dir_users, de, para, "username")

    def rename_servidor(self, de: str, para: str) -> None:
        self._renomear_entidade(self.dir_servers, de, para, "hostname")

    def rename_grupo_user(self, de: str, para: str) -> None:
        self._renomear_entidade(self.dir_user_groups, de, para, "nome")

    def rename_grupo_servidor(self, de: str, para: str) -> None:
        self._renomear_entidade(self.dir_server_groups, de, para, "nome")

    def rename_sudo_profile(self, de: str, para: str) -> None:
        self._renomear_entidade(self.dir_sudo_profiles, de, para, "nome")

    def replace_permissoes(self, perms: list[Permissao]) -> None:
        data = {
            "permissoes": [
                {
                    "id": str(p.id),
                    "grupo_user": p.grupo_user,
                    "grupo_servidor": p.grupo_servidor,
                    "nivel": p.nivel.value,
                    "profile": p.profile,
                }
                for p in perms
            ]
        }
        write_atomic(self.file_permissions, self._dump(data))
