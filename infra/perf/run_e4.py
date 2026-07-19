#!/usr/bin/env python3
"""E4 PARALLELISM: apply, verify and audit with per-host fan-out (--jobs 25).

For each fleet size N and each repetition (fresh containers per repetition),
measures the operations that touch every host, run in parallel with a fixed
pool of 25 (--jobs 25), so they can be compared against the sequential figures
of E1:
  cold_apply_parallel   first full apply to an unmanaged fleet
  noop_apply_parallel   re-apply with empty delta
  verify_parallel       'apply verify' (declared vs real, read-only SSH)
  audit_parallel        'audit server --all' (read-only SSH inspection)

Usage: python3 infra/perf/run_e4.py [--sizes 5,10,25,50] [--reps 5]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import perflib as P

JOBS = 25


def one_rep(n: int, rep: int, keys: dict) -> dict:
    P.fleet_down()
    hosts = P.fleet_up(n)
    state = P.WORK_DIR / f"state-e4-n{n:02d}-rep{rep}"
    if state.exists():
        shutil.rmtree(state)
    cell: dict = {"n": n, "rep": rep, "jobs": JOBS, "cells": {}}
    try:
        P.declare_state(state, hosts, keys)
        _, wall, rss = P.af(["apply", "--yes", "--jobs", str(JOBS)], state, time_v=True)
        cell["cells"]["cold_apply_parallel"] = wall
        cell["cold_apply_peak_rss_kib"] = rss
        _, wall, _ = P.af(["apply", "--yes", "--jobs", str(JOBS)], state)
        cell["cells"]["noop_apply_parallel"] = wall
        _, wall, _ = P.af(["apply", "verify", "--jobs", str(JOBS)], state, check=False)
        cell["cells"]["verify_parallel"] = wall
        _, wall, _ = P.af(["audit", "server", "--all", "--jobs", str(JOBS)], state, check=False)
        cell["cells"]["audit_parallel"] = wall
    finally:
        P.fleet_down()
    return cell


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="5,10,25,50")
    ap.add_argument("--reps", type=int, default=5)
    args = ap.parse_args()
    sizes = [int(s) for s in args.sizes.split(",")]

    P.build_image()
    keys = P.gen_user_keys(P.WORK_DIR / "userkeys", P.N_ADMINS + 1)
    keys.pop("admin11", None)

    for n in sizes:
        for rep in range(1, args.reps + 1):
            out = P.RESULTS_RAW / f"e4_n{n:02d}_rep{rep}.json"
            if out.exists():
                print(f"[e4] n={n} rep={rep} already done, skipping")
                continue
            print(f"[e4] n={n} rep={rep} ...", flush=True)
            payload = one_rep(n, rep, keys)
            P.save_raw(f"e4_n{n:02d}_rep{rep}", payload)
            print(f"[e4] n={n} rep={rep} cells={payload['cells']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
