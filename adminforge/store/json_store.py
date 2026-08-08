"""Plain-JSON, one-file-per-entity implementation of ``IStore``.

Each entity (user, server, group, sudo profile) lives in its own
``<name>.json`` file under a per-kind subdirectory of ``root``; permissions
are the one exception and live together in a single ``permissions.json``.
Every write goes through ``write_atomic`` (temp file + fsync + ``os.replace``)
so a crash mid-write can never leave a half-written file on disk — readers
always see either the previous version or the fully new one.

This class does not serialize concurrent access on its own: multiple
``JsonStore`` instances (e.g. two CLI invocations, or a CLI run against a
running daemon) must coordinate through ``lock()``/``unlock()`` (or the
context-manager form), which takes an exclusive ``flock`` on a dedicated
``.lock`` file in ``root``.
"""

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
    """``IStore`` backed by a directory tree of individually-written JSON files.

    Reads (``get_*``/``list_*``) are plain filesystem reads and never touch
    the process lock. Writes (``save_*``/``delete_*``/``rename_*``) are each
    individually atomic at the file level via ``write_atomic``, but callers
    that need several writes to appear as one logical change (e.g. a rename
    cascade across entities) must still hold ``lock()`` for the duration —
    this class provides no cross-file transactionality by itself.
    """

    EXTENSAO = ".json"

    def __init__(self, root: Path):
        """Bind to ``root`` and eagerly create its directory layout.

        Does not acquire the process lock; call ``lock()`` explicitly, or
        use the instance as a context manager, before performing writes that
        must be exclusive of other AdminForge processes.
        """
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
        """Create every entity subdirectory (idempotent) and lock them to mode 0700.

        A ``PermissionError`` from ``chmod`` is swallowed rather than
        raised, since it typically means the filesystem doesn't support the
        requested mode (e.g. some mounted/shared setups) rather than a real
        failure to create the directory.
        """
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
        """Acquire an exclusive, non-blocking process lock on ``root``.

        Raises ``LockOcupado`` immediately (without waiting) if another
        process already holds the lock, so concurrent AdminForge instances
        fail fast instead of blocking. The lock file itself persists across
        runs; only the in-memory file descriptor tracks whether *this*
        instance currently holds it.
        """
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
        """Release the process lock if held; a no-op if it was never acquired."""
        if self._lock_fd is not None:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            self._lock_fd = None

    def __enter__(self) -> JsonStore:
        """Acquire the process lock and return ``self`` for ``with JsonStore(...) as store:`` usage."""
        self.lock()
        return self

    def __exit__(self, *_) -> None:
        """Release the process lock unconditionally, even if the ``with`` block raised."""
        self.unlock()

    def _dump(self, data: dict) -> str:
        """Serialize ``data`` to pretty-printed JSON (2-space indent) with a trailing newline.

        ``ensure_ascii=False`` keeps non-ASCII characters (e.g. accented
        names) literal in the file instead of ``\\uXXXX``-escaped.
        """
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    def _load(self, path: Path) -> dict:
        """Read and parse a JSON file, treating "missing" and "empty" as equivalent to "no data".

        Returns ``{}`` if ``path`` does not exist or contains only
        whitespace, rather than raising — this lets every ``get_*`` method
        below treat "entity not yet created" uniformly without a separate
        existence check.
        """
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)

    def get_user(self, username: str) -> User | None:
        """Load a single user by username, or ``None`` if no such file exists."""
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
        """Return every user, sorted by filename (i.e. by username)."""
        users = []
        for arquivo in sorted(self.dir_users.glob("*.json")):
            u = self.get_user(arquivo.stem)
            if u is not None:
                users.append(u)
        return users

    def save_user(self, user: User) -> None:
        """Atomically write ``user`` to its file, preserving any existing credentials.

        The user's ``credenciais`` list lives in the same JSON file but is
        not part of the ``User`` domain object passed in here, so this
        method reads the file first to carry the existing credential list
        forward — calling this does not touch or clear credentials.
        """
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
        """Return the SSH credentials embedded in ``username``'s file (empty list if none/user absent)."""
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
        """Upsert ``cred`` into its owning user's file by credential id, then write atomically.

        The whole user file is rewritten (not just the credential), so this
        still gets the same crash-safety as any other write here. Raises
        ``FileNotFoundError`` if the owning user does not exist yet.
        """
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
        """Find the credential matching ``fingerprint`` by scanning every user's credentials.

        Linear in the number of users times their credential count — there
        is no fingerprint index. Fine for AdminForge's expected scale, but
        not something to call in a hot loop over many users.
        """
        for user in self.list_users():
            for c in self.list_credenciais(user.username):
                if c.fingerprint == fingerprint:
                    return c
        return None

    def get_servidor(self, hostname: str) -> Servidor | None:
        """Load a single server by hostname, or ``None`` if no such file exists."""
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
        """Return every server, sorted by filename (i.e. by hostname)."""
        out = []
        for arquivo in sorted(self.dir_servers.glob("*.json")):
            s = self.get_servidor(arquivo.stem)
            if s is not None:
                out.append(s)
        return out

    def save_servidor(self, servidor: Servidor) -> None:
        """Atomically overwrite the server's file with the full ``servidor`` state."""
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
        """Remove the server's file; a no-op (no exception) if it does not exist."""
        (self.dir_servers / f"{hostname}.json").unlink(missing_ok=True)

    def get_grupo_user(self, nome: str) -> GrupoUser | None:
        """Load a single user group by name, or ``None`` if no such file exists."""
        data = self._load(self.dir_user_groups / f"{nome}.json")
        if not data:
            return None
        return GrupoUser(
            id=UUID(data["id"]), nome=data["nome"], membros=list(data.get("membros", []))
        )

    def list_grupos_user(self) -> list[GrupoUser]:
        """Return every user group, sorted by filename (i.e. by group name)."""
        out = []
        for arquivo in sorted(self.dir_user_groups.glob("*.json")):
            g = self.get_grupo_user(arquivo.stem)
            if g is not None:
                out.append(g)
        return out

    def save_grupo_user(self, grupo: GrupoUser) -> None:
        """Atomically overwrite the user group's file with the full ``grupo`` state."""
        data = {"id": str(grupo.id), "nome": grupo.nome, "membros": list(grupo.membros)}
        write_atomic(self.dir_user_groups / f"{grupo.nome}.json", self._dump(data))

    def delete_grupo_user(self, nome: str) -> None:
        """Remove the user group's file; a no-op (no exception) if it does not exist."""
        (self.dir_user_groups / f"{nome}.json").unlink(missing_ok=True)

    def get_grupo_servidor(self, nome: str) -> GrupoServidor | None:
        """Load a single server group by name, or ``None`` if no such file exists."""
        data = self._load(self.dir_server_groups / f"{nome}.json")
        if not data:
            return None
        return GrupoServidor(
            id=UUID(data["id"]), nome=data["nome"], membros=list(data.get("membros", []))
        )

    def list_grupos_servidor(self) -> list[GrupoServidor]:
        """Return every server group, sorted by filename (i.e. by group name)."""
        out = []
        for arquivo in sorted(self.dir_server_groups.glob("*.json")):
            g = self.get_grupo_servidor(arquivo.stem)
            if g is not None:
                out.append(g)
        return out

    def save_grupo_servidor(self, grupo: GrupoServidor) -> None:
        """Atomically overwrite the server group's file with the full ``grupo`` state."""
        data = {"id": str(grupo.id), "nome": grupo.nome, "membros": list(grupo.membros)}
        write_atomic(self.dir_server_groups / f"{grupo.nome}.json", self._dump(data))

    def delete_grupo_servidor(self, nome: str) -> None:
        """Remove the server group's file; a no-op (no exception) if it does not exist."""
        (self.dir_server_groups / f"{nome}.json").unlink(missing_ok=True)

    def list_permissoes(self) -> list[Permissao]:
        """Return every permission entry from the shared ``permissions.json`` file."""
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
        """Upsert ``permissao`` keyed by the (grupo_user, grupo_servidor) pair, not by id.

        If an entry already exists for the same group pair, its ``nivel``
        and ``profile`` are updated in place (keeping the original entry's
        id); otherwise a new entry is appended. The whole permissions file
        is rewritten atomically either way.
        """
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
        """Remove the permission for the given group pair.

        Unlike the other ``delete_*`` methods in this class, this raises
        ``FileNotFoundError`` if no matching entry exists, since permissions
        share one file and there is no missing-file signal to fall back on.
        """
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
        """Load a single sudo profile by name, or ``None`` if no such file exists."""
        data = self._load(self.dir_sudo_profiles / f"{nome}.json")
        if not data:
            return None
        return SudoProfile(
            id=UUID(data["id"]),
            nome=data["nome"],
            comandos=list(data.get("comandos", [])),
        )

    def list_sudo_profiles(self) -> list[SudoProfile]:
        """Return every sudo profile, sorted by filename (i.e. by profile name)."""
        out = []
        for arquivo in sorted(self.dir_sudo_profiles.glob("*.json")):
            p = self.get_sudo_profile(arquivo.stem)
            if p is not None:
                out.append(p)
        return out

    def save_sudo_profile(self, profile: SudoProfile) -> None:
        """Atomically overwrite the sudo profile's file with the full ``profile`` state."""
        data = {"id": str(profile.id), "nome": profile.nome, "comandos": list(profile.comandos)}
        write_atomic(self.dir_sudo_profiles / f"{profile.nome}.json", self._dump(data))

    def delete_sudo_profile(self, nome: str) -> None:
        """Remove the sudo profile's file; a no-op (no exception) if it does not exist."""
        (self.dir_sudo_profiles / f"{nome}.json").unlink(missing_ok=True)

    # ---------------------------------------------------------------------------
    # Renomeacao em lote: cada uma faz move atomico do arquivo + atualiza o campo
    # de nome dentro do JSON. Cascata de referencias e responsabilidade do Nucleo.
    # ---------------------------------------------------------------------------
    def _renomear_entidade(self, diretorio: Path, de: str, para: str, campo: str) -> None:
        """Rename an entity's file from ``de`` to ``para``, updating its name field in place.

        Raises ``FileNotFoundError`` if the source is missing and
        ``FileExistsError`` if the destination already exists (never
        silently overwrites on rename). The name field is rewritten and
        fsynced to the *old* path first via ``write_atomic``, then the file
        is moved to the new path with ``os.replace`` — a single syscall, so
        there is no window where both the old and new filenames exist (or
        neither does). Updating any other entity that references this name
        by value is the caller's (Nucleo's) responsibility, not this
        method's.
        """
        antigo = diretorio / f"{de}.json"
        novo = diretorio / f"{para}.json"
        if not antigo.exists():
            raise FileNotFoundError(antigo)
        if novo.exists():
            raise FileExistsError(novo)
        data = self._load(antigo)
        data[campo] = para
        # atualiza o campo no proprio arquivo antigo e move atomicamente:
        # os.replace e uma unica syscall — nao ha janela com os dois nomes presentes.
        write_atomic(antigo, self._dump(data))
        os.replace(antigo, novo)

    def rename_user(self, de: str, para: str) -> None:
        """Rename a user's file and its embedded ``username`` field; see ``_renomear_entidade``."""
        self._renomear_entidade(self.dir_users, de, para, "username")

    def rename_servidor(self, de: str, para: str) -> None:
        """Rename a server's file and its embedded ``hostname`` field; see ``_renomear_entidade``."""
        self._renomear_entidade(self.dir_servers, de, para, "hostname")

    def rename_grupo_user(self, de: str, para: str) -> None:
        """Rename a user group's file and its embedded ``nome`` field; see ``_renomear_entidade``."""
        self._renomear_entidade(self.dir_user_groups, de, para, "nome")

    def rename_grupo_servidor(self, de: str, para: str) -> None:
        """Rename a server group's file and its embedded ``nome`` field; see ``_renomear_entidade``."""
        self._renomear_entidade(self.dir_server_groups, de, para, "nome")

    def rename_sudo_profile(self, de: str, para: str) -> None:
        """Rename a sudo profile's file and its embedded ``nome`` field; see ``_renomear_entidade``."""
        self._renomear_entidade(self.dir_sudo_profiles, de, para, "nome")

    def replace_permissoes(self, perms: list[Permissao]) -> None:
        """Atomically replace the entire permissions file with exactly ``perms``.

        This is a full overwrite, not a merge: any existing permission not
        present in ``perms`` is dropped.
        """
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
