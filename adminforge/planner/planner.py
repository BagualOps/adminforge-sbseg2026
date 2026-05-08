from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from adminforge.domain import (
    NivelPermissao,
    StatusCredencial,
    StatusUser,
    Subacao,
    TipoAcao,
)
from adminforge.exceptions import EstadoInvalido
from adminforge.interfaces.store import IStore


_PRIORIDADE = {NivelPermissao.SHELL: 1, NivelPermissao.SUDO: 2}


def _maior(a: NivelPermissao, b: NivelPermissao) -> NivelPermissao:
    return a if _PRIORIDADE[a] >= _PRIORIDADE[b] else b


def _merge_profile(
    existente: "ChaveInstalada | None",
    perm_nivel: NivelPermissao,
    perm_profile: str | None,
    nivel_final: NivelPermissao,
) -> str | None:
    """Calcula o profile efetivo ao mesclar uma nova permissao na ChaveInstalada existente.

    Regras (validadas por testes parametrizados):
      - nivel_final != SUDO              -> None (profile nao se aplica a SHELL)
      - existente is None                -> profile do entrante
      - existente era SHELL              -> profile do entrante (entrante eh SUDO)
      - entrante eh SHELL                -> mantem profile do existente SUDO
      - ambos SUDO, algum sem profile    -> None (full sudo prevalece, menor restricao)
      - ambos SUDO com profile           -> mantem o profile do existente (estavel)
    """
    if nivel_final != NivelPermissao.SUDO:
        return None
    if existente is None:
        return perm_profile
    if existente.nivel != NivelPermissao.SUDO:
        return perm_profile
    if perm_nivel != NivelPermissao.SUDO:
        return existente.profile
    if existente.profile is None or perm_profile is None:
        return None
    return existente.profile


@dataclass(frozen=True)
class ChaveInstalada:
    ref: str
    username: str
    nivel: NivelPermissao
    profile: str | None = None

    @classmethod
    def de_dict(cls, d: dict) -> "ChaveInstalada":
        return cls(
            ref=d["ref"],
            username=d.get("username") or d["ref"].split(":", 1)[0],
            nivel=NivelPermissao(d.get("nivel", "shell")),
            profile=d.get("profile"),
        )

    def para_dict(self) -> dict:
        out = {"ref": self.ref, "username": self.username, "nivel": self.nivel.value}
        if self.profile is not None:
            out["profile"] = self.profile
        return out


class Planner:
    def __init__(self, store: IStore):
        self.store = store

    def estado_desejado(self) -> dict[str, dict[str, ChaveInstalada]]:
        users = {u.username: u for u in self.store.list_users() if u.status == StatusUser.ATIVO}
        creds_por_user = {
            u: [c for c in self.store.list_credenciais(u) if c.status == StatusCredencial.ATIVA]
            for u in users
        }
        grupos_user = {g.nome: g for g in self.store.list_grupos_user()}
        grupos_servidor = {g.nome: g for g in self.store.list_grupos_servidor()}
        servidores_validos = {s.hostname for s in self.store.list_servidores()}

        desejado: dict[str, dict[str, ChaveInstalada]] = defaultdict(dict)
        for perm in self.store.list_permissoes():
            gu = grupos_user.get(perm.grupo_user)
            gs = grupos_servidor.get(perm.grupo_servidor)
            if not gu or not gs:
                continue
            for username in gu.membros:
                if username not in users:
                    continue
                for cred in creds_por_user.get(username, []):
                    ref = cred.referencia
                    for hostname in gs.membros:
                        if hostname not in servidores_validos:
                            continue
                        existente = desejado[hostname].get(ref)
                        nivel = perm.nivel if existente is None else _maior(existente.nivel, perm.nivel)
                        profile = _merge_profile(existente, perm.nivel, perm.profile, nivel)
                        desejado[hostname][ref] = ChaveInstalada(
                            ref=ref, username=username, nivel=nivel, profile=profile
                        )
        return desejado

    def calcular_delta(self) -> list[Subacao]:
        desejado = self.estado_desejado()
        subacoes: list[Subacao] = []

        # cache de profiles para evitar reler a cada subaction
        profiles_cache: dict[str, list[str] | None] = {}

        def _comandos(profile: str | None) -> list[str] | None:
            """None  = sem profile (NOPASSWD:ALL legítimo).
            Lista nao-vazia = perfil resolvido.
            Lanca EstadoInvalido se profile referenciado nao existe ou esta vazio
            (evita virar full sudo silenciosamente)."""
            if profile is None:
                return None
            if profile not in profiles_cache:
                p = self.store.get_sudo_profile(profile)
                profiles_cache[profile] = list(p.comandos) if p else None
            comandos = profiles_cache[profile]
            if comandos is None:
                raise EstadoInvalido(
                    f"sudo-profile '{profile}' referenced but not found in state"
                )
            if not comandos:
                raise EstadoInvalido(
                    f"sudo-profile '{profile}' has no commands; refusing to apply"
                )
            return comandos

        for servidor in self.store.list_servidores():
            atual = {}
            for item in servidor.chaves_instaladas:
                if isinstance(item, str):
                    ch = ChaveInstalada(
                        ref=item,
                        username=item.split(":", 1)[0],
                        nivel=NivelPermissao.SHELL,
                    )
                else:
                    ch = ChaveInstalada.de_dict(item)
                atual[ch.ref] = ch

            alvo = desejado.get(servidor.hostname, {})

            for ref, esperado in alvo.items():
                cred = self.store.get_credencial_por_fingerprint(esperado.ref.split(":", 1)[1])
                chave_publica = cred.chave_publica if cred else ""
                instalado = atual.get(ref)
                divergente = (
                    instalado is None
                    or instalado.nivel != esperado.nivel
                    or instalado.profile != esperado.profile
                )
                if divergente:
                    subacoes.append(
                        Subacao(
                            servidor=servidor.hostname,
                            acao=TipoAcao.ADICIONAR_CHAVE,
                            credencial=ref,
                            chave_publica=chave_publica,
                            username=esperado.username,
                            nivel=esperado.nivel,
                            profile=esperado.profile,
                            profile_comandos=_comandos(esperado.profile),
                        )
                    )

            for ref, instalado in atual.items():
                if ref not in alvo:
                    subacoes.append(
                        Subacao(
                            servidor=servidor.hostname,
                            acao=TipoAcao.REMOVER_CHAVE,
                            credencial=ref,
                            username=instalado.username,
                            nivel=instalado.nivel,
                        )
                    )

        subacoes.sort(key=lambda s: (s.servidor, s.acao.value, s.credencial or ""))
        return subacoes
