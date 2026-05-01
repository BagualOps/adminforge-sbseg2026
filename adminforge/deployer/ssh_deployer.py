from __future__ import annotations

import io
import shlex
from pathlib import Path

import paramiko

from adminforge.domain import NivelPermissao, Servidor, Subacao, TipoAcao
from adminforge.exceptions import HostKeyDivergente
from adminforge.interfaces.deployer import IDeployer


class SSHDeployer(IDeployer):
    def __init__(
        self,
        chave_privada_path: Path,
        usuario_servico: str = "adminforge",
        timeout: int = 30,
        criar_conta_unix: bool = True,
    ):
        self.chave_privada_path = Path(chave_privada_path)
        self.usuario_servico = usuario_servico
        self.timeout = timeout
        self.criar_conta_unix = criar_conta_unix

    def _conectar(self, servidor: Servidor) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        if servidor.chave_host:
            host_key = self._carregar_host_key(servidor.chave_host)
            client.get_host_keys().add(servidor.hostname, host_key.get_name(), host_key)
            client.get_host_keys().add(servidor.ipv4, host_key.get_name(), host_key)
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            raise HostKeyDivergente(f"servidor {servidor.hostname} sem host_key registrada")

        client.connect(
            hostname=servidor.ipv4 or servidor.hostname,
            port=servidor.porta_ssh,
            username=self.usuario_servico,
            key_filename=str(self.chave_privada_path),
            timeout=self.timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        return client

    def _carregar_host_key(self, raw: str) -> paramiko.PKey:
        partes = raw.strip().split(None, 2)
        if len(partes) < 2:
            raise HostKeyDivergente("formato de host_key invalido")
        tipo, blob = partes[0], partes[1]
        return _from_known(tipo, blob)

    def capturar_host_key(self, hostname: str, ipv4: str, porta: int) -> tuple[str, str]:
        transport = paramiko.Transport((ipv4 or hostname, porta))
        try:
            transport.start_client(timeout=self.timeout)
            host_key = transport.get_remote_server_key()
        finally:
            transport.close()
        import base64

        blob = base64.b64encode(host_key.asbytes()).decode("ascii")
        return f"{host_key.get_name()} {blob}", host_key.fingerprint.hex() if hasattr(
            host_key, "fingerprint"
        ) else _fingerprint_md5(host_key)

    def _executar(self, client: paramiko.SSHClient, comando: str) -> tuple[int, str, str]:
        _, stdout, stderr = client.exec_command(comando, timeout=self.timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        return rc, out, err

    def _garantir_usuario_unix(self, client: paramiko.SSHClient, username: str) -> None:
        if not self.criar_conta_unix:
            return
        comando = (
            f"id -u {shlex.quote(username)} >/dev/null 2>&1 || "
            f"sudo useradd -m -s /bin/bash {shlex.quote(username)}"
        )
        rc, _, err = self._executar(client, comando)
        if rc != 0:
            raise RuntimeError(f"falha ao criar usuario unix '{username}': {err.strip()}")

    def _adicionar_chave(self, client: paramiko.SSHClient, sub: Subacao) -> None:
        if not sub.chave_publica or not sub.username:
            raise ValueError("subacao sem chave_publica ou username")
        self._garantir_usuario_unix(client, sub.username)
        chave = sub.chave_publica.strip().replace("'", "'\\''")
        u = shlex.quote(sub.username)
        comando = (
            f"sudo -u {u} bash -c '"
            f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
            f"touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && "
            f"grep -qxF \"{chave}\" ~/.ssh/authorized_keys || echo \"{chave}\" >> ~/.ssh/authorized_keys"
            f"'"
        )
        rc, _, err = self._executar(client, comando)
        if rc != 0:
            raise RuntimeError(f"falha ao instalar chave: {err.strip()}")

        sudoers = f"/etc/sudoers.d/adminforge-{sub.username}"
        if sub.nivel == NivelPermissao.SUDO:
            linha = f"{sub.username} ALL=(ALL) NOPASSWD:ALL"
            comando_sudoers = (
                f"echo {shlex.quote(linha)} | sudo tee {sudoers} >/dev/null && "
                f"sudo chmod 0440 {sudoers}"
            )
            rc, _, err = self._executar(client, comando_sudoers)
            if rc != 0:
                raise RuntimeError(f"falha ao escrever sudoers: {err.strip()}")
        else:
            self._executar(client, f"sudo rm -f {sudoers}")

    def _remover_chave(self, client: paramiko.SSHClient, sub: Subacao) -> None:
        if not sub.username or not sub.credencial:
            raise ValueError("subacao sem username ou credencial")
        fingerprint = sub.credencial.split(":", 1)[1] if ":" in sub.credencial else sub.credencial
        u = shlex.quote(sub.username)
        marcador = shlex.quote(fingerprint)
        comando = (
            f"sudo -u {u} bash -c '"
            f"if [ -f ~/.ssh/authorized_keys ]; then "
            f"grep -v {marcador} ~/.ssh/authorized_keys > ~/.ssh/authorized_keys.tmp && "
            f"mv ~/.ssh/authorized_keys.tmp ~/.ssh/authorized_keys && "
            f"chmod 600 ~/.ssh/authorized_keys; "
            f"fi'"
        )
        rc, _, err = self._executar(client, comando)
        if rc != 0:
            raise RuntimeError(f"falha ao remover chave: {err.strip()}")
        self._executar(client, f"sudo rm -f /etc/sudoers.d/adminforge-{sub.username}")

    def aplicar(self, servidor: Servidor, subacoes: list[Subacao]) -> list[Subacao]:
        try:
            client = self._conectar(servidor)
        except Exception as e:
            for s in subacoes:
                s.status = "falha"
                s.erro = f"ssh: {e}"
            return subacoes

        try:
            for s in subacoes:
                try:
                    if s.acao == TipoAcao.ADICIONAR_CHAVE:
                        self._adicionar_chave(client, s)
                    elif s.acao == TipoAcao.REMOVER_CHAVE:
                        self._remover_chave(client, s)
                    s.status = "sucesso"
                except Exception as e:
                    s.status = "falha"
                    s.erro = str(e)
        finally:
            client.close()
        return subacoes

    def inspecionar(self, servidor: Servidor) -> dict:
        try:
            client = self._conectar(servidor)
        except Exception as e:
            return {"erro": f"ssh: {e}", "usuarios": [], "servicos": []}
        try:
            _, out_users, _ = self._executar(
                client,
                "getent passwd | awk -F: '$3>=1000 && $1!=\"nobody\" {print $1}'",
            )
            _, out_serv, _ = self._executar(
                client,
                "systemctl list-units --type=service --state=running --no-legend --no-pager 2>/dev/null "
                "| awk '{print $1}' || service --status-all 2>/dev/null",
            )
            return {
                "usuarios": [u for u in out_users.splitlines() if u.strip()],
                "servicos": [s for s in out_serv.splitlines() if s.strip()],
            }
        finally:
            client.close()


def _from_known(tipo: str, blob: str) -> paramiko.PKey:
    raw = f"{tipo} {blob}\n"
    if tipo == "ssh-rsa":
        return paramiko.RSAKey(data=_decode_b64(blob))
    if tipo == "ssh-ed25519":
        return paramiko.Ed25519Key(data=_decode_b64(blob))
    if tipo.startswith("ecdsa-sha2-"):
        return paramiko.ECDSAKey(data=_decode_b64(blob))
    return paramiko.PKey.from_type_string(tipo, _decode_b64(blob))


def _decode_b64(s: str) -> bytes:
    import base64

    return base64.b64decode(s.encode("ascii"))


def _fingerprint_md5(host_key: paramiko.PKey) -> str:
    import hashlib

    digest = hashlib.md5(host_key.asbytes()).hexdigest()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))
