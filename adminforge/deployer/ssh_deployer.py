from __future__ import annotations

import base64
import hashlib
import os
import secrets
import shlex
import subprocess
from pathlib import Path

from adminforge.domain import NivelPermissao, Servidor, Subacao, TipoAcao
from adminforge.exceptions import HostKeyDivergente
from adminforge.interfaces.deployer import IDeployer


class SSHDeployer(IDeployer):
    MARCADOR_INICIO = "# BEGIN adminforge: "
    MARCADOR_FIM = "# END adminforge: "

    def __init__(
        self,
        chave_privada_path: Path,
        known_hosts_path: Path,
        usuario_servico: str = "adminforge",
        timeout: int = 30,
        criar_conta_unix: bool = True,
    ):
        self.chave_privada_path = Path(chave_privada_path)
        self.known_hosts_path = Path(known_hosts_path)
        self.usuario_servico = usuario_servico
        self.timeout = timeout
        self.criar_conta_unix = criar_conta_unix
        self._garantir_known_hosts()

    def _garantir_known_hosts(self) -> None:
        self.known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.known_hosts_path.exists():
            self.known_hosts_path.touch(mode=0o600)
        try:
            os.chmod(self.known_hosts_path, 0o600)
        except PermissionError:
            pass

    def _opcoes_ssh(self, servidor: Servidor) -> list[str]:
        if not servidor.chave_host:
            raise HostKeyDivergente(f"servidor {servidor.hostname} sem host_key registrada")
        self._sincronizar_host_key(servidor)
        return [
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={self.timeout}",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={self.known_hosts_path}",
            "-o", "PasswordAuthentication=no",
            "-o", "PubkeyAuthentication=yes",
            "-o", "GlobalKnownHostsFile=/dev/null",
            "-i", str(self.chave_privada_path),
            "-p", str(servidor.porta_ssh),
        ]

    def _sincronizar_host_key(self, servidor: Servidor) -> None:
        host = servidor.ipv4 or servidor.hostname
        if servidor.porta_ssh != 22:
            entrada = f"[{host}]:{servidor.porta_ssh} {servidor.chave_host}\n"
        else:
            entrada = f"{host} {servidor.chave_host}\n"
        atual = self.known_hosts_path.read_text(encoding="utf-8") if self.known_hosts_path.exists() else ""
        if entrada in atual:
            return
        marcador = f"{host}" if servidor.porta_ssh == 22 else f"[{host}]:{servidor.porta_ssh}"
        linhas_filtradas = [linha for linha in atual.splitlines() if not linha.startswith(marcador + " ")]
        novo = "\n".join(linhas_filtradas + [entrada.rstrip("\n")]) + "\n"
        self.known_hosts_path.write_text(novo, encoding="utf-8")
        os.chmod(self.known_hosts_path, 0o600)

    def _executar_ssh(self, servidor: Servidor, comando: str) -> tuple[int, str, str]:
        host = servidor.ipv4 or servidor.hostname
        cmd = ["ssh", *self._opcoes_ssh(servidor), f"{self.usuario_servico}@{host}", comando]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.timeout * 2,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def capturar_host_key(self, hostname: str, ipv4: str, porta: int) -> tuple[str, str]:
        host = ipv4 or hostname
        cmd = ["ssh-keyscan", "-T", str(self.timeout), "-t", "ed25519,rsa,ecdsa", "-p", str(porta), host]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout * 2)
        if proc.returncode != 0 and not proc.stdout.strip():
            raise HostKeyDivergente(f"ssh-keyscan falhou: {proc.stderr.strip()}")

        preferida = None
        for linha in proc.stdout.splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#"):
                continue
            partes = linha.split(None, 1)
            if len(partes) != 2:
                continue
            _host_field, key = partes
            if key.startswith("ssh-ed25519"):
                preferida = key
                break
            if preferida is None:
                preferida = key

        if preferida is None:
            raise HostKeyDivergente(f"nenhuma host_key retornada por ssh-keyscan para {host}")

        partes = preferida.split(None, 2)
        blob_b64 = partes[1]
        digest = hashlib.sha256(base64.b64decode(blob_b64.encode("ascii"))).digest()
        fp = "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")
        return preferida, fp

    def aplicar(self, servidor: Servidor, subacoes: list[Subacao]) -> list[Subacao]:
        try:
            self._opcoes_ssh(servidor)
        except Exception as e:
            for s in subacoes:
                s.status = "falha"
                s.erro = f"ssh: {e}"
            return subacoes

        rc, _, err = self._executar_ssh(servidor, "true")
        if rc != 0:
            for s in subacoes:
                s.status = "falha"
                s.erro = f"ssh: {err.strip() or 'conexao falhou'}"
            return subacoes

        for s in subacoes:
            try:
                if s.acao == TipoAcao.ADICIONAR_CHAVE:
                    self._adicionar_chave(servidor, s)
                elif s.acao == TipoAcao.REMOVER_CHAVE:
                    self._remover_chave(servidor, s)
                s.status = "sucesso"
            except Exception as e:
                s.status = "falha"
                s.erro = str(e)
        return subacoes

    def _garantir_usuario_unix(self, servidor: Servidor, username: str) -> None:
        u = shlex.quote(username)
        rc, _, _ = self._executar_ssh(servidor, f"id -u {u} >/dev/null 2>&1")
        if rc == 0:
            return
        if not self.criar_conta_unix:
            raise RuntimeError(
                f"usuario '{username}' nao existe e criacao automatica esta desabilitada "
                f"(ADMINFORGE_CREATE_UNIX_USER=false)"
            )
        rc, _, err = self._executar_ssh(servidor, f"sudo useradd -m -s /bin/bash {u}")
        if rc != 0:
            raise RuntimeError(f"falha ao criar usuario unix '{username}': {err.strip()}")

    def _bloco_chave(self, ref: str, chave: str) -> str:
        return (
            f"{self.MARCADOR_INICIO}{ref}\n"
            f"{chave.strip()}\n"
            f"{self.MARCADOR_FIM}{ref}"
        )

    def _ler_authorized_keys(self, servidor: Servidor, username: str) -> str:
        u = shlex.quote(username)
        rc, out, _ = self._executar_ssh(
            servidor, f"sudo cat /home/{u}/.ssh/authorized_keys 2>/dev/null || true"
        )
        return out

    def _escrever_authorized_keys(
        self, servidor: Servidor, username: str, conteudo: str
    ) -> None:
        u = shlex.quote(username)
        b64 = base64.b64encode(conteudo.encode("utf-8")).decode("ascii")
        comando = (
            f"sudo install -d -m 700 -o {u} -g {u} /home/{u}/.ssh && "
            f"echo {shlex.quote(b64)} | base64 -d | "
            f"sudo install -m 600 -o {u} -g {u} /dev/stdin /home/{u}/.ssh/authorized_keys"
        )
        rc, _, err = self._executar_ssh(servidor, comando)
        if rc != 0:
            raise RuntimeError(f"falha ao escrever authorized_keys: {err.strip()}")

    def _substituir_bloco(self, conteudo: str, ref: str, bloco_novo: str) -> str:
        marcador_inicio = f"{self.MARCADOR_INICIO}{ref}"
        marcador_fim = f"{self.MARCADOR_FIM}{ref}"
        out: list[str] = []
        dentro = False
        for linha in conteudo.splitlines():
            if linha == marcador_inicio:
                dentro = True
                continue
            if dentro:
                if linha == marcador_fim:
                    dentro = False
                continue
            out.append(linha)
        if bloco_novo:
            out.append(bloco_novo)
        resultado = "\n".join(out)
        if resultado and not resultado.endswith("\n"):
            resultado += "\n"
        return resultado

    def _adicionar_chave(self, servidor: Servidor, sub: Subacao) -> None:
        if not sub.chave_publica or not sub.username or not sub.credencial:
            raise ValueError("subacao sem chave_publica, username ou credencial")
        self._garantir_usuario_unix(servidor, sub.username)
        atual = self._ler_authorized_keys(servidor, sub.username)
        novo = self._substituir_bloco(
            atual, sub.credencial, self._bloco_chave(sub.credencial, sub.chave_publica)
        )
        self._escrever_authorized_keys(servidor, sub.username, novo)

        sudoers = f"/etc/sudoers.d/adminforge-{sub.username}"
        if sub.nivel == NivelPermissao.SUDO:
            self._escrever_sudoers(servidor, sub.username, sudoers)
        else:
            self._executar_ssh(servidor, f"sudo rm -f {sudoers}")

    def _escrever_sudoers(
        self, servidor: Servidor, username: str, destino: str
    ) -> None:
        linha = f"{username} ALL=(ALL) NOPASSWD:ALL\n"
        tmp = f"/tmp/.adminforge-sudoers-{username}.{secrets.token_hex(8)}"
        comando = (
            f"set -e; "
            f"printf %s {shlex.quote(linha)} | sudo tee {tmp} >/dev/null && "
            f"sudo chmod 0440 {tmp} && "
            f"sudo visudo -cf {tmp} >/dev/null && "
            f"sudo mv {tmp} {destino}"
        )
        rc, _, err = self._executar_ssh(servidor, comando)
        if rc != 0:
            self._executar_ssh(servidor, f"sudo rm -f {tmp}")
            raise RuntimeError(f"falha ao escrever sudoers: {err.strip()}")

    def _remover_chave(self, servidor: Servidor, sub: Subacao) -> None:
        if not sub.username or not sub.credencial:
            raise ValueError("subacao sem username ou credencial")
        atual = self._ler_authorized_keys(servidor, sub.username)
        novo = self._substituir_bloco(atual, sub.credencial, "")
        self._escrever_authorized_keys(servidor, sub.username, novo)
        self._executar_ssh(servidor, f"sudo rm -f /etc/sudoers.d/adminforge-{sub.username}")

    def inspecionar(self, servidor: Servidor) -> dict:
        try:
            self._opcoes_ssh(servidor)
        except Exception as e:
            return {"erro": f"ssh: {e}", "usuarios": [], "servicos": []}

        rc, out_users, err = self._executar_ssh(
            servidor,
            "getent passwd | awk -F: '"
            "$3 >= 100 && $1 != \"nobody\" "
            "{ printf \"%s\\tuid=%s\\tshell=%s\\n\", $1, $3, $7 }'",
        )
        if rc != 0:
            return {"erro": f"ssh: {err.strip()}", "usuarios": [], "servicos": []}

        _, out_serv, _ = self._executar_ssh(
            servidor,
            "systemctl list-units --type=service --state=running --no-legend --no-pager 2>/dev/null "
            "| awk '{print $1}' || service --status-all 2>/dev/null",
        )
        return {
            "usuarios": [u for u in out_users.splitlines() if u.strip()],
            "servicos": [s for s in out_serv.splitlines() if s.strip()],
        }
