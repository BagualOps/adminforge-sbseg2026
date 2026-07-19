"""Shared helpers for the AdminForge performance harness.

Standard library only. All paths are derived from the repository root,
never hardcoded to a personal machine.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PERF_DIR = REPO_ROOT / "infra" / "perf"
WORK_DIR = Path(os.environ.get("PERF_WORK", PERF_DIR / "work"))
RESULTS_RAW = PERF_DIR / "results" / "raw"
TESTLAB = REPO_ROOT / "infra" / "testlab"


def key_dir() -> Path:
    """Directory able to hold 0600 private keys.

    The repository may live on a filesystem without POSIX permissions
    (e.g. NTFS), where ssh refuses the operator key. Detect that and fall
    back to a per-user directory on the system temp filesystem.
    """
    candidate = WORK_DIR / "keys"
    candidate.mkdir(parents=True, exist_ok=True)
    probe = candidate / ".permprobe"
    probe.touch()
    os.chmod(probe, 0o600)
    ok = (probe.stat().st_mode & 0o077) == 0
    probe.unlink()
    if ok:
        return candidate
    import tempfile

    fallback = Path(tempfile.gettempdir()) / f"adminforge-perf-{os.getuid()}" / "keys"
    fallback.mkdir(parents=True, exist_ok=True)
    os.chmod(fallback, 0o700)
    return fallback

IMAGE = os.environ.get("PERF_IMAGE", "adminforge-perf:latest")
NETWORK = os.environ.get("PERF_NETWORK", "afperf")
PREFIX = os.environ.get("PERF_PREFIX", "afperf")


def sh(cmd: list[str], check: bool = True, env: dict | None = None,
       cwd: Path | None = None, input_text: str | None = None) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    proc = subprocess.run(
        cmd, capture_output=True, text=True, env=full_env,
        cwd=str(cwd) if cwd else None, input=input_text,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed rc={proc.returncode}: {' '.join(cmd)}\n"
            f"stdout: {proc.stdout[-2000:]}\nstderr: {proc.stderr[-2000:]}"
        )
    return proc


# ---------------------------------------------------------------------------
# Operator SSH key (the testlab key committed in infra/testlab/keys)
# ---------------------------------------------------------------------------
def operator_key() -> Path:
    """Copy the testlab operator key into the key dir with 0600 perms."""
    src = TESTLAB / "keys" / "adminforge_id"
    dst_dir = key_dir()
    dst = dst_dir / "adminforge_id"
    shutil.copyfile(src, dst)
    os.chmod(dst, 0o600)
    shutil.copyfile(src.with_suffix(".pub"), dst.with_suffix(".pub"))
    return dst


# ---------------------------------------------------------------------------
# Docker fleet
# ---------------------------------------------------------------------------
def build_image() -> None:
    pubkey = (TESTLAB / "keys" / "adminforge_id.pub").read_text().strip()
    sh(["docker", "build", "-t", IMAGE,
        "--build-arg", f"ADMINFORGE_PUBKEY={pubkey}", str(TESTLAB)])


def ensure_network() -> None:
    proc = sh(["docker", "network", "inspect", NETWORK], check=False)
    if proc.returncode != 0:
        sh(["docker", "network", "create", "--driver", "bridge", NETWORK])


def fleet_up(n: int, image: str = IMAGE) -> list[dict]:
    """Start n sshd containers, return [{'hostname','ip','container'}]."""
    ensure_network()
    names = [f"{PREFIX}-{i:02d}" for i in range(1, n + 1)]
    for name in names:
        sh(["docker", "run", "-d", "--rm", "--name", name,
            "--hostname", name, "--network", NETWORK, image])
    hosts = []
    for name in names:
        proc = sh(["docker", "inspect", "-f",
                   "{{.NetworkSettings.Networks." + NETWORK + ".IPAddress}}", name])
        ip = proc.stdout.strip()
        hosts.append({"hostname": name, "ip": ip, "container": name})
    for h in hosts:
        wait_ssh(h["ip"])
    return hosts


def wait_ssh(ip: str, port: int = 22, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((ip, port), timeout=2) as s:
                banner = s.recv(64)
                if banner.startswith(b"SSH-"):
                    return
        except OSError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"sshd at {ip}:{port} did not come up in {timeout}s")


def fleet_down() -> None:
    proc = sh(["docker", "ps", "-aq", "--filter", f"name=^{PREFIX}-"], check=False)
    ids = proc.stdout.split()
    if ids:
        sh(["docker", "rm", "-f", *ids], check=False)


# ---------------------------------------------------------------------------
# AdminForge invocation
# ---------------------------------------------------------------------------
def af_env(state_dir: Path) -> dict:
    return {
        "ADMINFORGE_STATE": str(state_dir),
        "ADMINFORGE_SSH_KEY": str(operator_key()),
        "ADMINFORGE_SUPERADMIN": "perf-harness",
        "PYTHONPATH": str(REPO_ROOT),
    }


def af(args: list[str], state_dir: Path, check: bool = True,
       time_v: bool = False, input_text: str | None = None,
       ) -> tuple[subprocess.CompletedProcess, float, int | None]:
    """Run one AdminForge CLI command. Returns (proc, wall_seconds, peak_rss_kib)."""
    base = [sys.executable, "-m", "adminforge.cli.main", "--state", str(state_dir), *args]
    if time_v:
        base = ["/usr/bin/time", "-v", *base]
    t0 = time.monotonic()
    proc = sh(base, check=check, env=af_env(state_dir), input_text=input_text)
    wall = time.monotonic() - t0
    rss = None
    if time_v:
        m = re.search(r"Maximum resident set size \(kbytes\): (\d+)", proc.stderr)
        if m:
            rss = int(m.group(1))
    return proc, wall, rss


# ---------------------------------------------------------------------------
# Declared state used by every experiment
# ---------------------------------------------------------------------------
N_ADMINS = 10
SHELL_GROUP = "shellops"
SUDO_GROUP = "sudoops"
SERVER_GROUP = "fleet"
SUDO_PROFILE = "ops"
SUDO_COMMANDS = ["/usr/bin/systemctl", "/usr/bin/journalctl"]


def gen_user_keys(key_dir: Path, count: int) -> dict[str, Path]:
    """Generate throwaway ed25519 keypairs admin01..adminNN. Returns name -> pub path."""
    key_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for i in range(1, count + 1):
        name = f"admin{i:02d}"
        priv = key_dir / name
        if not priv.exists():
            sh(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", f"{name}@perf",
                "-f", str(priv), "-q"])
        out[name] = priv.with_suffix(".pub")
    return out


def declare_state(state_dir: Path, hosts: list[dict], keys: dict[str, Path]) -> int:
    """Register the reference declared state. Returns number of CLI commands used."""
    state_dir.mkdir(parents=True, exist_ok=True)
    cmds = 0

    def run(args: list[str], input_text: str | None = None) -> None:
        nonlocal cmds
        af(args, state_dir, input_text=input_text)
        cmds += 1

    profile_args = ["sudo-profile", "create", "--name", SUDO_PROFILE]
    for c in SUDO_COMMANDS:
        profile_args += ["--command", c]
    run(profile_args)

    names = sorted(keys)
    for name in names:
        run(["user", "add", "--username", name, "--name", f"Perf {name}",
             "--email", f"{name}@perf.lab", "--key-file", str(keys[name])])

    run(["user-group", "create", "--name", SHELL_GROUP])
    run(["user-group", "create", "--name", SUDO_GROUP])
    half = len(names) // 2
    run(["user-group", "add-member", "--group", SHELL_GROUP, "--username", *names[:half]])
    run(["user-group", "add-member", "--group", SUDO_GROUP, "--username", *names[half:]])

    for h in hosts:
        # --auto captures the host key via ssh-keyscan (TOFU) and asks for
        # fingerprint confirmation; the harness confirms via stdin.
        run(["server", "add", "--hostname", h["hostname"], "--ip", h["ip"], "--auto"],
            input_text="y\n")

    run(["server-group", "create", "--name", SERVER_GROUP])
    run(["server-group", "add-member", "--group", SERVER_GROUP,
         "--hostname", *[h["hostname"] for h in hosts]])

    run(["permission", "grant", "--user-group", SHELL_GROUP,
         "--server-group", SERVER_GROUP, "--level", "shell"])
    run(["permission", "grant", "--user-group", SUDO_GROUP,
         "--server-group", SERVER_GROUP, "--level", "sudo", "--profile", SUDO_PROFILE])
    return cmds


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
def save_raw(name: str, payload: dict) -> Path:
    RESULTS_RAW.mkdir(parents=True, exist_ok=True)
    path = RESULTS_RAW / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def hardware_info() -> dict:
    cpu = ""
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("model name"):
            cpu = line.split(":", 1)[1].strip()
            break
    mem_kib = 0
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal"):
            mem_kib = int(line.split()[1])
            break
    docker = sh(["docker", "--version"], check=False).stdout.strip()
    return {
        "cpu": cpu,
        "mem_gib": round(mem_kib / (1024 * 1024), 1),
        "kernel": platform.release(),
        "os": platform.platform(),
        "docker": docker,
        "python": platform.python_version(),
    }
