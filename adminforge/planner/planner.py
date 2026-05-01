from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from adminforge.domain import (
    NivelPermissao,
    StatusAdmin,
    StatusCredencial,
    Subacao,
    TipoAcao,
)
from adminforge.interfaces.store import IStore


_PRIORIDADE = {NivelPermissao.SHELL: 1, NivelPermissao.SUDO: 2}


def _maior(a: NivelPermissao, b: NivelPermissao) -> NivelPermissao:
    return a if _PRIORIDADE[a] >= _PRIORIDADE[b] else b


@dataclass(frozen=True)
class ChaveInstalada:
    ref: str
    username: str
    nivel: NivelPermissao

    @classmethod
    def de_dict(cls, d: dict) -> "ChaveInstalada":
        return cls(
            ref=d["ref"],
            username=d.get("username") or d["ref"].split(":", 1)[0],
            nivel=NivelPermissao(d.get("nivel", "shell")),
        )

    def para_dict(self) -> dict:
        return {"ref": self.ref, "username": self.username, "nivel": self.nivel.value}


class Planner:
    def __init__(self, store: IStore):
        self.store = store

    def estado_desejado(self) -> dict[str, dict[str, ChaveInstalada]]:
        admins = {a.username: a for a in self.store.list_admins() if a.status == StatusAdmin.ATIVO}
        creds_por_admin = {
            u: [c for c in self.store.list_credenciais(u) if c.status == StatusCredencial.ATIVA]
            for u in admins
        }
        grupos_admin = {g.nome: g for g in self.store.list_grupos_admin()}
        grupos_servidor = {g.nome: g for g in self.store.list_grupos_servidor()}
        servidores_validos = {s.hostname for s in self.store.list_servidores()}

        desejado: dict[str, dict[str, ChaveInstalada]] = defaultdict(dict)
        for perm in self.store.list_permissoes():
            ga = grupos_admin.get(perm.grupo_admin)
            gs = grupos_servidor.get(perm.grupo_servidor)
            if not ga or not gs:
                continue
            for username in ga.membros:
                if username not in admins:
                    continue
                for cred in creds_por_admin.get(username, []):
                    ref = cred.referencia
                    for hostname in gs.membros:
                        if hostname not in servidores_validos:
                            continue
                        existente = desejado[hostname].get(ref)
                        nivel = perm.nivel if existente is None else _maior(existente.nivel, perm.nivel)
                        desejado[hostname][ref] = ChaveInstalada(
                            ref=ref, username=username, nivel=nivel
                        )
        return desejado

    def calcular_delta(self) -> list[Subacao]:
        desejado = self.estado_desejado()
        subacoes: list[Subacao] = []

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
                if instalado is None or instalado.nivel != esperado.nivel:
                    subacoes.append(
                        Subacao(
                            servidor=servidor.hostname,
                            acao=TipoAcao.ADICIONAR_CHAVE,
                            credencial=ref,
                            chave_publica=chave_publica,
                            username=esperado.username,
                            nivel=esperado.nivel,
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
