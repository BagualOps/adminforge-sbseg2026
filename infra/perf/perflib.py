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
# Where per-repetition raw results are written and looked up. Defaults to the
# committed reference directory (the paper's full campaign). The claim scripts
# override it (PERF_RESULTS_RAW) to a fresh temp dir so they always measure live
# on the evaluator's machine instead of reusing the committed numbers.
RESULTS_RAW = Path(os.environ.get("PERF_RESULTS_RAW", PERF_DIR / "results" / "raw"))
TESTLAB = REPO_ROOT / "infra" / "testlab"


_GNU_TIME = shutil.which("time") or shutil.which("gtime")

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
    """Run a subprocess and capture its output.

    `env` is merged on top of the current environment rather than replacing
    it, so callers only need to pass the variables they add or override.
    When `check` is true (the default) a non-zero exit raises with the
    tail of stdout/stderr attached, so a failing experiment step names
    itself instead of surfacing as an opaque non-zero return code upstream.
    """
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
    """Return the operator private key (0600) in a key dir ssh will accept.

    Uses the committed test key if the developer has it; otherwise generates a
    throwaway ed25519 keypair once, so a fresh clone needs no committed private
    key. build_image() bakes the matching public key into the fleet, so whatever
    key this returns is the one the containers accept.
    """
    dst_dir = key_dir()
    dst = dst_dir / "adminforge_id"
    if dst.exists():
        return dst
    src = TESTLAB / "keys" / "adminforge_id"
    if src.exists():
        shutil.copyfile(src, dst)
        shutil.copyfile(src.with_suffix(".pub"), dst.with_suffix(".pub"))
    else:
        sh(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "adminforge-perf",
            "-f", str(dst), "-q"])
    os.chmod(dst, 0o600)
    return dst


# ---------------------------------------------------------------------------
# Docker fleet
# ---------------------------------------------------------------------------
def build_image() -> None:
    """Build the base fleet image (sshd only) with the operator public key baked in.

    Idempotent from Docker's own layer cache: re-running after the first
    build is a no-op cost-wise unless `infra/testlab/Dockerfile` changed.
    """
    pubkey = operator_key().with_suffix(".pub").read_text().strip()
    sh(["docker", "build", "-t", IMAGE,
        "--build-arg", f"ADMINFORGE_PUBKEY={pubkey}", str(TESTLAB)])


def ensure_network() -> None:
    """Create the bridge network the fleet and controller containers share, if missing."""
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
    """Block until the SSH banner is readable at ip:port, or raise after `timeout` seconds.

    Polled rather than a fixed sleep, so it does not pad the measured
    timings with container-startup jitter and does not undercount slow
    starts on loaded hardware.
    """
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
    """Force-remove every container whose name starts with PREFIX, ignoring errors.

    Called before and after (in a `finally`) every experiment repetition,
    so a crashed prior run never leaks containers into the next fleet size.
    """
    proc = sh(["docker", "ps", "-aq", "--filter", f"name=^{PREFIX}-"], check=False)
    ids = proc.stdout.split()
    if ids:
        sh(["docker", "rm", "-f", *ids], check=False)


# ---------------------------------------------------------------------------
# AdminForge invocation
# ---------------------------------------------------------------------------
def af_env(state_dir: Path) -> dict:
    """Build the environment `af()` runs the AdminForge CLI under for one state dir."""
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
    # Peak RSS is read from GNU time when it is installed. It is absent on many minimal
    # systems, and it is not what any claim asserts: the wall clock below is measured here,
    # and Claim #1 gates on ratios of it. So a missing /usr/bin/time costs the memory column
    # and nothing else, instead of ending the run in a FileNotFoundError.
    if time_v and _GNU_TIME:
        base = [_GNU_TIME, "-v", *base]
    t0 = time.monotonic()
    proc = sh(base, check=check, env=af_env(state_dir), input_text=input_text)
    wall = time.monotonic() - t0
    rss = None
    if time_v and _GNU_TIME:
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
        """Run one untimed AdminForge CLI command and count it towards `cmds`."""
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
    """Write one repetition's result dict as pretty-printed JSON under RESULTS_RAW.

    The caller's out-file existence check (skip if already present) is what
    makes every run_eN.py script resumable, so this write must be the last
    step of a repetition, after nothing about it can still fail.
    """
    RESULTS_RAW.mkdir(parents=True, exist_ok=True)
    path = RESULTS_RAW / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def hardware_info() -> dict:
    """Collect the host CPU model, RAM and OS/Docker versions for the results report.

    Recorded so the paper's numbers can be attributed to the machine they
    were measured on: everything a claim script prints is either this
    hardware-dependent wall-clock context or the hardware-independent
    ratios/counts the claim actually asserts, and this function is only
    ever the former.
    """
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
    mem_gib = round(mem_kib / (1024 * 1024), 1)
    # MemTotal is what the OS sees, which is below the installed capacity on a
    # machine whose integrated GPU reserves system RAM as VRAM. Report both: the
    # OS-visible GiB and the nearest installed size in GB for the hardware line.
    installed_gb = 8 * round(mem_kib * 1024 / 1e9 / 8) or round(mem_kib * 1024 / 1e9)
    return {
        "cpu": cpu,
        "mem_gib": mem_gib,
        "mem_installed_gb": installed_gb,
        "kernel": platform.release(),
        "os": platform.platform(),
        "docker": docker,
        "python": platform.python_version(),
    }
