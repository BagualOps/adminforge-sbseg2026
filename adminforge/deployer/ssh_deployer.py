"""Real-execution ``IDeployer`` implementation: applies changes over SSH.

This is the module where dry-run stops and side effects on remote hosts
begin — everything here shells out to ``ssh``/``ssh-keyscan`` and mutates
files on the target server (``authorized_keys``, ``/etc/sudoers.d/*``,
optionally creating the unix account). ``adminforge.deployer.dry_run`` is
the simulated counterpart with the same ``IDeployer`` shape but no network
or filesystem effects on any remote host; callers choose between the two,
this class never checks a "dry run" flag internally.

Failure handling is per-subaction, not per-host or per-run: ``aplicar``
processes every ``Subacao`` for one server and marks each one
``"sucesso"``/``"falha"`` independently, so one server (or one credential
within a server) failing does not stop or roll back the others already
applied. There is no distributed transaction across hosts or across
sub-actions on the same host; state changes made before a failure are not
undone.
"""

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
    """Applies and inspects state on remote servers over SSH using a service account key.

    Every remote operation goes through ``_executar_ssh``, which enforces
    strict host-key checking (no TOFU, no ``StrictHostKeyChecking=no``) and
    public-key-only auth — a server's ``chave_host`` must already be known
    (see ``capturar_host_key``) before any command can run against it.
    Writes to remote files (``authorized_keys``, sudoers) are done via
    temp-file-then-``mv`` shell pipelines so a failed remote write does not
    leave a half-written destination file.
    """

    def __init__(
        self,
        chave_privada_path: Path,
        known_hosts_path: Path,
        usuario_servico: str = "adminforge",
        timeout: int = 30,
        criar_conta_unix: bool = True,
    ):
        """Configure SSH credentials/options and ensure the known_hosts file exists with mode 0600.

        ``criar_conta_unix`` controls whether ``_garantir_usuario_unix`` is
        allowed to run ``useradd`` for a missing account or must instead
        fail (mirrors ``ADMINFORGE_CREATE_UNIX_USER``).
        """
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
        """Create the known_hosts file (mode 0600) if missing, and re-assert that mode either way.

        A ``PermissionError`` from ``chmod`` is swallowed rather than
        raised (same rationale as elsewhere in the store/deployer layers:
        some filesystems won't honor the mode, and that alone shouldn't be
        fatal).
        """
        self.known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.known_hosts_path.exists():
            self.known_hosts_path.touch(mode=0o600)
        try:
            os.chmod(self.known_hosts_path, 0o600)
        except PermissionError:
            pass

    def _opcoes_ssh(self, servidor: Servidor) -> list[str]:
        """Build the shared ``ssh`` CLI options for talking to ``servidor``.

        Raises ``HostKeyDivergente`` if the server has no registered
        ``chave_host`` yet — this is the gate that prevents ever connecting
        to a host AdminForge hasn't explicitly pinned. As a side effect,
        also ensures that pinned key is present in ``known_hosts`` (via
        ``_sincronizar_host_key``) before returning the option list, since
        ``StrictHostKeyChecking=yes`` below requires it to already be
        there. ``GlobalKnownHostsFile=/dev/null`` means only AdminForge's
        own known_hosts file is trusted, not the system-wide one.
        """
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
        """Ensure ``servidor.chave_host`` is present (and any stale entry for the same host replaced) in known_hosts.

        Read-modify-write of the whole file is protected by ``_kh_lock``
        since multiple servers may be deployed to concurrently
        (``apply --jobs N``) and all share this one file; without the lock
        two threads racing here could each read the file before the other's
        write, and one entry would be lost. If the exact entry is already
        present this is a no-op; otherwise any existing line for the same
        host (and port, for non-default ports) is dropped before appending
        the current one, so a server's rotated host key replaces its old
        entry rather than accumulating duplicates.
        """
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
        """Run ``comando`` on ``servidor`` over SSH and return ``(returncode, stdout, stderr)``.

        Blocks stdin explicitly (``subprocess.DEVNULL``) so this never
        consumes or waits on the caller's own stdin. Uses a timeout of
        twice ``self.timeout`` (the connect timeout), giving the remote
        command roughly that much time to actually execute after the
        connection itself is established; a ``subprocess.TimeoutExpired``
        propagates uncaught to the caller.
        """
        host = servidor.ipv4 or servidor.hostname
        cmd = ["ssh", *self._opcoes_ssh(servidor), f"{self.usuario_servico}@{host}", comando]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.timeout * 2,
            stdin=subprocess.DEVNULL,  # does not inherit/consume the caller's stdin
        )
        return proc.returncode, proc.stdout, proc.stderr

    def capturar_host_key(self, hostname: str, ipv4: str, porta: int) -> tuple[str, str]:
        """Run ``ssh-keyscan`` against the host and return ``(key_line, sha256_fingerprint)``.

        Prefers an ``ssh-ed25519`` key if the host offers one, otherwise
        takes the first key line returned. This is how a server's
        ``chave_host`` gets pinned in the first place (out of band from
        ``_opcoes_ssh``'s strict checking) and should be treated as
        trust-on-first-use: the caller is responsible for having the
        operator confirm the fingerprint before it's persisted. Raises
        ``HostKeyDivergente`` if ``ssh-keyscan`` fails outright or returns
        no usable key line.
        """
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
        """Apply every sub-action to ``servidor``, mutating each ``Subacao``'s status/erro in place.

        This is the real (non-dry-run) entry point: it actually connects
        and mutates remote state. Two connectivity failures fail *all*
        sub-actions in bulk without attempting any of them (no host_key /
        ``_opcoes_ssh`` raising, or the ``true`` connectivity probe
        returning non-zero) — in that case none of ``subacoes`` was ever
        attempted, so it is safe to retry the whole batch. Past that point,
        each sub-action is tried independently: one raising an exception
        marks only that sub-action ``"falha"`` and the loop continues to
        the next one, so a partial failure on this host does not roll back
        or skip sub-actions already applied earlier in the same call. The
        input list is both mutated and returned.
        """
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
        """Ensure the unix account ``username`` exists on ``servidor``, creating it if allowed.

        If the account is missing and ``self.criar_conta_unix`` is
        ``False``, raises ``RuntimeError`` instead of creating it — this is
        the enforcement point for the "don't auto-provision unix accounts"
        policy (``ADMINFORGE_CREATE_UNIX_USER=false``). Account creation
        uses ``sudo useradd -m -s /bin/bash``, so it also fails loudly if
        sudo on the remote side isn't configured for this.
        """
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
        """Read ``username``'s authorized_keys via sudo, returning ``(content, ok)``.

        ``ok`` is ``False`` whenever the read cannot be trusted — either
        the ``sudo -n true`` preflight fails (no passwordless sudo) or the
        remote command itself fails. This distinction matters because a
        missing authorized_keys file is a legitimate case that also
        produces empty output with ``rc == 0``: without the preflight,
        "sudo silently blocked" and "file genuinely doesn't exist yet"
        would be indistinguishable, and callers use ``ok`` to decide
        whether it is safe to overwrite the file (see ``_adicionar_chave``/
        ``_remover_chave``, which both refuse to proceed when ``ok`` is
        ``False`` to avoid clobbering content they couldn't actually read).
        """
        # First validates that sudo works with NOPASSWD; without it there is no
        # way to distinguish 'file does not exist' (legitimate empty output) from
        # 'sudo blocked' (empty output masking the error).
        rc, _, _ = self._executar_ssh(servidor, "sudo -n true 2>/dev/null")
        if rc != 0:
            return "", False
        u = shlex.quote(username)
        # explicit if-then: missing file => empty output + rc=0 (legitimate).
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
        """Write ``conteudo`` as ``username``'s authorized_keys via a base64 pipe + temp-file + atomic move.

        Content is base64-encoded before being embedded in the remote shell
        command so arbitrary key material can't break out of the command
        line. The remote-side sequence backs up the existing file to
        ``.bak`` (if present), writes to a per-invocation temp path under
        ``/tmp`` (random suffix via ``secrets.token_hex`` to avoid
        collisions between concurrent deploys), then ``sudo mv``s it into
        place — the rename is the only step that can make the change
        visible, so a failure earlier in the pipeline never leaves a
        partially written authorized_keys file. On any remote failure the
        temp file is best-effort cleaned up and ``RuntimeError`` is raised.
        A ``tee``+temp+``mv`` pattern is used instead of
        ``install /dev/stdin`` because the latter isn't available on
        minimal/busybox coreutils some targets may run.
        """
        u = shlex.quote(username)
        b64 = base64.b64encode(conteudo.encode("utf-8")).decode("ascii")
        # tee+temp+mv (same pattern as _escrever_sudoers): install /dev/stdin
        # breaks on minimal coreutils (busybox).
        ssh_dir = shlex.quote(f"/home/{username}/.ssh")
        destino = shlex.quote(f"/home/{username}/.ssh/authorized_keys")
        tmp = f"/tmp/.adminforge-ak-{username}.{secrets.token_hex(8)}"
        comando = (
            f"set -e; "
            f"sudo install -d -m 700 -o {u} -g {u} {ssh_dir} && "
            f"if sudo test -f {destino}; then "
            f"sudo install -m 600 -o {u} -g {u} {destino} {destino}.bak; fi && "
            f"echo {shlex.quote(b64)} | base64 -d | sudo tee {tmp} >/dev/null && "
            f"sudo chmod 600 {tmp} && "
            f"sudo chown {u}:{u} {tmp} && "
            f"sudo mv {tmp} {destino}"
        )
        rc, _, err = self._executar_ssh(servidor, comando)
        if rc != 0:
            self._executar_ssh(servidor, f"sudo rm -f {tmp}")
            raise RuntimeError(f"failed to write authorized_keys: {err.strip()}")


    def _adicionar_chave(self, servidor: Servidor, sub: Subacao) -> None:
        """Install/replace one credential's block in authorized_keys, and sync its sudoers entry.

        Requires the unix account to exist first (creating it if allowed).
        Refuses to proceed — raising rather than silently starting from an
        empty file — if the existing authorized_keys content couldn't be
        read reliably (see ``ler_authorized_keys``), since writing from an
        empty/unknown base could delete other AdminForge-managed blocks
        that happen to already be there. Also (re)writes or removes this
        user's ``/etc/sudoers.d/adminforge-<username>`` file to match
        ``sub.nivel`` — sudo access tracks the credential's own level, not
        a separate step the caller must remember to trigger.
        """
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
        """Render and install a sudoers drop-in for ``username``, validated remotely with ``visudo -cf``.

        ``comandos`` is a three-way switch, not just an optional list:
        ``None`` means unrestricted (``NOPASSWD:ALL``, intentional full
        sudo); an empty list is treated as an error rather than "no
        commands", because silently writing a rule that grants nothing
        would look successful while actually leaving the user with no sudo
        access the caller likely expected; a non-empty list is validated
        item-by-item (must be an absolute path, no newline/CR/NUL) as
        defense-in-depth against hand-edited state files that bypassed the
        Nucleo's own validation. The rendered file is written to a random
        temp path, syntax-checked with ``visudo -cf`` *before* being moved
        into ``/etc/sudoers.d/``, so a malformed rule never reaches the
        live sudoers directory; on any failure the temp file is best-effort
        removed and ``RuntimeError`` is raised.
        """
        # Explicitly distinguishes None (full sudo) from [] (invalid profile):
        #   None          -> NOPASSWD:ALL (intentional)
        #   empty list    -> error (profile resolved to nothing; does not silently escalate)
        #   list          -> one line per absolute command
        if comandos is None:
            corpo = f"{username} ALL=(ALL) NOPASSWD:ALL\n"
        elif len(comandos) == 0:
            raise RuntimeError(
                f"refusing to write sudoers for '{username}': empty command list "
                f"(would otherwise silently grant full sudo)"
            )
        else:
            # defense-in-depth: revalidate at the write point. Hand-edited state
            # could contain a relative path or control char not detected by the Nucleo.
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
        """Strip one credential's block from authorized_keys and delete its sudoers drop-in.

        Same read-before-write safety as ``_adicionar_chave``: refuses to
        proceed if the current authorized_keys content couldn't be read
        reliably, to avoid overwriting it with an incomplete/empty base.
        The sudoers removal (``rm -f``) is unconditional and best-effort —
        its result is not checked, so this method does not fail just
        because the sudoers file was already absent.
        """
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
        # checks systemctl explicitly: 'cmd | awk' returned rc=0 from awk even with systemctl missing,
        # preventing the service --status-all fallback.
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
        """Classify a unix uid as ``"system"`` (<100), ``"service"`` (<1000), or ``"human"`` (otherwise)."""
        if uid < 100:
            return "system"
        if uid < 1000:
            return "service"
        return "human"

    def inspecionar(self, servidor: Servidor) -> dict:
        """Run a single read-only remote script and return a structured snapshot of server state.

        Executes ``_SCRIPT_INSPECAO`` once (one round trip covers users,
        groups, running services, and sudoers), then parses its
        section-delimited plain-text output locally. All sudo-gated parts
        of the script fall back to a non-sudo attempt (e.g.
        ``sudo -n cat ... || cat ...``) so inspection degrades gracefully
        instead of failing outright when the service account lacks
        passwordless sudo — it just won't see privileged data it isn't
        allowed to read. On any SSH-level failure returns ``{"erro": ...}``
        instead of raising, unlike ``aplicar``'s per-sub-action exceptions.
        Sudo rules are attributed to users heuristically by taking the
        first whitespace-separated token of each non-comment,
        non-``Defaults`` line as the username; group rules (lines starting
        with ``%``) are recognized and skipped, not attributed to anyone.
        """
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

        # parse: getent group gives name:x:gid:m1,m2,...
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

        # parse: getent passwd gives name:x:uid:gid:gecos:home:shell
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

        # parse sudoers: non-comment rules, and per-file mapping (drift)
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

        # map rules per user (heuristic: 1st column of the rule)
        sudo_por_user: dict[str, list[str]] = {}
        for regra in regras_sudo:
            primeira = regra.split(None, 1)[0] if regra else ""
            if primeira.startswith("%"):
                continue  # group rule, ignore here
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
