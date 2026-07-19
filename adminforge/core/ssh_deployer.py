from __future__ import annotations

import base64
import hashlib
import os
import secrets
import shlex
import subprocess
import threading
from pathlib import Path

from adminforge import authorized_keys as ak
from adminforge.domain import NivelPermissao, Servidor, Subacao, TipoAcao
from adminforge.exceptions import HostKeyDivergente
from adminforge.interfaces.deployer import IDeployer


class SSHDeployer(IDeployer):

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
        # Guards the read-modify-write of the shared known_hosts file so that a
        # parallel apply (apply --jobs N) does not lose entries to a data race.
        self._kh_lock = threading.Lock()
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
            raise HostKeyDivergente(f"server {servidor.hostname} has no registered host_key")
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
        with self._kh_lock:
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
            stdin=subprocess.DEVNULL,  # não herda/consome o stdin de quem chamou
        )
        return proc.returncode, proc.stdout, proc.stderr

    def capturar_host_key(self, hostname: str, ipv4: str, porta: int) -> tuple[str, str]:
        host = ipv4 or hostname
        cmd = ["ssh-keyscan", "-T", str(self.timeout), "-t", "ed25519,rsa,ecdsa", "-p", str(porta), host]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=self.timeout * 2, stdin=subprocess.DEVNULL
        )
        if proc.returncode != 0 and not proc.stdout.strip():
            raise HostKeyDivergente(f"ssh-keyscan failed: {proc.stderr.strip()}")

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
            raise HostKeyDivergente(f"no host_key returned by ssh-keyscan for {host}")

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
                s.erro = f"ssh: {err.strip() or 'connection failed'}"
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
                f"unix user '{username}' does not exist and auto-create is disabled "
                f"(ADMINFORGE_CREATE_UNIX_USER=false)"
            )
        rc, _, err = self._executar_ssh(servidor, f"sudo useradd -m -s /bin/bash {u}")
        if rc != 0:
            raise RuntimeError(f"failed to create unix user '{username}': {err.strip()}")

    def ler_authorized_keys(self, servidor: Servidor, username: str) -> tuple[str, bool]:
        # Primeiro valida que sudo funciona com NOPASSWD; sem isso nao da
        # para distinguir 'arquivo nao existe' (output vazio legitimo) de
        # 'sudo bloqueou' (output vazio mascarando erro).
        rc, _, _ = self._executar_ssh(servidor, "sudo -n true 2>/dev/null")
        if rc != 0:
            return "", False
        u = shlex.quote(username)
        # if-then explicito: arquivo ausente => output vazio + rc=0 (legitimo).
        rc, out, _ = self._executar_ssh(
            servidor,
            f"if sudo test -e /home/{u}/.ssh/authorized_keys; then "
            f"sudo cat /home/{u}/.ssh/authorized_keys; "
            f"fi",
        )
        return out, rc == 0

    def _escrever_authorized_keys(
        self, servidor: Servidor, username: str, conteudo: str
    ) -> None:
        u = shlex.quote(username)
        b64 = base64.b64encode(conteudo.encode("utf-8")).decode("ascii")
        # backup do arquivo atual em .bak antes de sobrescrever (rollback manual)
        comando = (
            f"sudo install -d -m 700 -o {u} -g {u} /home/{u}/.ssh && "
            f"if sudo test -f /home/{u}/.ssh/authorized_keys; then "
            f"sudo install -m 600 -o {u} -g {u} /home/{u}/.ssh/authorized_keys "
            f"/home/{u}/.ssh/authorized_keys.bak; fi && "
            f"echo {shlex.quote(b64)} | base64 -d | "
            f"sudo install -m 600 -o {u} -g {u} /dev/stdin /home/{u}/.ssh/authorized_keys"
        )
        rc, _, err = self._executar_ssh(servidor, comando)
        if rc != 0:
            raise RuntimeError(f"failed to write authorized_keys: {err.strip()}")


    def _adicionar_chave(self, servidor: Servidor, sub: Subacao) -> None:
        if not sub.chave_publica or not sub.username or not sub.credencial:
            raise ValueError("sub-action missing chave_publica, username or credencial")
        self._garantir_usuario_unix(servidor, sub.username)
        atual, ok = self.ler_authorized_keys(servidor, sub.username)
        if not ok:
            raise RuntimeError(
                f"failed to read authorized_keys for '{sub.username}'; "
                f"refusing to overwrite to avoid losing existing AdminForge blocks"
            )
        novo = ak.substituir_bloco(
            atual, sub.credencial, ak.bloco(sub.credencial, sub.chave_publica)
        )
        self._escrever_authorized_keys(servidor, sub.username, novo)

        sudoers = f"/etc/sudoers.d/adminforge-{sub.username}"
        if sub.nivel == NivelPermissao.SUDO:
            self._escrever_sudoers(servidor, sub.username, sudoers, sub.profile_comandos)
        else:
            self._executar_ssh(servidor, f"sudo rm -f {sudoers}")

    def _escrever_sudoers(
        self,
        servidor: Servidor,
        username: str,
        destino: str,
        comandos: list[str] | None,
    ) -> None:
        # Diferencia explicitamente None (full sudo) de [] (profile invalido):
        #   None         -> NOPASSWD:ALL (intencional)
        #   lista vazia  -> erro (profile resolveu para nada; nao escala silenciosamente)
        #   lista        -> uma linha por comando absoluto
        if comandos is None:
            corpo = f"{username} ALL=(ALL) NOPASSWD:ALL\n"
        elif len(comandos) == 0:
            raise RuntimeError(
                f"refusing to write sudoers for '{username}': empty command list "
                f"(would otherwise silently grant full sudo)"
            )
        else:
            # defense-in-depth: revalida no ponto de gravacao. State editado a mao
            # poderia conter path relativo ou control char nao detectado pelo Nucleo.
            for c in comandos:
                if not c.startswith("/"):
                    raise RuntimeError(
                        f"refusing to write sudoers for '{username}': "
                        f"command must be absolute path: {c!r}"
                    )
                if any(ch in c for ch in ("\n", "\r", "\x00")):
                    raise RuntimeError(
                        f"refusing to write sudoers for '{username}': "
                        f"command contains forbidden control character: {c!r}"
                    )
            corpo = "\n".join(
                f"{username} ALL=(ALL) NOPASSWD: {c}" for c in comandos
            ) + "\n"
        tmp = f"/tmp/.adminforge-sudoers-{username}.{secrets.token_hex(8)}"
        comando = (
            f"set -e; "
            f"printf %s {shlex.quote(corpo)} | sudo tee {tmp} >/dev/null && "
            f"sudo chmod 0440 {tmp} && "
            f"sudo visudo -cf {tmp} >/dev/null && "
            f"sudo mv {tmp} {destino}"
        )
        rc, _, err = self._executar_ssh(servidor, comando)
        if rc != 0:
            self._executar_ssh(servidor, f"sudo rm -f {tmp}")
            raise RuntimeError(f"failed to write sudoers: {err.strip()}")

    def _remover_chave(self, servidor: Servidor, sub: Subacao) -> None:
        if not sub.username or not sub.credencial:
            raise ValueError("sub-action missing username or credencial")
        atual, ok = self.ler_authorized_keys(servidor, sub.username)
        if not ok:
            raise RuntimeError(
                f"failed to read authorized_keys for '{sub.username}'; "
                f"refusing to overwrite"
            )
        novo = ak.substituir_bloco(atual, sub.credencial, "")
        self._escrever_authorized_keys(servidor, sub.username, novo)
        self._executar_ssh(servidor, f"sudo rm -f /etc/sudoers.d/adminforge-{sub.username}")

    _SCRIPT_INSPECAO = (
        'echo "=== USERS ==="; getent passwd; '
        'echo "=== GROUPS ==="; getent group; '
        'echo "=== SERVICES ==="; '
        # checa systemctl explicitamente: 'cmd | awk' dava rc=0 do awk mesmo com systemctl ausente,
        # impedindo o fallback service --status-all.
        'if command -v systemctl >/dev/null 2>&1; then '
        'systemctl list-units --type=service --state=running --no-legend --no-pager 2>/dev/null '
        '| awk \'{print $1}\'; '
        'elif command -v service >/dev/null 2>&1; then '
        'service --status-all 2>/dev/null; '
        'fi; '
        'echo "=== SUDOERS_FILES ==="; '
        '(sudo -n ls /etc/sudoers.d/ 2>/dev/null || ls /etc/sudoers.d/ 2>/dev/null) || true; '
        'echo "=== SUDOERS_BODY ==="; '
        '(sudo -n cat /etc/sudoers /etc/sudoers.d/* 2>/dev/null '
        '|| cat /etc/sudoers /etc/sudoers.d/* 2>/dev/null) || true'
    )

    @staticmethod
    def _classificar_uid(uid: int) -> str:
        if uid < 100:
            return "system"
        if uid < 1000:
            return "service"
        return "human"

    def inspecionar(self, servidor: Servidor) -> dict:
        try:
            self._opcoes_ssh(servidor)
        except Exception as e:
            return {"erro": f"ssh: {e}"}

        rc, out, err = self._executar_ssh(servidor, self._SCRIPT_INSPECAO)
        if rc != 0:
            return {"erro": f"ssh: {err.strip()}"}

        secoes: dict[str, list[str]] = {
            "USERS": [], "GROUPS": [], "SERVICES": [],
            "SUDOERS_FILES": [], "SUDOERS_BODY": [],
        }
        atual: str | None = None
        for linha in out.splitlines():
            if linha.startswith("=== ") and linha.endswith(" ==="):
                marca = linha[4:-4]
                atual = marca if marca in secoes else None
                continue
            if atual and linha.strip():
                secoes[atual].append(linha)

        # parse: getent group dá nome:x:gid:m1,m2,...
        grupos_por_gid: dict[int, dict] = {}
        grupos: list[dict] = []
        for linha in secoes["GROUPS"]:
            partes = linha.split(":")
            if len(partes) < 4:
                continue
            nome, _, gid_s, membros = partes[0], partes[1], partes[2], partes[3]
            try:
                gid = int(gid_s)
            except ValueError:
                continue
            g = {
                "nome": nome,
                "gid": gid,
                "membros": [m for m in membros.split(",") if m],
            }
            grupos.append(g)
            grupos_por_gid[gid] = g

        # parse: getent passwd dá nome:x:uid:gid:gecos:home:shell
        usuarios: list[dict] = []
        for linha in secoes["USERS"]:
            partes = linha.split(":")
            if len(partes) < 7:
                continue
            nome = partes[0]
            try:
                uid, gid_primario = int(partes[2]), int(partes[3])
            except ValueError:
                continue
            shell = partes[6]
            grupos_user = sorted(
                {g["nome"] for g in grupos if nome in g["membros"]}
                | ({grupos_por_gid[gid_primario]["nome"]} if gid_primario in grupos_por_gid else set())
            )
            usuarios.append({
                "nome": nome,
                "uid": uid,
                "shell": shell,
                "categoria": self._classificar_uid(uid),
                "grupos": grupos_user,
            })

        # parse sudoers: regras nao-comentario, e mapeamento por arquivo (drift)
        regras_sudo: list[str] = []
        for linha in secoes["SUDOERS_BODY"]:
            stripped = linha.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("Defaults"):
                continue
            regras_sudo.append(stripped)

        arquivos_sudoers = []
        for nome in secoes["SUDOERS_FILES"]:
            arquivos_sudoers.append({
                "nome": nome.strip(),
                "adminforge": nome.strip().startswith("adminforge-"),
            })

        # mapeia regras por usuario (heuristico: 1a coluna da regra)
        sudo_por_user: dict[str, list[str]] = {}
        for regra in regras_sudo:
            primeira = regra.split(None, 1)[0] if regra else ""
            if primeira.startswith("%"):
                continue  # regra de grupo, ignora aqui
            sudo_por_user.setdefault(primeira, []).append(regra)
        for u in usuarios:
            u["sudo"] = sudo_por_user.get(u["nome"], [])

        return {
            "usuarios": usuarios,
            "grupos": grupos,
            "servicos": [s.strip() for s in secoes["SERVICES"] if s.strip()],
            "sudoers_arquivos": arquivos_sudoers,
            "sudoers_regras": regras_sudo,
        }
