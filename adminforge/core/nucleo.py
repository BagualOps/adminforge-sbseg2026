"""Core orchestration layer: validate input, mutate persisted state, and audit every operation.

`Nucleo` is the single write path for all AdminForge entities (users, SSH
keys, user-groups, servers, server-groups, permissions, sudo-profiles) and
hosts the plan/apply/reconcile pipeline built on `planner.Planner`. Every
mutating method follows the same shape: allocate an `Operacao`, validate and
mutate `JsonStore` state inside `with self.store:`, and register the
resulting status through `JsonlAuditor` so the audit log always reflects what
was actually persisted. `preview`/`aplicar` are where the paper's central
claim is implemented: without `--reconcile` they answer "is anything
pending?" purely from the locally persisted desired-vs-installed state (no
network I/O), and `aplicar` applies per host independently so its cost scales
linearly with fleet size; passing `reconcile=True` swaps in the real state
fetched over SSH (`_atual_vivo`) for the comparison instead.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from adminforge import ssh_keys
from adminforge.auditor.jsonl_auditor import JsonlAuditor
from adminforge.deployer.dry_run import DryRunDeployer
from adminforge.domain import (
    CredencialSSH,
    GrupoServidor,
    GrupoUser,
    NivelPermissao,
    Operacao,
    Permissao,
    Servidor,
    StatusCredencial,
    StatusOperacao,
    StatusUser,
    Subacao,
    SudoProfile,
    TipoAcao,
    User,
)
from adminforge.exceptions import (
    EstadoInvalido,
    FormatoInvalido,
    JaExiste,
    NaoExiste,
)
from adminforge.i18n import t as _
from adminforge.interfaces.deployer import IDeployer
from adminforge.planner.planner import Planner
from adminforge.store.json_store import JsonStore

_RE_USERNAME = re.compile(r"^[a-z_][a-z0-9_-]{0,30}$")
_RE_HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")
_RE_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_RE_NOME_GRUPO = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")
_RE_IPV4 = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


def _ipv4_valido(ip: str) -> bool:
    """Return whether `ip` is a syntactically valid dotted-quad IPv4 address (each octet 0-255)."""
    if not _RE_IPV4.match(ip):
        return False
    return all(0 <= int(octeto) <= 255 for octeto in ip.split("."))


def _msg_permissoes_associadas(tipo: str, nome: str, perms: list[Permissao]) -> str:
    """Mensagem de erro do delete bloqueado: lista as N permissões e sugere o comando."""
    pares = [(p.grupo_user, p.grupo_servidor, p.nivel.value) for p in perms]
    if tipo == "user-group":
        linhas = [f"  - {gs} ({lvl})" for _gu, gs, lvl in pares]
        comandos = [f"  adminforge permission revoke --user-group {nome} --server-group {gs}" for _gu, gs, _ in pares]
    else:
        linhas = [f"  - {gu} ({lvl})" for gu, _gs, lvl in pares]
        comandos = [f"  adminforge permission revoke --user-group {gu} --server-group {nome}" for gu, _gs, _ in pares]
    return (
        _("{kind} {name} has {n} associated permission(s):").format(kind=_(tipo), name=nome, n=len(perms))
        + "\n" + "\n".join(linhas)
        + "\n" + _("Revoke them first:") + "\n"
        + "\n".join(comandos)
    )


class Nucleo:
    """Facade over `JsonStore`, `JsonlAuditor` and `Planner` that implements every AdminForge command.

    Holds the single `JsonStore` instance (state of record), the
    `JsonlAuditor` (append-only history) and a `Planner` built on the same
    store; `deployer` is the only collaborator that touches real hosts and
    defaults to `DryRunDeployer`, so constructing a `Nucleo` never risks
    reaching the network. Callers are the CLI subcommands; each public method
    maps to one CLI verb and returns the `Operacao` that was appended to the
    audit log, success or failure alike.
    """

    def __init__(
        self,
        store: JsonStore,
        auditor: JsonlAuditor,
        deployer: IDeployer | None = None,
        superadmin: str = "unknown",
    ):
        """Store the collaborators and build a `Planner` bound to the same `store`."""
        self.store = store
        self.auditor = auditor
        self.deployer = deployer or DryRunDeployer()
        self.superadmin = superadmin
        self.planner = Planner(store)

    @classmethod
    def montar(
        cls,
        state_dir: Path,
        deployer: IDeployer | None = None,
        superadmin: str = "unknown",
    ) -> "Nucleo":
        """Build a `Nucleo` wired to a `JsonStore`/`JsonlAuditor` pair rooted at `state_dir`.

        Convenience constructor for the CLI entry point: derives
        `history.jsonl` from `state_dir` so callers only need to know the
        state directory, not the on-disk layout of the store and the audit
        log.
        """
        store = JsonStore(state_dir)
        auditor = JsonlAuditor(state_dir / "history.jsonl")
        return cls(store, auditor, deployer, superadmin)

    def _nova_op(self, comando: str) -> Operacao:
        """Allocate a new `Operacao` in `EM_ANDAMENTO` status with a fresh id and timestamp.

        Called at the top of every command before any validation or
        mutation, so a record already exists to attach a failure to even if
        the command raises before doing any work.
        """
        return Operacao(
            id=self.auditor.proximo_id(),
            momento=datetime.now().astimezone(),
            superadmin=self.superadmin,
            comando=comando,
            status=StatusOperacao.EM_ANDAMENTO,
        )

    def _registrar(self, op: Operacao, status: StatusOperacao) -> Operacao:
        """Set `op.status` and persist it via `self.auditor.registrar`, then return `op`.

        Centralizes the "write the outcome to the audit log" step so every
        command method ends the same way regardless of which status it
        reached.
        """
        op.status = status
        self.auditor.registrar(op)
        return op

    def _registrar_falha(self, op: Operacao, mensagem: str) -> Operacao:
        """Attach a synthetic failed `Subacao` carrying `mensagem` to `op` and register it as `FALHA`.

        Used by the `except Exception` handler at the end of every command
        method, so a validation error or store exception still produces a
        `Subacao` an operator can read from the audit log instead of just a
        bare failure status with no detail.
        """
        op.subacoes.append(
            Subacao(servidor="", acao=TipoAcao.LEITURA, status="falha", erro=mensagem)
        )
        return self._registrar(op, StatusOperacao.FALHA)

    def cadastrar_user(self, username: str, nome: str, email: str) -> Operacao:
        """Validate and persist a new active user, failing if the username or email is malformed or the username is already taken.

        Runs entirely inside a `JsonStore` transaction; any raised exception
        is caught and turned into a `FALHA` `Operacao` rather than
        propagating, so the CLI never crashes on invalid input.
        """
        op = self._nova_op(f"user add {username}")
        try:
            with self.store:
                if not _RE_USERNAME.match(username):
                    raise FormatoInvalido(_("invalid username: {u}").format(u=repr(username)))
                if not nome.strip():
                    raise FormatoInvalido(_("name is required"))
                if not _RE_EMAIL.match(email):
                    raise FormatoInvalido(_("invalid email: {e}").format(e=repr(email)))
                if self.store.get_user(username):
                    raise JaExiste(_("username {u} already exists").format(u=repr(username)))
                self.store.save_user(User(username=username, nome=nome, email=email))
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def desabilitar_user(self, username: str) -> Operacao:
        """Mark `username` as `INATIVO` and revoke all of its currently active SSH credentials.

        Revoking the credentials here, rather than leaving that to the next
        `apply`, means a disabled user shows up as revoked in the store
        immediately, before any `preview`/`apply` runs against the fleet.
        """
        op = self._nova_op(f"user disable {username}")
        try:
            with self.store:
                user = self.store.get_user(username)
                if not user:
                    raise NaoExiste(_("user {u} does not exist").format(u=repr(username)))
                user.status = StatusUser.INATIVO
                self.store.save_user(user)
                for cred in self.store.list_credenciais(username):
                    if cred.status == StatusCredencial.ATIVA:
                        cred.status = StatusCredencial.REVOGADA
                        self.store.save_credencial(cred)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def cadastrar_chave(self, username: str, chave_raw: str) -> Operacao:
        """Register a new SSH public key for `username`, rejecting it if its fingerprint is already on file for that user.

        Keys are stored canonicalized (`ssh_keys.chave_canonica`) and
        deduplicated by fingerprint, not by raw text, so re-submitting the
        same key with different whitespace or a different comment is still
        caught as a duplicate.
        """
        op = self._nova_op(f"user key add {username}")
        try:
            with self.store:
                user = self.store.get_user(username)
                if not user:
                    raise NaoExiste(_("user {u} does not exist").format(u=repr(username)))
                fp = ssh_keys.fingerprint(chave_raw)
                canonica = ssh_keys.chave_canonica(chave_raw)
                for c in self.store.list_credenciais(username):
                    if c.fingerprint == fp:
                        raise JaExiste(_("key already registered for {u} ({fp})").format(u=repr(username), fp=fp))
                self.store.save_credencial(
                    CredencialSSH(
                        username=username, chave_publica=canonica, fingerprint=fp
                    )
                )
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def revogar_chave(self, fingerprint: str) -> Operacao:
        """Mark the credential identified by `fingerprint` as `REVOGADA`.

        Looks the credential up across all users by fingerprint alone; the
        caller does not need to know which user it belongs to.
        """
        op = self._nova_op(f"user key revoke {fingerprint}")
        try:
            with self.store:
                cred = self.store.get_credencial_por_fingerprint(fingerprint)
                if not cred:
                    raise NaoExiste(_("fingerprint {fp} does not exist").format(fp=repr(fingerprint)))
                cred.status = StatusCredencial.REVOGADA
                self.store.save_credencial(cred)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def criar_grupo_user(self, nome: str) -> Operacao:
        """Validate and persist a new, empty user-group, failing if the name is malformed or already exists."""
        op = self._nova_op(f"user-group create {nome}")
        try:
            with self.store:
                if not _RE_NOME_GRUPO.match(nome):
                    raise FormatoInvalido(_("invalid group name: {n}").format(n=repr(nome)))
                if self.store.get_grupo_user(nome):
                    raise JaExiste(_("user-group {n} already exists").format(n=repr(nome)))
                self.store.save_grupo_user(GrupoUser(nome=nome))
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def adicionar_membro_grupo_user(self, grupo: str, username: str) -> Operacao:
        """Add a single user to `grupo`; delegates to `adicionar_membros_grupo_user` with a one-element list."""
        return self.adicionar_membros_grupo_user(grupo, [username])

    def adicionar_membros_grupo_user(self, grupo: str, usernames: list[str]) -> Operacao:
        """Add `usernames` to `grupo`, failing if the group or any of the users does not exist.

        Idempotent: reports success without changing anything if every
        requested member is already in the group. Membership is stored
        sorted, so re-running with an overlapping set never changes the
        persisted member order.
        """
        op = self._nova_op(f"user-group add-member {grupo} {' '.join(usernames)}")
        try:
            with self.store:
                g = self.store.get_grupo_user(grupo)
                if not g:
                    raise NaoExiste(_("group {g} does not exist").format(g=repr(grupo)))
                inexistentes = [u for u in usernames if not self.store.get_user(u)]
                if inexistentes:
                    raise NaoExiste(_("unknown users: {u}").format(u=", ".join(inexistentes)))
                membros = set(g.membros)
                membros.update(usernames)
                if membros == set(g.membros):
                    return self._registrar(op, StatusOperacao.SUCESSO)
                g.membros = sorted(membros)
                self.store.save_grupo_user(g)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def remover_membro_grupo_user(self, grupo: str, username: str) -> Operacao:
        """Remove a single user from `grupo`; delegates to `remover_membros_grupo_user` with a one-element list."""
        return self.remover_membros_grupo_user(grupo, [username])

    def remover_membros_grupo_user(self, grupo: str, usernames: list[str]) -> Operacao:
        """Remove `usernames` from `grupo`, failing only if the group itself does not exist.

        Silently ignores names not currently in the group (removal is
        idempotent) and, unlike the add path, does not check that the names
        are known users: membership can only reference users that already
        existed when added, and a name may have since been deleted from the
        store.
        """
        op = self._nova_op(f"user-group remove-member {grupo} {' '.join(usernames)}")
        try:
            with self.store:
                g = self.store.get_grupo_user(grupo)
                if not g:
                    raise NaoExiste(_("group {g} does not exist").format(g=repr(grupo)))
                alvo = set(usernames)
                novos = [m for m in g.membros if m not in alvo]
                if novos == g.membros:
                    return self._registrar(op, StatusOperacao.SUCESSO)
                g.membros = novos
                self.store.save_grupo_user(g)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def excluir_grupo_user(self, nome: str) -> Operacao:
        """Delete `nome`, failing if it does not exist or still has permissions granted to it.

        The permission check exists so deleting a group can never silently
        orphan a `Permissao` that references it; the error message lists
        every blocking permission and the `revoke` command needed to clear
        it (`_msg_permissoes_associadas`).
        """
        op = self._nova_op(f"user-group delete {nome}")
        try:
            with self.store:
                if not self.store.get_grupo_user(nome):
                    raise NaoExiste(f"group '{nome}' does not exist")
                associadas = [p for p in self.store.list_permissoes() if p.grupo_user == nome]
                if associadas:
                    raise EstadoInvalido(_msg_permissoes_associadas("user-group", nome, associadas))
                self.store.delete_grupo_user(nome)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def cadastrar_servidor(
        self,
        hostname: str,
        ipv4: str,
        porta: int,
        host_key: str,
    ) -> Operacao:
        """Validate and persist a new server, failing if the hostname/IPv4/port/host key is malformed or the hostname is already registered."""
        op = self._nova_op(f"server add {hostname}")
        try:
            with self.store:
                if not _RE_HOSTNAME.match(hostname):
                    raise FormatoInvalido(_("invalid hostname: {h}").format(h=repr(hostname)))
                if not _ipv4_valido(ipv4):
                    raise FormatoInvalido(_("invalid ipv4: {ip}").format(ip=repr(ipv4)))
                if not (1 <= porta <= 65535):
                    raise FormatoInvalido(_("invalid port: {p}").format(p=porta))
                if not host_key.strip():
                    raise FormatoInvalido(_("host_key is required"))
                if self.store.get_servidor(hostname):
                    raise JaExiste(_("server {h} already exists").format(h=repr(hostname)))
                self.store.save_servidor(
                    Servidor(
                        hostname=hostname,
                        ipv4=ipv4,
                        porta_ssh=porta,
                        chave_host=host_key.strip(),
                    )
                )
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def excluir_servidor(self, hostname: str) -> Operacao:
        """Delete `hostname` and remove it from every server-group that lists it as a member.

        Unlike `excluir_grupo_user`/`excluir_grupo_servidor`, this does not
        block on associated permissions: permissions reference server-groups,
        not individual servers, so removing a server just shrinks the groups
        it belonged to instead of leaving a dangling reference.
        """
        op = self._nova_op(f"server remove {hostname}")
        try:
            with self.store:
                if not self.store.get_servidor(hostname):
                    raise NaoExiste(_("server {h} does not exist").format(h=repr(hostname)))
                for g in self.store.list_grupos_servidor():
                    if hostname in g.membros:
                        g.membros = [m for m in g.membros if m != hostname]
                        self.store.save_grupo_servidor(g)
                self.store.delete_servidor(hostname)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def criar_grupo_servidor(self, nome: str) -> Operacao:
        """Validate and persist a new, empty server-group, failing if the name is malformed or already exists."""
        op = self._nova_op(f"server-group create {nome}")
        try:
            with self.store:
                if not _RE_NOME_GRUPO.match(nome):
                    raise FormatoInvalido(_("invalid group name: {n}").format(n=repr(nome)))
                if self.store.get_grupo_servidor(nome):
                    raise JaExiste(_("server-group {n} already exists").format(n=repr(nome)))
                self.store.save_grupo_servidor(GrupoServidor(nome=nome))
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def adicionar_membro_grupo_servidor(self, grupo: str, hostname: str) -> Operacao:
        """Add a single server to `grupo`; delegates to `adicionar_membros_grupo_servidor` with a one-element list."""
        return self.adicionar_membros_grupo_servidor(grupo, [hostname])

    def adicionar_membros_grupo_servidor(self, grupo: str, hostnames: list[str]) -> Operacao:
        """Add `hostnames` to `grupo`, failing if the group or any of the servers does not exist.

        Idempotent no-op if every hostname is already a member; membership is
        stored sorted, mirroring `adicionar_membros_grupo_user`.
        """
        op = self._nova_op(f"server-group add-member {grupo} {' '.join(hostnames)}")
        try:
            with self.store:
                g = self.store.get_grupo_servidor(grupo)
                if not g:
                    raise NaoExiste(_("group {g} does not exist").format(g=repr(grupo)))
                inexistentes = [h for h in hostnames if not self.store.get_servidor(h)]
                if inexistentes:
                    raise NaoExiste(_("unknown servers: {s}").format(s=", ".join(inexistentes)))
                membros = set(g.membros)
                membros.update(hostnames)
                if membros == set(g.membros):
                    return self._registrar(op, StatusOperacao.SUCESSO)
                g.membros = sorted(membros)
                self.store.save_grupo_servidor(g)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def remover_membro_grupo_servidor(self, grupo: str, hostname: str) -> Operacao:
        """Remove a single server from `grupo`; delegates to `remover_membros_grupo_servidor` with a one-element list."""
        return self.remover_membros_grupo_servidor(grupo, [hostname])

    def remover_membros_grupo_servidor(self, grupo: str, hostnames: list[str]) -> Operacao:
        """Remove `hostnames` from `grupo`, failing only if the group itself does not exist; mirrors `remover_membros_grupo_user`."""
        op = self._nova_op(f"server-group remove-member {grupo} {' '.join(hostnames)}")
        try:
            with self.store:
                g = self.store.get_grupo_servidor(grupo)
                if not g:
                    raise NaoExiste(_("group {g} does not exist").format(g=repr(grupo)))
                alvo = set(hostnames)
                novos = [m for m in g.membros if m not in alvo]
                if novos == g.membros:
                    return self._registrar(op, StatusOperacao.SUCESSO)
                g.membros = novos
                self.store.save_grupo_servidor(g)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def excluir_grupo_servidor(self, nome: str) -> Operacao:
        """Delete `nome`, failing if it does not exist or still has permissions granted to it; mirrors `excluir_grupo_user`."""
        op = self._nova_op(f"server-group delete {nome}")
        try:
            with self.store:
                if not self.store.get_grupo_servidor(nome):
                    raise NaoExiste(f"group '{nome}' does not exist")
                associadas = [p for p in self.store.list_permissoes() if p.grupo_servidor == nome]
                if associadas:
                    raise EstadoInvalido(_msg_permissoes_associadas("server-group", nome, associadas))
                self.store.delete_grupo_servidor(nome)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def conceder(
        self,
        grupo_user: str,
        grupo_servidor: str,
        nivel: NivelPermissao,
        profile: str | None = None,
    ) -> Operacao:
        """Grant `nivel` access from `grupo_user` to `grupo_servidor`, optionally scoped to a sudo `profile`.

        Validates that both groups exist, that `profile` is only supplied
        when `nivel` is `SUDO`, and that a supplied profile actually exists
        in the store. Overwrites any existing permission for the same
        (user-group, server-group) pair rather than failing, since a
        permission is keyed on that pair and re-granting is how it is
        updated.
        """
        comando = f"permission grant {grupo_user} {grupo_servidor} --level {nivel.value}"
        if profile:
            comando += f" --profile {profile}"
        op = self._nova_op(comando)
        try:
            with self.store:
                if not self.store.get_grupo_user(grupo_user):
                    raise NaoExiste(_("user-group {g} does not exist").format(g=repr(grupo_user)))
                if not self.store.get_grupo_servidor(grupo_servidor):
                    raise NaoExiste(_("server-group {g} does not exist").format(g=repr(grupo_servidor)))
                if profile is not None:
                    if nivel != NivelPermissao.SUDO:
                        raise FormatoInvalido(_("--profile only applies when --level is sudo"))
                    if not self.store.get_sudo_profile(profile):
                        raise NaoExiste(_("sudo-profile {n} does not exist").format(n=repr(profile)))
                self.store.save_permissao(
                    Permissao(
                        grupo_user=grupo_user,
                        grupo_servidor=grupo_servidor,
                        nivel=nivel,
                        profile=profile,
                    )
                )
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def criar_sudo_profile(self, nome: str, comandos: list[str]) -> Operacao:
        """Validate and persist a new sudo command profile, failing on a malformed name, an empty command list, or a non-absolute or control-character-bearing command.

        The control-character check exists specifically to stop sudoers rule
        injection: `visudo -c` validates syntax but does not distinguish one
        sudoers line from two, so a command smuggling in an embedded
        `\\n`/`\\r`/NUL could otherwise add a second, attacker-controlled
        rule while still passing validation.
        """
        op = self._nova_op(f"sudo-profile create {nome}")
        try:
            with self.store:
                if not _RE_NOME_GRUPO.match(nome):
                    raise FormatoInvalido(_("invalid sudo-profile name: {n}").format(n=repr(nome)))
                if not comandos:
                    raise FormatoInvalido(_("at least one --command is required"))
                for c in comandos:
                    if not c.startswith("/"):
                        raise FormatoInvalido(_("command must be absolute path: {c} (sudoers requires absolute paths)").format(c=repr(c)))
                    # Bloqueia injection de novas regras no sudoers via newline/CR.
                    # 'visudo -c' valida sintaxe mas nao distingue 1 regra com \n vs 2 regras
                    # legitimas; basta uma das linhas ser valida pra passar.
                    if any(ch in c for ch in ("\n", "\r", "\x00")):
                        raise FormatoInvalido(_("command contains forbidden control character: {c}").format(c=repr(c)))
                if self.store.get_sudo_profile(nome):
                    raise JaExiste(_("sudo-profile {n} already exists").format(n=repr(nome)))
                self.store.save_sudo_profile(SudoProfile(nome=nome, comandos=list(comandos)))
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def excluir_sudo_profile(self, nome: str) -> Operacao:
        """Delete `nome`, failing if it does not exist or is still referenced by a permission.

        Mirrors the group-deletion guards: a profile in use is never deleted
        by silently nulling out the permissions that reference it, since that
        would promote them to unrestricted sudo instead of failing loudly.
        """
        op = self._nova_op(f"sudo-profile delete {nome}")
        try:
            with self.store:
                if not self.store.get_sudo_profile(nome):
                    raise NaoExiste(f"sudo-profile '{nome}' does not exist")
                em_uso = [
                    p for p in self.store.list_permissoes() if p.profile == nome
                ]
                if em_uso:
                    raise EstadoInvalido(_("sudo-profile {n} is in use by {k} permission(s); update or revoke them first").format(n=repr(nome), k=len(em_uso)))
                self.store.delete_sudo_profile(nome)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def revogar(self, grupo_user: str, grupo_servidor: str) -> Operacao:
        """Delete the permission for the (`grupo_user`, `grupo_servidor`) pair, failing with a friendly error if it does not exist.

        Catches `FileNotFoundError` specifically (raised by the store when
        the pair has no permission) and reports it as a normal `Operacao`
        failure rather than letting it propagate as an unrelated I/O error.
        """
        op = self._nova_op(f"permission revoke {grupo_user} {grupo_servidor}")
        try:
            with self.store:
                self.store.delete_permissao(grupo_user, grupo_servidor)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except FileNotFoundError:
            return self._registrar_falha(op, _("permission does not exist"))
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def preview(self, force: bool = False, reconcile: bool = False) -> list[Subacao]:
        """Compute the pending `Subacao` list without applying it -- the "is anything pending?" check the paper measures.

        With `reconcile=True`, compares desired state against the real state
        fetched live over SSH (`_atual_vivo`); otherwise the comparison is
        entirely against the state already persisted in `JsonStore`
        (`chaves_instaladas`, last written by `aplicar`), so no host is
        contacted and the check stays fast regardless of fleet size. `force`
        is passed through to `Planner.calcular_delta` to treat every desired
        credential as if nothing were installed.
        """
        if reconcile:
            return self.planner.calcular_delta(atual_override=self._atual_vivo())
        return self.planner.calcular_delta(force=force)

    def _atual_vivo(self) -> dict[str, dict]:
        """Estado real por servidor ({host: {ref: ChaveInstalada}}) via SSH, para o
        planner usar como 'atual' no --reconcile."""
        from adminforge import authorized_keys as ak
        from adminforge.planner.planner import ChaveInstalada

        prefixo = "adminforge-"
        desejado = self.planner.estado_desejado()
        out: dict[str, dict[str, ChaveInstalada]] = {}
        for servidor in self.store.list_servidores():
            alvo = desejado.get(servidor.hostname, {})
            if not alvo:
                continue
            rel = self.deployer.inspecionar(servidor)
            ok_rel = isinstance(rel, dict) and "erro" not in rel
            real_users = {u["nome"] for u in rel.get("usuarios", [])} if ok_rel else set()
            sudo_users = {a["nome"][len(prefixo):] for a in rel.get("sudoers_arquivos", [])
                          if a.get("adminforge") and a.get("nome", "").startswith(prefixo)}
            atual: dict[str, ChaveInstalada] = {}
            for username in sorted({ci.username for ci in alvo.values()}):
                if username not in real_users:
                    continue
                conteudo, ok = self.deployer.ler_authorized_keys(servidor, username)
                if not ok:
                    continue
                nivel = NivelPermissao.SUDO if username in sudo_users else NivelPermissao.SHELL
                for ref in ak.parse_blocos(conteudo):
                    atual[ref] = ChaveInstalada(ref=ref, username=username, nivel=nivel)
            out[servidor.hostname] = atual
        return out

    def aplicar(
        self,
        jobs: int = 1,
        force: bool = False,
        reconcile: bool = False,
        subacoes: list[Subacao] | None = None,
    ) -> Operacao:
        """Compute (or accept) the pending subactions and apply them to each host, updating the persisted installed-keys state.

        Computes the delta the same way `preview` does unless `subacoes` is
        supplied by the caller, so a previously computed preview can be
        re-applied without recomputing it. Deployment is grouped per host
        and, when `jobs > 1` and more than one host has work, fanned out over
        a bounded `ThreadPoolExecutor` -- this is the step whose cost the
        paper claims is linear per host, since each host's SSH round-trip is
        independent, and the `Store` update that follows stays serial and
        deterministic regardless of `jobs`, so the persisted result is
        identical whether hosts were applied in parallel or not. A host
        removed from the store between planning and apply is reported as a
        failed subaction rather than raising, so a partially stale plan
        degrades to `SUCESSO_PARCIAL` instead of aborting the whole run.
        """
        op = self._nova_op("apply")
        try:
            with self.store:
                if subacoes is None:
                    if reconcile:
                        subacoes = self.planner.calcular_delta(atual_override=self._atual_vivo())
                    else:
                        subacoes = self.planner.calcular_delta(force=force)
                if not subacoes:
                    return self._registrar(op, StatusOperacao.SUCESSO)

                por_servidor: dict[str, list[Subacao]] = {}
                for s in subacoes:
                    por_servidor.setdefault(s.servidor, []).append(s)

                from adminforge.planner.planner import ChaveInstalada

                # Resolve each host's target state once, in a deterministic order.
                hostnames = list(por_servidor)
                servidores = {h: self.store.get_servidor(h) for h in hostnames}

                # The SSH work (deployer.aplicar) is independent per host and is
                # the wall-clock cost; run it with a bounded thread pool when
                # jobs > 1. The Store update below stays serial and ordered, so
                # the result is identical regardless of jobs. ThreadPoolExecutor
                # is part of the standard library, preserving the zero-dependency
                # runtime.
                pendentes = {h: lote for h, lote in por_servidor.items() if servidores[h] is not None}
                if jobs > 1 and len(pendentes) > 1:
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor(max_workers=min(jobs, len(pendentes))) as pool:
                        resultados = dict(zip(
                            pendentes,
                            pool.map(lambda h: self.deployer.aplicar(servidores[h], pendentes[h]), pendentes),
                        ))
                else:
                    resultados = {h: self.deployer.aplicar(servidores[h], lote) for h, lote in pendentes.items()}

                for hostname, lote in por_servidor.items():
                    servidor = servidores[hostname]
                    if servidor is None:
                        for s in lote:
                            s.status = "falha"
                            s.erro = _("server {h} does not exist").format(h=repr(hostname))
                        op.subacoes.extend(lote)
                        continue

                    aplicadas = resultados[hostname]
                    op.subacoes.extend(aplicadas)

                    instaladas = {
                        ci.ref: ci
                        for ci in (
                            ChaveInstalada.de_dict(item) if isinstance(item, dict)
                            else ChaveInstalada(
                                ref=item,
                                username=item.split(":", 1)[0],
                                nivel=NivelPermissao.SHELL,
                            )
                            for item in servidor.chaves_instaladas
                        )
                    }
                    for s in aplicadas:
                        if s.status != "sucesso" or s.credencial is None:
                            continue
                        if s.acao == TipoAcao.ADICIONAR_CHAVE:
                            instaladas[s.credencial] = ChaveInstalada(
                                ref=s.credencial,
                                username=s.username or "",
                                nivel=s.nivel or NivelPermissao.SHELL,
                                profile=s.profile,
                            )
                        elif s.acao == TipoAcao.REMOVER_CHAVE:
                            instaladas.pop(s.credencial, None)
                    servidor.chaves_instaladas = [c.para_dict() for c in instaladas.values()]
                    self.store.save_servidor(servidor)

                sucessos = sum(1 for s in op.subacoes if s.status == "sucesso")
                total = len(op.subacoes)
                if sucessos == total:
                    status = StatusOperacao.SUCESSO
                elif sucessos == 0:
                    status = StatusOperacao.FALHA
                else:
                    status = StatusOperacao.SUCESSO_PARCIAL
                return self._registrar(op, status)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    # ---------------------------------------------------------------------------
    # Edits / renames
    # ---------------------------------------------------------------------------
    def editar_user(self, username: str, nome: str | None = None, email: str | None = None) -> Operacao:
        """Update `nome` and/or `email` on an existing user, validating whichever fields are supplied; fields left as `None` are unchanged."""
        op = self._nova_op(f"user edit {username}")
        try:
            with self.store:
                user = self.store.get_user(username)
                if not user:
                    raise NaoExiste(_("user {u} does not exist").format(u=repr(username)))
                if nome is not None:
                    if not nome.strip():
                        raise FormatoInvalido(_("name is required"))
                    user.nome = nome
                if email is not None:
                    if not _RE_EMAIL.match(email):
                        raise FormatoInvalido(_("invalid email: {e}").format(e=repr(email)))
                    user.email = email
                self.store.save_user(user)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def renomear_user(self, de: str, para: str) -> Operacao:
        """Rename a user from `de` to `para` and update their membership in every user-group.

        No-op success if `de == para`. Fails if `para` is invalid or already
        taken, or if `de` does not exist.
        """
        op = self._nova_op(f"user rename {de} -> {para}")
        try:
            with self.store:
                if de == para:
                    return self._registrar(op, StatusOperacao.SUCESSO)
                if not _RE_USERNAME.match(para):
                    raise FormatoInvalido(_("invalid username: {u}").format(u=repr(para)))
                if not self.store.get_user(de):
                    raise NaoExiste(_("user {u} does not exist").format(u=repr(de)))
                if self.store.get_user(para):
                    raise JaExiste(_("username {u} already exists").format(u=repr(para)))
                self.store.rename_user(de, para)
                for g in self.store.list_grupos_user():
                    if de in g.membros:
                        g.membros = [para if m == de else m for m in g.membros]
                        self.store.save_grupo_user(g)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def editar_servidor(
        self,
        hostname: str,
        ipv4: str | None = None,
        porta: int | None = None,
        chave_host: str | None = None,
    ) -> Operacao:
        """Update `ipv4`, `porta` and/or `chave_host` on an existing server, validating whichever fields are supplied; fields left as `None` are unchanged."""
        op = self._nova_op(f"server edit {hostname}")
        try:
            with self.store:
                servidor = self.store.get_servidor(hostname)
                if not servidor:
                    raise NaoExiste(_("server {h} does not exist").format(h=repr(hostname)))
                if ipv4 is not None:
                    if not _ipv4_valido(ipv4):
                        raise FormatoInvalido(_("invalid ipv4: {ip}").format(ip=repr(ipv4)))
                    servidor.ipv4 = ipv4
                if porta is not None:
                    if not (1 <= porta <= 65535):
                        raise FormatoInvalido(_("invalid port: {p}").format(p=porta))
                    servidor.porta_ssh = porta
                if chave_host is not None:
                    if not chave_host.strip():
                        raise FormatoInvalido(_("host_key is required"))
                    servidor.chave_host = chave_host.strip()
                self.store.save_servidor(servidor)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def renomear_servidor(self, de: str, para: str) -> Operacao:
        """Rename a server from `de` to `para` and update its membership in every server-group; mirrors `renomear_user`."""
        op = self._nova_op(f"server rename {de} -> {para}")
        try:
            with self.store:
                if de == para:
                    return self._registrar(op, StatusOperacao.SUCESSO)
                if not _RE_HOSTNAME.match(para):
                    raise FormatoInvalido(_("invalid hostname: {h}").format(h=repr(para)))
                if not self.store.get_servidor(de):
                    raise NaoExiste(_("server {h} does not exist").format(h=repr(de)))
                if self.store.get_servidor(para):
                    raise JaExiste(_("server {h} already exists").format(h=repr(para)))
                self.store.rename_servidor(de, para)
                for g in self.store.list_grupos_servidor():
                    if de in g.membros:
                        g.membros = [para if m == de else m for m in g.membros]
                        self.store.save_grupo_servidor(g)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def _renomear_grupo(
        self,
        tipo: str,
        de: str,
        para: str,
        get,
        rename,
        atualizar_permissao,
    ) -> Operacao:
        """Shared rename implementation for user-groups and server-groups: validate, rename via `rename`, and repoint every `Permissao` that referenced the old name.

        `get`/`rename` are the store accessors for the specific group kind
        being renamed; `atualizar_permissao` is a callback that mutates a
        `Permissao` in place if it references `de`, so the same generic pass
        over `self.store.list_permissoes()` works for both user-groups
        (matching `grupo_user`) and server-groups (matching
        `grupo_servidor`). `tipo` is used only for the command string and
        error messages.
        """
        op = self._nova_op(f"{tipo} rename {de} -> {para}")
        try:
            with self.store:
                if de == para:
                    return self._registrar(op, StatusOperacao.SUCESSO)
                if not _RE_NOME_GRUPO.match(para):
                    raise FormatoInvalido(_("invalid group name: {n}").format(n=repr(para)))
                if not get(de):
                    raise NaoExiste(_("{kind} {n} does not exist").format(kind=tipo, n=repr(de)))
                if get(para):
                    raise JaExiste(_("{kind} {n} already exists").format(kind=tipo, n=repr(para)))
                rename(de, para)
                perms = self.store.list_permissoes()
                for p in perms:
                    atualizar_permissao(p, de, para)
                self.store.replace_permissoes(perms)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def renomear_grupo_user(self, de: str, para: str) -> Operacao:
        """Rename a user-group from `de` to `para`, repointing permissions via `_renomear_grupo`."""
        def _swap(p, antigo, novo):
            """Repoint `p.grupo_user` to `novo` in place if it currently references `antigo`."""
            if p.grupo_user == antigo:
                p.grupo_user = novo
        return self._renomear_grupo(
            "user-group", de, para,
            self.store.get_grupo_user, self.store.rename_grupo_user, _swap,
        )

    def renomear_grupo_servidor(self, de: str, para: str) -> Operacao:
        """Rename a server-group from `de` to `para`, repointing permissions via `_renomear_grupo`."""
        def _swap(p, antigo, novo):
            """Repoint `p.grupo_servidor` to `novo` in place if it currently references `antigo`."""
            if p.grupo_servidor == antigo:
                p.grupo_servidor = novo
        return self._renomear_grupo(
            "server-group", de, para,
            self.store.get_grupo_servidor, self.store.rename_grupo_servidor, _swap,
        )

    def renomear_sudo_profile(self, de: str, para: str) -> Operacao:
        """Rename a sudo-profile from `de` to `para` and repoint every `Permissao.profile` that referenced the old name.

        Does not reuse `_renomear_grupo` because a sudo-profile is not a
        group with membership.
        """
        op = self._nova_op(f"sudo-profile rename {de} -> {para}")
        try:
            with self.store:
                if de == para:
                    return self._registrar(op, StatusOperacao.SUCESSO)
                if not _RE_NOME_GRUPO.match(para):
                    raise FormatoInvalido(_("invalid sudo-profile name: {n}").format(n=repr(para)))
                if not self.store.get_sudo_profile(de):
                    raise NaoExiste(_("sudo-profile {n} does not exist").format(n=repr(de)))
                if self.store.get_sudo_profile(para):
                    raise JaExiste(_("sudo-profile {n} already exists").format(n=repr(para)))
                self.store.rename_sudo_profile(de, para)
                perms = self.store.list_permissoes()
                for p in perms:
                    if p.profile == de:
                        p.profile = para
                self.store.replace_permissoes(perms)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def auditar_servidor(self, hostname: str) -> tuple[Operacao, dict]:
        """Inspect `hostname` live over SSH and return both the resulting `Operacao` and the raw report from `deployer.inspecionar`.

        Unlike the other command methods, this does not open a `JsonStore`
        transaction (`with self.store:`): it only reads the store via
        `get_servidor` and never persists anything, so no transaction is
        needed. On failure it also returns the exception as a dict with an
        `"erro"` key, not just the failed `Operacao`, since the caller needs
        a report shape even when inspection could not run.
        """
        op = self._nova_op(f"audit server {hostname}")
        try:
            servidor = self.store.get_servidor(hostname)
            if not servidor:
                raise NaoExiste(_("server {h} does not exist").format(h=repr(hostname)))
            relatorio = self.deployer.inspecionar(servidor)
            sub = Subacao(
                servidor=hostname,
                acao=TipoAcao.LEITURA,
                status="sucesso" if "erro" not in relatorio else "falha",
                erro=relatorio.get("erro"),
                mensagem=_("{u} users, {g} groups, {s} services, {r} sudo rules").format(u=len(relatorio.get("usuarios", [])), g=len(relatorio.get("grupos", [])), s=len(relatorio.get("servicos", [])), r=len(relatorio.get("sudoers_regras", []))),
            )
            op.subacoes.append(sub)
            status = StatusOperacao.SUCESSO if "erro" not in relatorio else StatusOperacao.FALHA
            self._registrar(op, status)
            return op, relatorio
        except Exception as e:
            return self._registrar_falha(op, str(e)), {"erro": str(e)}
