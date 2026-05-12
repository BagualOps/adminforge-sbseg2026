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
    def __init__(
        self,
        store: JsonStore,
        auditor: JsonlAuditor,
        deployer: IDeployer | None = None,
        superadmin: str = "unknown",
    ):
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
        store = JsonStore(state_dir)
        auditor = JsonlAuditor(state_dir / "history.jsonl")
        return cls(store, auditor, deployer, superadmin)

    def _nova_op(self, comando: str) -> Operacao:
        return Operacao(
            id=self.auditor.proximo_id(),
            momento=datetime.now().astimezone(),
            superadmin=self.superadmin,
            comando=comando,
            status=StatusOperacao.EM_ANDAMENTO,
        )

    def _registrar(self, op: Operacao, status: StatusOperacao) -> Operacao:
        op.status = status
        self.auditor.registrar(op)
        return op

    def _registrar_falha(self, op: Operacao, mensagem: str) -> Operacao:
        op.subacoes.append(
            Subacao(servidor="", acao=TipoAcao.LEITURA, status="falha", erro=mensagem)
        )
        return self._registrar(op, StatusOperacao.FALHA)

    def cadastrar_user(self, username: str, nome: str, email: str) -> Operacao:
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
        return self.adicionar_membros_grupo_user(grupo, [username])

    def adicionar_membros_grupo_user(self, grupo: str, usernames: list[str]) -> Operacao:
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
        return self.remover_membros_grupo_user(grupo, [username])

    def remover_membros_grupo_user(self, grupo: str, usernames: list[str]) -> Operacao:
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
        op = self._nova_op(f"server add {hostname}")
        try:
            with self.store:
                if not _RE_HOSTNAME.match(hostname):
                    raise FormatoInvalido(_("invalid hostname: {h}").format(h=repr(hostname)))
                if not _RE_IPV4.match(ipv4):
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
        return self.adicionar_membros_grupo_servidor(grupo, [hostname])

    def adicionar_membros_grupo_servidor(self, grupo: str, hostnames: list[str]) -> Operacao:
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
        return self.remover_membros_grupo_servidor(grupo, [hostname])

    def remover_membros_grupo_servidor(self, grupo: str, hostnames: list[str]) -> Operacao:
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
        op = self._nova_op(f"permission revoke {grupo_user} {grupo_servidor}")
        try:
            with self.store:
                self.store.delete_permissao(grupo_user, grupo_servidor)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except FileNotFoundError:
            return self._registrar_falha(op, _("permission does not exist"))
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def preview(self) -> list[Subacao]:
        return self.planner.calcular_delta()

    def aplicar(self) -> Operacao:
        op = self._nova_op("apply")
        try:
            with self.store:
                subacoes = self.planner.calcular_delta()
                if not subacoes:
                    return self._registrar(op, StatusOperacao.SUCESSO)

                por_servidor: dict[str, list[Subacao]] = {}
                for s in subacoes:
                    por_servidor.setdefault(s.servidor, []).append(s)

                from adminforge.planner.planner import ChaveInstalada

                for hostname, lote in por_servidor.items():
                    servidor = self.store.get_servidor(hostname)
                    if servidor is None:
                        for s in lote:
                            s.status = "falha"
                            s.erro = _("server {h} does not exist").format(h=repr(hostname))
                        op.subacoes.extend(lote)
                        continue

                    aplicadas = self.deployer.aplicar(servidor, lote)
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

    def auditar_servidor(self, hostname: str) -> tuple[Operacao, dict]:
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
