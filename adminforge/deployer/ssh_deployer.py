from __future__ import annotations

import io
import shlex
from pathlib import Path

import paramiko

from adminforge.domain import NivelPermissao, Servidor, Subacao, TipoAcao
from adminforge.exceptions import HostKeyDivergente
from adminforge.interfaces.deployer import IDeployer


class SSHDeployer(IDeployer):
    MARCADOR_INICIO = "# BEGIN adminforge: "
    MARCADOR_FIM = "# END adminforge: "

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
        if not servidor.chave_host:
            raise HostKeyDivergente(f"servidor {servidor.hostname} sem host_key registrada")
        host_key = self._carregar_host_key(servidor.chave_host)
        nomes = {servidor.hostname, servidor.ipv4}
        if servidor.porta_ssh != 22:
            nomes |= {f"[{servidor.hostname}]:{servidor.porta_ssh}", f"[{servidor.ipv4}]:{servidor.porta_ssh}"}
        for nome in nomes:
            if nome:
                client.get_host_keys().add(nome, host_key.get_name(), host_key)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())

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
        return f"{host_key.get_name()} {blob}", _fingerprint_sha256(host_key)

    def _executar(self, client: paramiko.SSHClient, comando: str) -> tuple[int, str, str]:
        _, stdout, stderr = client.exec_command(comando, timeout=self.timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        return rc, out, err

    def _garantir_usuario_unix(self, client: paramiko.SSHClient, username: str) -> None:
        u = shlex.quote(username)
        rc, _, _ = self._executar(client, f"id -u {u} >/dev/null 2>&1")
        if rc == 0:
            return
        if not self.criar_conta_unix:
            raise RuntimeError(
                f"usuario '{username}' nao existe e criacao automatica esta desabilitada "
                f"(ADMINFORGE_CREATE_UNIX_USER=false)"
            )
        rc, _, err = self._executar(client, f"sudo useradd -m -s /bin/bash {u}")
        if rc != 0:
            raise RuntimeError(f"falha ao criar usuario unix '{username}': {err.strip()}")

    def _bloco_chave(self, ref: str, chave: str) -> str:
        return (
            f"{self.MARCADOR_INICIO}{ref}\n"
            f"{chave.strip()}\n"
            f"{self.MARCADOR_FIM}{ref}"
        )

    def _adicionar_chave(self, client: paramiko.SSHClient, sub: Subacao) -> None:
        if not sub.chave_publica or not sub.username or not sub.credencial:
            raise ValueError("subacao sem chave_publica, username ou credencial")
        self._garantir_usuario_unix(client, sub.username)
        atual = self._ler_authorized_keys(client, sub.username)
        novo = self._substituir_bloco(atual, sub.credencial, self._bloco_chave(sub.credencial, sub.chave_publica))
        self._escrever_authorized_keys(client, sub.username, novo)

        sudoers = f"/etc/sudoers.d/adminforge-{sub.username}"
        if sub.nivel == NivelPermissao.SUDO:
            self._escrever_sudoers(client, sub.username, sudoers)
        else:
            self._executar(client, f"sudo rm -f {sudoers}")

    def _escrever_sudoers(
        self, client: paramiko.SSHClient, username: str, destino: str
    ) -> None:
        linha = f"{username} ALL=(ALL) NOPASSWD:ALL\n"
        tmp = f"/tmp/.adminforge-sudoers-{username}.{_token()}"
        comando = (
            f"set -e; "
            f"printf %s {shlex.quote(linha)} | sudo tee {tmp} >/dev/null && "
            f"sudo chmod 0440 {tmp} && "
            f"sudo visudo -cf {tmp} >/dev/null && "
            f"sudo mv {tmp} {destino}"
        )
        rc, _, err = self._executar(client, comando)
        if rc != 0:
            self._executar(client, f"sudo rm -f {tmp}")
            raise RuntimeError(f"falha ao escrever sudoers: {err.strip()}")

    def _remover_chave(self, client: paramiko.SSHClient, sub: Subacao) -> None:
        if not sub.username or not sub.credencial:
            raise ValueError("subacao sem username ou credencial")
        atual = self._ler_authorized_keys(client, sub.username)
        novo = self._substituir_bloco(atual, sub.credencial, "")
        self._escrever_authorized_keys(client, sub.username, novo)
        self._executar(client, f"sudo rm -f /etc/sudoers.d/adminforge-{sub.username}")

    def _ler_authorized_keys(self, client: paramiko.SSHClient, username: str) -> str:
        u = shlex.quote(username)
        rc, out, _ = self._executar(
            client,
            f"sudo cat /home/{u}/.ssh/authorized_keys 2>/dev/null || true",
        )
        return out

    def _escrever_authorized_keys(
        self, client: paramiko.SSHClient, username: str, conteudo: str
    ) -> None:
        u = shlex.quote(username)
        b64 = _b64encode(conteudo)
        comando = (
            f"sudo install -d -m 700 -o {u} -g {u} /home/{u}/.ssh && "
            f"echo {shlex.quote(b64)} | base64 -d | "
            f"sudo install -m 600 -o {u} -g {u} /dev/stdin /home/{u}/.ssh/authorized_keys"
        )
        rc, _, err = self._executar(client, comando)
        if rc != 0:
            raise RuntimeError(f"falha ao escrever authorized_keys: {err.strip()}")

    def _substituir_bloco(self, conteudo: str, ref: str, bloco_novo: str) -> str:
        linhas = conteudo.splitlines()
        marcador_inicio = f"{self.MARCADOR_INICIO}{ref}"
        marcador_fim = f"{self.MARCADOR_FIM}{ref}"
        out: list[str] = []
        dentro = False
        for linha in linhas:
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
                "getent passwd | awk -F: '"
                "$3 >= 100 && $1 != \"nobody\" "
                "{ printf \"%s\\tuid=%s\\tshell=%s\\n\", $1, $3, $7 }'",
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


def _b64encode(s: str) -> str:
    import base64

    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def _token() -> str:
    import secrets

    return secrets.token_hex(8)


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


def _fingerprint_sha256(host_key: paramiko.PKey) -> str:
    import base64
    import hashlib

    digest = hashlib.sha256(host_key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")
