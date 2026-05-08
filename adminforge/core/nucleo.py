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
    TipoAcao,
    User,
)
from adminforge.exceptions import (
    EstadoInvalido,
    FormatoInvalido,
    JaExiste,
    NaoExiste,
)
from adminforge.interfaces.deployer import IDeployer
from adminforge.planner.planner import Planner
from adminforge.store.json_store import JsonStore

_RE_USERNAME = re.compile(r"^[a-z_][a-z0-9_-]{0,30}$")
_RE_HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")
_RE_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_RE_NOME_GRUPO = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")
_RE_IPV4 = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


class Nucleo:
    def __init__(
        self,
        store: JsonStore,
        auditor: JsonlAuditor,
        deployer: IDeployer | None = None,
        superadmin: str = "desconhecido",
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
        superadmin: str = "desconhecido",
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
                    raise FormatoInvalido(f"username invalido: '{username}'")
                if not nome.strip():
                    raise FormatoInvalido("nome obrigatorio")
                if not _RE_EMAIL.match(email):
                    raise FormatoInvalido(f"email invalido: '{email}'")
                if self.store.get_user(username):
                    raise JaExiste(f"username '{username}' ja existe")
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
                    raise NaoExiste(f"user '{username}' nao existe")
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
                    raise NaoExiste(f"user '{username}' nao existe")
                fp = ssh_keys.fingerprint(chave_raw)
                canonica = ssh_keys.chave_canonica(chave_raw)
                for c in self.store.list_credenciais(username):
                    if c.fingerprint == fp:
                        raise JaExiste(f"chave ja cadastrada para '{username}' ({fp})")
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
                    raise NaoExiste(f"fingerprint '{fingerprint}' nao existe")
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
                    raise FormatoInvalido(f"nome de grupo invalido: '{nome}'")
                if self.store.get_grupo_user(nome):
                    raise JaExiste(f"grupo de user '{nome}' ja existe")
                self.store.save_grupo_user(GrupoUser(nome=nome))
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def adicionar_membro_grupo_user(self, grupo: str, username: str) -> Operacao:
        op = self._nova_op(f"user-group add-member {grupo} {username}")
        try:
            with self.store:
                g = self.store.get_grupo_user(grupo)
                if not g:
                    raise NaoExiste(f"grupo '{grupo}' nao existe")
                if not self.store.get_user(username):
                    raise NaoExiste(f"user '{username}' nao existe")
                if username in g.membros:
                    return self._registrar(op, StatusOperacao.SUCESSO)
                g.membros = sorted({*g.membros, username})
                self.store.save_grupo_user(g)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def remover_membro_grupo_user(self, grupo: str, username: str) -> Operacao:
        op = self._nova_op(f"user-group remove-member {grupo} {username}")
        try:
            with self.store:
                g = self.store.get_grupo_user(grupo)
                if not g:
                    raise NaoExiste(f"grupo '{grupo}' nao existe")
                if username not in g.membros:
                    return self._registrar(op, StatusOperacao.SUCESSO)
                g.membros = [m for m in g.membros if m != username]
                self.store.save_grupo_user(g)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def excluir_grupo_user(self, nome: str) -> Operacao:
        op = self._nova_op(f"user-group delete {nome}")
        try:
            with self.store:
                if not self.store.get_grupo_user(nome):
                    raise NaoExiste(f"grupo '{nome}' nao existe")
                if any(p.grupo_user == nome for p in self.store.list_permissoes()):
                    raise EstadoInvalido(
                        f"grupo '{nome}' tem permissoes associadas; revogue antes"
                    )
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
                    raise FormatoInvalido(f"hostname invalido: '{hostname}'")
                if not _RE_IPV4.match(ipv4):
                    raise FormatoInvalido(f"ipv4 invalido: '{ipv4}'")
                if not (1 <= porta <= 65535):
                    raise FormatoInvalido(f"porta invalida: {porta}")
                if not host_key.strip():
                    raise FormatoInvalido("host_key obrigatoria")
                if self.store.get_servidor(hostname):
                    raise JaExiste(f"servidor '{hostname}' ja existe")
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
                    raise NaoExiste(f"servidor '{hostname}' nao existe")
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
                    raise FormatoInvalido(f"nome de grupo invalido: '{nome}'")
                if self.store.get_grupo_servidor(nome):
                    raise JaExiste(f"grupo de servidor '{nome}' ja existe")
                self.store.save_grupo_servidor(GrupoServidor(nome=nome))
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def adicionar_membro_grupo_servidor(self, grupo: str, hostname: str) -> Operacao:
        op = self._nova_op(f"server-group add-member {grupo} {hostname}")
        try:
            with self.store:
                g = self.store.get_grupo_servidor(grupo)
                if not g:
                    raise NaoExiste(f"grupo '{grupo}' nao existe")
                if not self.store.get_servidor(hostname):
                    raise NaoExiste(f"servidor '{hostname}' nao existe")
                if hostname in g.membros:
                    return self._registrar(op, StatusOperacao.SUCESSO)
                g.membros = sorted({*g.membros, hostname})
                self.store.save_grupo_servidor(g)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def remover_membro_grupo_servidor(self, grupo: str, hostname: str) -> Operacao:
        op = self._nova_op(f"server-group remove-member {grupo} {hostname}")
        try:
            with self.store:
                g = self.store.get_grupo_servidor(grupo)
                if not g:
                    raise NaoExiste(f"grupo '{grupo}' nao existe")
                if hostname not in g.membros:
                    return self._registrar(op, StatusOperacao.SUCESSO)
                g.membros = [m for m in g.membros if m != hostname]
                self.store.save_grupo_servidor(g)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def excluir_grupo_servidor(self, nome: str) -> Operacao:
        op = self._nova_op(f"server-group delete {nome}")
        try:
            with self.store:
                if not self.store.get_grupo_servidor(nome):
                    raise NaoExiste(f"grupo '{nome}' nao existe")
                if any(p.grupo_servidor == nome for p in self.store.list_permissoes()):
                    raise EstadoInvalido(
                        f"grupo '{nome}' tem permissoes associadas; revogue antes"
                    )
                self.store.delete_grupo_servidor(nome)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def conceder(self, grupo_user: str, grupo_servidor: str, nivel: NivelPermissao) -> Operacao:
        op = self._nova_op(f"grant {grupo_user} {grupo_servidor} --nivel {nivel.value}")
        try:
            with self.store:
                if not self.store.get_grupo_user(grupo_user):
                    raise NaoExiste(f"grupo de user '{grupo_user}' nao existe")
                if not self.store.get_grupo_servidor(grupo_servidor):
                    raise NaoExiste(f"grupo de servidor '{grupo_servidor}' nao existe")
                self.store.save_permissao(
                    Permissao(
                        grupo_user=grupo_user,
                        grupo_servidor=grupo_servidor,
                        nivel=nivel,
                    )
                )
                return self._registrar(op, StatusOperacao.SUCESSO)
        except Exception as e:
            return self._registrar_falha(op, str(e))

    def revogar(self, grupo_user: str, grupo_servidor: str) -> Operacao:
        op = self._nova_op(f"revoke {grupo_user} {grupo_servidor}")
        try:
            with self.store:
                self.store.delete_permissao(grupo_user, grupo_servidor)
                return self._registrar(op, StatusOperacao.SUCESSO)
        except FileNotFoundError:
            return self._registrar_falha(op, "permissao nao existe")
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
                            s.erro = f"servidor '{hostname}' nao existe"
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
                raise NaoExiste(f"servidor '{hostname}' nao existe")
            relatorio = self.deployer.inspecionar(servidor)
            sub = Subacao(
                servidor=hostname,
                acao=TipoAcao.LEITURA,
                status="sucesso" if "erro" not in relatorio else "falha",
                erro=relatorio.get("erro"),
                mensagem=f"{len(relatorio.get('usuarios', []))} usuarios, "
                f"{len(relatorio.get('servicos', []))} servicos",
            )
            op.subacoes.append(sub)
            status = StatusOperacao.SUCESSO if "erro" not in relatorio else StatusOperacao.FALHA
            self._registrar(op, status)
            return op, relatorio
        except Exception as e:
            return self._registrar_falha(op, str(e)), {"erro": str(e)}
