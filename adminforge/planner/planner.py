"""Compute the SSH-key/permission delta between declared state and installed state.

`Planner` is where the paper's declared-vs-real state comparison and the
linear-per-host apply cost originate. `estado_desejado` expands users, groups
and permissions into a per-host, per-key desired state purely from `IStore`
reads (no network I/O). `calcular_delta` then diffs that desired state
against either the state already persisted on each `Servidor` (the default,
and the fast "is anything pending?" path, since it touches no host) or an
`atual_override` supplied by the caller (used by `Nucleo` with
`--reconcile` to diff against state fetched live over SSH instead). The
per-host loop inside `calcular_delta` is independent across hosts, which is
what lets `Nucleo.aplicar` parallelize the subsequent apply step.
"""

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
    """Return whichever of `a`/`b` outranks the other (`SUDO` beats `SHELL`); ties keep `a`."""
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
    """One SSH credential installed for one user, at one permission level, on one host.

    Used both for the desired state built by `Planner.estado_desejado` and the
    installed state read from `Servidor.chaves_instaladas` or a live
    inspection (`Nucleo._atual_vivo`); `calcular_delta` compares instances of
    the two by field equality to detect drift. Frozen because instances are
    used as dict values keyed by `ref` and are expected to be replaced, not
    mutated in place, whenever their level or profile changes.
    """

    ref: str
    username: str
    nivel: NivelPermissao
    profile: str | None = None

    @classmethod
    def de_dict(cls, d: dict) -> "ChaveInstalada":
        """Reconstruct a `ChaveInstalada` from the dict form persisted in `Servidor.chaves_instaladas`.

        `username` and `nivel` fall back to being derived from `ref` and to
        `NivelPermissao.SHELL` respectively when the dict omits them, which
        happens for records written before those fields existed.
        """
        return cls(
            ref=d["ref"],
            username=d.get("username") or d["ref"].split(":", 1)[0],
            nivel=NivelPermissao(d.get("nivel", "shell")),
            profile=d.get("profile"),
        )

    def para_dict(self) -> dict:
        """Serialize back to the dict form persisted in `Servidor.chaves_instaladas`, omitting `profile` entirely instead of writing a null when it is `None`."""
        out = {"ref": self.ref, "username": self.username, "nivel": self.nivel.value}
        if self.profile is not None:
            out["profile"] = self.profile
        return out


class Planner:
    """Diffs the store's declared access state against installed state, on behalf of `Nucleo`.

    Holds only the `IStore` needed to read users, groups, permissions,
    credentials and servers; has no knowledge of SSH or the deployer, which
    keeps `estado_desejado` and the default path of `calcular_delta` free of
    network I/O and therefore fast regardless of fleet size.
    """

    def __init__(self, store: IStore):
        """Store the `IStore` used to read users, groups, permissions, credentials and servers."""
        self.store = store

    def estado_desejado(self) -> dict[str, dict[str, ChaveInstalada]]:
        """Expand every active permission into the desired `ChaveInstalada` for each (host, credential) pair, from store reads alone.

        For each permission, walks every active member of its user-group,
        every active credential of each such user, and every server in its
        server-group. When the same (host, ref) pair is reachable through
        more than one granted permission — e.g. two groups both giving a user
        access to the same host — the levels are merged upward via `_maior`
        (`SUDO` wins over `SHELL`) and the resulting sudo profile is resolved
        by `_merge_profile`, rather than one permission's result simply
        overwriting the other's. A dangling reference (a permission naming a
        deleted group, a group member who is inactive or no longer exists, a
        server no longer registered) is silently skipped rather than treated
        as an error: the store is the source of truth, so a stale reference
        just yields less desired state, not a failure.
        """
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

    def calcular_delta(
        self,
        force: bool = False,
        atual_override: dict[str, dict[str, "ChaveInstalada"]] | None = None,
    ) -> list[Subacao]:
        """Diff desired state against installed state and return the `Subacao` list needed to reconcile them, sorted deterministically.

        This is the check the paper calls "is anything pending?": by default
        (no `atual_override`), the installed side is read entirely from
        `Servidor.chaves_instaladas` already in the store, so the whole
        computation is local and touches no host. `atual_override` lets the
        caller substitute state fetched live over SSH instead (used for
        `--reconcile`). `force=True` discards, per host, any
        currently-installed key that is also desired, so every desired key is
        re-emitted as an add even if the store believes it is already
        installed — used to repair state that has drifted without a live
        `--reconcile`. A key is judged divergent if it is missing, installed
        at the wrong permission level, or installed with the wrong sudo
        profile. Profile command lists are resolved once per profile name via
        a local cache and raise `EstadoInvalido` if the referenced profile is
        missing or has no commands, so a dangling or emptied profile can
        never silently degrade into unrestricted sudo. The result is sorted
        by (host, action, credential) so `Nucleo.aplicar` groups it by host
        deterministically and repeated runs against the same state produce
        identical subaction ordering.
        """
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
            alvo = desejado.get(servidor.hostname, {})
            if atual_override is not None and servidor.hostname in atual_override:
                atual = dict(atual_override[servidor.hostname])
            else:
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
                if force:
                    atual = {r: c for r, c in atual.items() if r not in alvo}

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
