#!/usr/bin/env python3
"""E2 COMPARISON WITH ANSIBLE: same effective operation on the same fleet.

Operation: ensure the 10 managed users exist with their authorized_keys and
sudoers entries on all N hosts (identical to the E1 declared state minus
AdminForge bookkeeping). Cells, per repetition (fresh containers for the
first apply, same fleet for the no-op re-run):
  first_apply   ansible-playbook against an unmanaged fleet
  noop_apply    immediate re-run (everything already converged)

Configurations: N=10 with default forks, N=50 with default forks, and
N=50 with forks=25 (fairness run for the larger fleet).

Fairness settings (documented in the raw output):
  - same containers, same operator key, same 'adminforge' NOPASSWD sudo user
  - known_hosts prepopulated by ssh-keyscan before timing (AdminForge also
    captures host keys at registration time, outside the timed window)
  - StrictHostKeyChecking=yes for both tools
  - gather_facts: false (the playbook uses no facts; this favors Ansible)
  - only ansible-core builtin modules; pipelining left at its default (False)
  - Ansible requires a Python interpreter on every managed host, so E2 runs
    on an image variant with python3 added (ansible/Dockerfile.python3);
    AdminForge needs no remote interpreter. To show the variant does not
    change AdminForge numbers, one AdminForge cold+noop apply repetition is
    also recorded on the python3 image ('af_sanity' raw file).

Usage: python3 infra/perf/run_e2.py [--reps 5]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import perflib as P

ANSIBLE_DIR = P.PERF_DIR / "ansible"
VENV = P.WORK_DIR / "venv-ansible"
IMAGE_PY3 = "adminforge-perf-ansible:latest"


def build_image_py3() -> None:
    P.build_image()
    P.sh(["docker", "build", "-t", IMAGE_PY3,
          "--build-arg", f"BASE_IMAGE={P.IMAGE}",
          "-f", str(ANSIBLE_DIR / "Dockerfile.python3"), str(ANSIBLE_DIR)])


def ensure_ansible() -> tuple[str, str]:
    if not (VENV / "bin" / "ansible-playbook").exists():
        P.sh([sys.executable, "-m", "venv", str(VENV)])
        P.sh([str(VENV / "bin" / "pip"), "install", "--quiet", "ansible-core"])
    proc = P.sh([str(VENV / "bin" / "ansible"), "--version"])
    version = proc.stdout.splitlines()[0].strip()
    dump = P.sh([str(VENV / "bin" / "ansible-config"), "dump"], check=False).stdout
    forks_default = ""
    for line in dump.splitlines():
        if line.startswith("DEFAULT_FORKS"):
            forks_default = line.strip()
            break
    return version, forks_default


def write_users_yml(keys: dict[str, Path]) -> Path:
    """Same 10 users and same sudo policy as the E1 declared state."""
    names = sorted(keys)
    half = len(names) // 2
    lines = ["managed_users:"]
    for i, name in enumerate(names):
        pub = keys[name].read_text().strip()
        lines.append(f"  - name: {name}")
        lines.append(f'    pubkey: "{pub}"')
        if i >= half:  # sudoops half, same commands as the AdminForge sudo profile
            sudoers = ", ".join(P.SUDO_COMMANDS)
            lines.append(f'    sudoers: "{name} ALL=(ALL) NOPASSWD: {sudoers}"')
    path = ANSIBLE_DIR / "users.yml"
    path.write_text("\n".join(lines) + "\n")
    return path


def write_inventory(hosts: list[dict], known_hosts: Path) -> Path:
    key = P.operator_key()
    lines = ["[fleet]"]
    for h in hosts:
        lines.append(f"{h['hostname']} ansible_host={h['ip']}")
    lines += [
        "",
        "[fleet:vars]",
        "ansible_user=adminforge",
        f"ansible_ssh_private_key_file={key}",
        ("ansible_ssh_common_args=-o StrictHostKeyChecking=yes "
         f"-o UserKnownHostsFile={known_hosts}"),
    ]
    path = P.WORK_DIR / "inventory.ini"
    path.write_text("\n".join(lines) + "\n")
    return path


def keyscan(hosts: list[dict]) -> Path:
    out = []
    for h in hosts:
        proc = P.sh(["ssh-keyscan", "-t", "ed25519", h["ip"]], check=False)
        out.append(proc.stdout)
    path = P.WORK_DIR / "ansible_known_hosts"
    path.write_text("".join(out))
    return path


def run_playbook(inventory: Path, forks: int | None) -> float:
    env = {"ANSIBLE_HOST_KEY_CHECKING": "True"}
    cmd = [str(VENV / "bin" / "ansible-playbook"), "-i", str(inventory),
           str(ANSIBLE_DIR / "playbook.yml")]
    if forks is not None:
        cmd += ["--forks", str(forks)]
    t0 = time.monotonic()
    P.sh(cmd, env=env, cwd=ANSIBLE_DIR)
    return time.monotonic() - t0


def af_sanity(n: int, keys: dict) -> None:
    """One AdminForge cold+noop repetition on the python3 image variant."""
    import shutil

    out = P.RESULTS_RAW / "e2_af_sanity_python3_image.json"
    if out.exists():
        return
    P.fleet_down()
    hosts = P.fleet_up(n, image=IMAGE_PY3)
    state = P.WORK_DIR / "state-e2-sanity"
    shutil.rmtree(state, ignore_errors=True)
    try:
        P.declare_state(state, hosts, keys)
        _, cold, _ = P.af(["apply", "--yes"], state)
        _, noop, _ = P.af(["apply", "--yes"], state)
        P.save_raw("e2_af_sanity_python3_image",
                   {"n": n, "image": IMAGE_PY3, "note":
                    "adminforge on the python3 image variant, single repetition",
                    "cells": {"cold_apply": cold, "noop_apply": noop}})
    finally:
        P.fleet_down()


def one_rep(n: int, forks: int | None, rep: int, keys: dict) -> dict:
    P.fleet_down()
    hosts = P.fleet_up(n, image=IMAGE_PY3)
    payload = {"n": n, "forks": forks if forks is not None else "default", "rep": rep,
               "cells": {}}
    try:
        known_hosts = keyscan(hosts)  # untimed, mirrors AdminForge TOFU at registration
        inventory = write_inventory(hosts, known_hosts)
        payload["cells"]["first_apply"] = run_playbook(inventory, forks)
        payload["cells"]["noop_apply"] = run_playbook(inventory, forks)
    finally:
        P.fleet_down()
    return payload


def count_effort() -> dict:
    def nonempty(path: Path) -> int:
        return sum(1 for line in path.read_text().splitlines()
                   if line.strip() and not line.strip().startswith("#"))

    return {
        "ansible_playbook_lines": nonempty(ANSIBLE_DIR / "playbook.yml"),
        "ansible_inventory_lines": nonempty(P.WORK_DIR / "inventory.ini"),
        "ansible_users_yml_lines": nonempty(ANSIBLE_DIR / "users.yml"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--configs", default="10:default,50:default,50:25",
                    help="comma list of N:forks (forks 'default' keeps ansible.cfg default)")
    args = ap.parse_args()

    build_image_py3()
    version, forks_default = ensure_ansible()
    keys = P.gen_user_keys(P.WORK_DIR / "userkeys", P.N_ADMINS)
    write_users_yml(keys)
    af_sanity(10, keys)

    configs = []
    for item in args.configs.split(","):
        n, forks = item.split(":")
        configs.append((int(n), None if forks == "default" else int(forks)))

    for n, forks in configs:
        tag = "default" if forks is None else str(forks)
        for rep in range(1, args.reps + 1):
            out = P.RESULTS_RAW / f"e2_n{n:02d}_forks{tag}_rep{rep}.json"
            if out.exists():
                print(f"[e2] n={n} forks={tag} rep={rep} already done, skipping")
                continue
            print(f"[e2] n={n} forks={tag} rep={rep} ...", flush=True)
            payload = one_rep(n, forks, rep, keys)
            payload["ansible_version"] = version
            payload["ansible_forks_default"] = forks_default
            payload["effort"] = count_effort()
            P.save_raw(f"e2_n{n:02d}_forks{tag}_rep{rep}", payload)
            print(f"[e2] n={n} forks={tag} rep={rep} cells={payload['cells']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
