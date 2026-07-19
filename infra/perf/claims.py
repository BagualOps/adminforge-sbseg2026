#!/usr/bin/env python3
"""Print the paper/artifact claims computed from results/results.json,
asserting that the recorded numbers actually support them.

Usage: python3 infra/perf/claims.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import perflib as P


def main() -> int:
    path = P.PERF_DIR / "results" / "results.json"
    data = json.loads(path.read_text())

    e1 = data["e1_scalability"]
    n_max = max(int(k) for k in e1)
    top = e1[str(n_max)]["cells"]
    cold = top["cold_apply"]["median_s"]
    noop = top["noop_apply"]["median_s"]
    incr = top["incremental_apply"]["median_s"]
    revk = top["revoke_apply"]["median_s"]
    rss = e1[str(n_max)]["cold_apply_peak_rss_mib"]

    checks = []

    claim1 = (
        f"First full apply of the declared state (10 admins, 2 groups, sudo profile) "
        f"to {n_max} hosts completes in median {cold:.1f} s; a no-op re-apply takes "
        f"{noop:.2f} s because the planner computes an empty delta locally, without "
        f"opening a single SSH connection."
    )
    checks.append(("no-op at least 10x faster than cold apply", noop * 10 < cold))
    checks.append(("no-op under 1 s at largest fleet", noop < 1.0))

    claim2 = (
        f"Adding one admin to a group and re-applying touches only the delta: "
        f"median {incr:.1f} s across {n_max} hosts, and revoking that admin takes "
        f"median {revk:.1f} s; peak resident memory of the operator process during "
        f"the cold apply at N={n_max} is {rss:.0f} MiB."
    )
    checks.append(("incremental apply faster than cold apply", incr < cold))
    checks.append(("revocation faster than cold apply", revk < cold))

    e3 = data["e3_attack_surface"]
    v = e3["verdict"]

    def non_loopback_tcp(entries: list[str]) -> set[str]:
        out = set()
        for e in entries:
            proto, addr, port = e.rsplit(" ", 2)
            if proto == "tcp" and not addr.startswith("127.") and addr != "::1":
                out.add(port)
        return out

    reachable = {frozenset(non_loopback_tcp(h["after"]))
                 for h in e3["hosts_side"].values()}
    claim3 = (
        f"Managing a fleet adds zero new listening services: on "
        f"{len(e3['hosts_side'])} sampled hosts the socket set before and after "
        f"full management is identical and the only externally reachable listener "
        f"is the pre-existing sshd on port 22, while in "
        f"{e3['operator_side']['samples']} samples during apply the AdminForge "
        f"process tree never held a listening socket."
    )
    checks.append(("zero new listening sockets on managed hosts",
                   v["zero_new_listening_services_on_hosts"]))
    checks.append(("af process opened no listening socket",
                   v["af_opened_no_listening_socket"]))
    checks.append(("only sshd:22 reachable (non-loopback) on managed hosts",
                   reachable == {frozenset({"22"})}))

    e2 = data.get("e2_ansible_comparison", {})
    claim4 = None
    key = f"n{n_max:02d}_forksdefault"
    if key in e2:
        a_first = e2[key]["cells"]["first_apply"]["median_s"]
        a_noop = e2[key]["cells"]["noop_apply"]["median_s"]
        claim4 = (
            f"An equivalent Ansible playbook (ansible-core, default forks) needs "
            f"median {a_first:.1f} s for the first apply and {a_noop:.1f} s for a "
            f"no-op re-run at N={n_max}, versus {cold:.1f} s and {noop:.2f} s for "
            f"AdminForge; AdminForge re-checks convergence without contacting hosts."
        )
        checks.append(("AdminForge no-op faster than Ansible no-op", noop < a_noop))

    failed = [name for name, ok in checks if not ok]
    width = 74
    print("+" + "-" * width + "+")
    status = "OK: all claim assertions hold" if not failed else "FAILED assertions!"
    print("| " + status.ljust(width - 2) + " |")
    print("+" + "-" * width + "+")
    for i, claim in enumerate([claim1, claim2, claim3, claim4], 1):
        if claim:
            print(f"\nCLAIM {i}. {claim}")
    print("\nAssertions:")
    for name, ok in checks:
        print(f"  [{'ok' if ok else 'FAIL'}] {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
