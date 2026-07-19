#!/usr/bin/env python3
"""Aggregate raw per-repetition JSON into results/results.json.

For every experiment cell, reports median, min and max over the
repetitions, plus hardware info, peak RSS, configuration effort and
the E3 attack-surface verdicts.

Usage: python3 infra/perf/aggregate.py
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import perflib as P


def summarize(values: list[float]) -> dict:
    return {
        "median_s": round(statistics.median(values), 3),
        "min_s": round(min(values), 3),
        "max_s": round(max(values), 3),
        "reps": len(values),
    }


def main() -> int:
    raws = sorted(P.RESULTS_RAW.glob("*.json"))
    if not raws:
        print("no raw results found; run the experiments first", file=sys.stderr)
        return 1

    e1: dict = defaultdict(lambda: defaultdict(list))
    e1_rss: dict = defaultdict(list)
    e1_setup_cmds: dict = {}
    e2: dict = defaultdict(lambda: defaultdict(list))
    e2_meta: dict = {}
    e3 = None

    for path in raws:
        data = json.loads(path.read_text())
        name = path.stem
        if name.startswith("e1_"):
            n = data["n"]
            for cell, wall in data["cells"].items():
                e1[n][cell].append(wall)
            if data.get("cold_apply_peak_rss_kib"):
                e1_rss[n].append(data["cold_apply_peak_rss_kib"])
            e1_setup_cmds[n] = data.get("setup_commands")
        elif name.startswith("e2_af_sanity"):
            e2_meta["af_sanity_python3_image"] = data
        elif name.startswith("e2_"):
            key = f"n{data['n']:02d}_forks{data['forks']}"
            for cell, wall in data["cells"].items():
                e2[key][cell].append(wall)
            e2_meta[key] = {"n": data["n"], "forks": data["forks"],
                            "ansible_version": data.get("ansible_version"),
                            "effort": data.get("effort")}
        elif name.startswith("e3_"):
            e3 = data

    results = {
        "hardware": P.hardware_info(),
        "declared_state": {
            "admins": P.N_ADMINS,
            "admin_groups": 2,
            "sudo_profile_commands": P.SUDO_COMMANDS,
        },
        "e1_scalability": {
            str(n): {
                "cells": {cell: summarize(vals) for cell, vals in sorted(cells.items())},
                "setup_cli_commands": e1_setup_cmds.get(n),
                "cold_apply_peak_rss_mib": (
                    round(max(e1_rss[n]) / 1024, 1) if e1_rss.get(n) else None),
            }
            for n, cells in sorted(e1.items())
        },
        "e2_ansible_comparison": {
            key: {
                "cells": {cell: summarize(vals) for cell, vals in sorted(cells.items())},
                **e2_meta[key],
            }
            for key, cells in sorted(e2.items())
        },
        "e2_af_sanity_python3_image": e2_meta.get("af_sanity_python3_image"),
        "e3_attack_surface": e3,
    }

    out = P.PERF_DIR / "results" / "results.json"
    out.write_text(json.dumps(results, indent=2, sort_keys=False) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
