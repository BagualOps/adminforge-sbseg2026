#!/usr/bin/env python3
"""E3 ATTACK-SURFACE VERIFICATION.

Managed-host side: for 3 sampled containers, capture the set of listening
TCP sockets and bound UDP sockets (parsed from /proc/net/tcp{,6} and
/proc/net/udp{,6} inside the container, so no extra tooling is installed)
BEFORE any management and AFTER full management plus several applies.
Expected: identical sets, containing only the pre-existing sshd on :22.

Operator side: while the cold 'apply' runs, sample the AdminForge process
tree and check whether any of its file descriptors is a listening TCP
socket. Expected: zero samples with a listening socket.

Usage: python3 infra/perf/run_e3.py [--fleet 10] [--sample 3]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import perflib as P


def decode_addr(hex_str: str) -> str:
    """Decode a /proc/net local_address field (little-endian hex)."""
    import ipaddress
    import struct

    raw = bytes.fromhex(hex_str)
    if len(raw) == 4:
        return str(ipaddress.IPv4Address(struct.unpack("<I", raw)[0]))
    groups = [raw[i:i + 4][::-1] for i in range(0, 16, 4)]
    return str(ipaddress.IPv6Address(b"".join(groups)))


def parse_proc_net(text: str, proto: str) -> set[str]:
    """Return 'proto addr port' for LISTEN TCP rows / bound UDP rows.

    Note: on a user-defined Docker network the container netns also holds
    Docker's embedded DNS resolver bound to loopback 127.0.0.11; it shows
    up identically before and after and is never reachable from outside.
    """
    out = set()
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4 or ":" not in parts[1]:
            continue
        addr_hex, port_hex = parts[1].rsplit(":", 1)
        st = parts[3]
        entry = f"{proto[:3]} {decode_addr(addr_hex)} {int(port_hex, 16)}"
        if proto.startswith("tcp") and st == "0A":  # TCP_LISTEN
            out.add(entry)
        elif proto.startswith("udp") and st == "07":  # bound UDP
            out.add(entry)
    return out


def container_sockets(name: str) -> set[str]:
    out: set[str] = set()
    for proto in ("tcp", "tcp6", "udp", "udp6"):
        proc = P.sh(["docker", "exec", name, "cat", f"/proc/net/{proto}"], check=False)
        if proc.returncode == 0:
            out |= parse_proc_net(proc.stdout, proto)
    return out


def host_listen_inodes() -> set[str]:
    inodes = set()
    for proto in ("tcp", "tcp6"):
        for line in Path(f"/proc/net/{proto}").read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) > 9 and parts[3] == "0A":
                inodes.add(parts[9])
    return inodes


def proc_tree(pid: int) -> list[int]:
    pids, todo = [], [pid]
    while todo:
        p = todo.pop()
        pids.append(p)
        for task in Path(f"/proc/{p}/task").glob("*/children"):
            try:
                todo += [int(c) for c in task.read_text().split()]
            except OSError:
                pass
    return pids


def tree_socket_inodes(pid: int) -> set[str]:
    inodes = set()
    for p in proc_tree(pid):
        fd_dir = Path(f"/proc/{p}/fd")
        try:
            for fd in fd_dir.iterdir():
                try:
                    target = os.readlink(fd)
                except OSError:
                    continue
                if target.startswith("socket:["):
                    inodes.add(target[8:-1])
        except OSError:
            pass
    return inodes


def monitored_apply(state: Path) -> dict:
    """Run 'apply --yes' while sampling the process tree for listening sockets."""
    env = dict(os.environ)
    env.update(P.af_env(state))
    cmd = [sys.executable, "-m", "adminforge.cli.main", "--state", str(state),
           "apply", "--yes"]
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    samples = 0
    violations = []
    while proc.poll() is None:
        listen = host_listen_inodes()
        owned = tree_socket_inodes(proc.pid)
        bad = listen & owned
        if bad:
            violations.append(sorted(bad))
        samples += 1
        time.sleep(0.05)
    proc.communicate()
    return {"rc": proc.returncode, "samples": samples,
            "listening_socket_violations": violations}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fleet", type=int, default=10)
    ap.add_argument("--sample", type=int, default=3)
    args = ap.parse_args()

    P.build_image()
    keys = P.gen_user_keys(P.WORK_DIR / "userkeys", P.N_ADMINS + 1)
    extra = keys.pop("admin11")

    P.fleet_down()
    hosts = P.fleet_up(args.fleet)
    idx = [0, len(hosts) // 2, len(hosts) - 1][: args.sample]
    sampled = [hosts[i]["container"] for i in dict.fromkeys(idx)]

    state = P.WORK_DIR / "state-e3"
    if state.exists():
        shutil.rmtree(state)

    payload: dict = {"fleet": args.fleet, "sampled_containers": sampled, "hosts_side": {}}
    try:
        before = {c: sorted(container_sockets(c)) for c in sampled}

        P.declare_state(state, hosts, keys)
        operator = monitored_apply(state)  # cold apply, monitored
        # several more applies: no-op, incremental, revocation
        P.af(["apply", "--yes"], state)
        P.af(["user", "add", "--username", "admin11", "--name", "Perf admin11",
              "--email", "admin11@perf.lab", "--key-file", str(extra)], state)
        P.af(["user-group", "add-member", "--group", P.SHELL_GROUP,
              "--username", "admin11"], state)
        P.af(["apply", "--yes"], state)
        P.af(["user-group", "remove-member", "--group", P.SHELL_GROUP,
              "--username", "admin11"], state)
        P.af(["apply", "--yes"], state)
        P.af(["apply", "verify"], state)

        after = {c: sorted(container_sockets(c)) for c in sampled}
        for c in sampled:
            payload["hosts_side"][c] = {
                "before": before[c],
                "after": after[c],
                "new_sockets": sorted(set(after[c]) - set(before[c])),
            }
        payload["operator_side"] = operator
        payload["verdict"] = {
            "zero_new_listening_services_on_hosts": all(
                not v["new_sockets"] for v in payload["hosts_side"].values()),
            "af_opened_no_listening_socket": not operator["listening_socket_violations"]
            and operator["samples"] > 0,
        }
    finally:
        P.fleet_down()

    P.save_raw("e3_attack_surface", payload)
    print(f"[e3] verdict={payload['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
