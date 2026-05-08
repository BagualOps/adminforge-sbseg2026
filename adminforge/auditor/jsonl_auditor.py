from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from adminforge.domain import (
    NivelPermissao,
    Operacao,
    StatusOperacao,
    Subacao,
    TipoAcao,
)
from adminforge.exceptions import CadeiaQuebrada, NaoExiste
from adminforge.interfaces.auditor import IAuditor
from adminforge.store.atomic import append_line


class JsonlAuditor(IAuditor):
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _serializar_subacao(self, s: Subacao) -> dict:
        d = asdict(s)
        d["acao"] = s.acao.value
        if s.nivel is not None:
            d["nivel"] = s.nivel.value
        return {k: v for k, v in d.items() if v is not None and v != ""}

    def _calcular_hash(self, payload: dict) -> str:
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _ultimo_hash(self) -> str | None:
        ultimo = None
        if not self.path.exists():
            return None
        with self.path.open("r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                ultimo = json.loads(linha).get("hash")
        return ultimo

    def proximo_id(self) -> str:
        contador = 1
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as f:
                contador = sum(1 for _ in f) + 1
        return f"OP-{contador:04d}"

    def registrar(self, operacao: Operacao) -> None:
        operacao.hash_anterior = self._ultimo_hash()
        payload = {
            "id": operacao.id,
            "momento": operacao.momento.isoformat(timespec="seconds"),
            "superadmin": operacao.superadmin,
            "comando": operacao.comando,
            "status": operacao.status.value,
            "subacoes": [self._serializar_subacao(s) for s in operacao.subacoes],
            "hash_anterior": operacao.hash_anterior,
        }
        operacao.hash = self._calcular_hash(payload)
        payload["hash"] = operacao.hash
        append_line(self.path, json.dumps(payload, ensure_ascii=False))

    def _carregar(self) -> list[Operacao]:
        if not self.path.exists():
            return []
        out: list[Operacao] = []
        with self.path.open("r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                d = json.loads(linha)
                subacoes = [
                    Subacao(
                        servidor=s.get("servidor", ""),
                        acao=TipoAcao(s["acao"]),
                        credencial=s.get("credencial"),
                        chave_publica=s.get("chave_publica"),
                        username=s.get("username"),
                        nivel=NivelPermissao(s["nivel"]) if s.get("nivel") else None,
                        status=s.get("status", ""),
                        erro=s.get("erro"),
                        mensagem=s.get("mensagem"),
                    )
                    for s in d.get("subacoes", [])
                ]
                out.append(
                    Operacao(
                        id=d["id"],
                        momento=datetime.fromisoformat(d["momento"]),
                        superadmin=d["superadmin"],
                        comando=d["comando"],
                        status=StatusOperacao(d["status"]),
                        subacoes=subacoes,
                        hash_anterior=d.get("hash_anterior"),
                        hash=d.get("hash"),
                    )
                )
        return out

    def listar(self, limite: int = 50) -> list[Operacao]:
        ops = self._carregar()
        return ops[-limite:][::-1] if limite else ops[::-1]

    def listar_falhas(self, limite: int = 50) -> list[Operacao]:
        falhos = [
            op
            for op in self._carregar()
            if op.status in (StatusOperacao.FALHA, StatusOperacao.SUCESSO_PARCIAL)
        ]
        return falhos[-limite:][::-1] if limite else falhos[::-1]

    def buscar(self, id: str) -> Operacao | None:
        for op in self._carregar():
            if op.id == id:
                return op
        return None

    def verificar_cadeia(self) -> tuple[bool, str | None]:
        anterior: str | None = None
        if not self.path.exists():
            return True, None
        with self.path.open("r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                d = json.loads(linha)
                hash_armazenado = d.pop("hash", None)
                if d.get("hash_anterior") != anterior:
                    raise CadeiaQuebrada(
                        f"prev_hash mismatch at {d.get('id')}"
                    )
                recalculado = self._calcular_hash(d)
                if recalculado != hash_armazenado:
                    raise CadeiaQuebrada(f"hash mismatch at {d.get('id')}")
                anterior = hash_armazenado
        return True, anterior

    def buscar_obrigatorio(self, id: str) -> Operacao:
        op = self.buscar(id)
        if op is None:
            raise NaoExiste(f"operation '{id}' does not exist")
        return op
