#!/usr/bin/env python3
"""E1 SCALABILITY: AdminForge wall-clock vs fleet size.

For each fleet size N and each repetition (fresh containers per repetition):
  cold_apply        first full apply to an unmanaged fleet
  noop_apply        re-apply with empty delta (idempotence)
  incremental_apply apply after adding 1 admin to a group
  revoke_apply      apply after removing that admin from the group
  history_verify    'history verify' (hash chain check, local)
  audit_all         'audit server --all' (read-only SSH inspection)
  apply_verify      'apply verify' (declared vs real, read-only SSH)

Peak RSS of the AdminForge process is captured with /usr/bin/time -v for
every cold apply (reported for the largest N).

Usage: python3 infra/perf/run_e1.py [--sizes 1,5,10,25,50] [--reps 5]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import perflib as P


def one_rep(n: int, rep: int, keys: dict, extra_key: Path) -> dict:
    P.fleet_down()
    hosts = P.fleet_up(n)
    state = P.WORK_DIR / f"state-e1-n{n:02d}-rep{rep}"
    if state.exists():
        shutil.rmtree(state)
    cell: dict = {"n": n, "rep": rep, "cells": {}}
    try:
        n_cmds = P.declare_state(state, hosts, keys)
        cell["setup_commands"] = n_cmds

        _, wall, rss = P.af(["apply", "--yes"], state, time_v=True)
        cell["cells"]["cold_apply"] = wall
        cell["cold_apply_peak_rss_kib"] = rss

        _, wall, _ = P.af(["apply", "--yes"], state)
        cell["cells"]["noop_apply"] = wall

        P.af(["user", "add", "--username", "admin11", "--name", "Perf admin11",
              "--email", "admin11@perf.lab", "--key-file", str(extra_key)], state)
        P.af(["user-group", "add-member", "--group", P.SHELL_GROUP,
              "--username", "admin11"], state)
        _, wall, _ = P.af(["apply", "--yes"], state)
        cell["cells"]["incremental_apply"] = wall

        P.af(["user-group", "remove-member", "--group", P.SHELL_GROUP,
              "--username", "admin11"], state)
        _, wall, _ = P.af(["apply", "--yes"], state)
        cell["cells"]["revoke_apply"] = wall

        _, wall, _ = P.af(["history", "verify"], state)
        cell["cells"]["history_verify"] = wall

        _, wall, _ = P.af(["audit", "server", "--all"], state)
        cell["cells"]["audit_all"] = wall

        _, wall, _ = P.af(["apply", "verify"], state)
        cell["cells"]["apply_verify"] = wall
    finally:
        P.fleet_down()
    return cell


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="1,5,10,25,50")
    ap.add_argument("--reps", type=int, default=5)
    args = ap.parse_args()
    sizes = [int(s) for s in args.sizes.split(",")]

    P.build_image()
    keys = P.gen_user_keys(P.WORK_DIR / "userkeys", P.N_ADMINS + 1)
    extra_key = keys.pop("admin11")

    for n in sizes:
        for rep in range(1, args.reps + 1):
            out = P.RESULTS_RAW / f"e1_n{n:02d}_rep{rep}.json"
            if out.exists():
                print(f"[e1] n={n} rep={rep} already done, skipping")
                continue
            print(f"[e1] n={n} rep={rep} ...", flush=True)
            payload = one_rep(n, rep, keys, extra_key)
            P.save_raw(f"e1_n{n:02d}_rep{rep}", payload)
            print(f"[e1] n={n} rep={rep} cells={payload['cells']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
