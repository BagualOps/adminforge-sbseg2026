#!/usr/bin/env bash
# Claim #1: apply cost is a constant per host (scales linearly with the fleet),
# and AdminForge answers "is anything pending?" from local state, far faster
# than an Ansible re-run that must reconnect to every host.
#
# Measures LIVE on this machine (results go to a fresh temp dir, never the
# committed reference numbers). Two parts:
#   (a) scalability: reduced ladder N=1 and N=5 (1 rep) via infra/perf/run_e1;
#       checks the per-host cold-apply cost is flat and the no-op is near-instant.
#   (b) Ansible comparison: N=10 (1 rep) via infra/perf/run_e2; the Ansible
#       control node runs as a container (no ansible on the host), against the
#       same fleet; checks AdminForge's no-change apply is far below Ansible's
#       equivalent re-run.
# Host tools: git, docker, python3, ssh/ssh-keygen. First run pulls the base
# image and builds the fleet/ansible images; requires Docker and internet.
# Wall-clock times scale with CPU speed; the assertions are ratios/thresholds.
set -euo pipefail
cd "$(dirname "$0")"

WORK=$(mktemp -d)
RAW="$WORK/raw"                       # live results, isolated from committed data
mkdir -p "$RAW"
export PERF_WORK="$WORK"
export PERF_RESULTS_RAW="$RAW"
cleanup() {
  PERF_WORK="$WORK" python3 -c "import sys;sys.path.insert(0,'infra/perf');import perflib as P;P.fleet_down()" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "Claim #1 (a): scalability ladder (N=1, N=5), measured live..."
python3 infra/perf/run_e1.py --sizes 1,5 --reps 1 >/dev/null

echo "Claim #1 (b): Ansible comparison (N=10), measured live..."
python3 infra/perf/run_e2.py --reps 1 --configs 10:default >/dev/null

python3 - "$RAW" <<'PYEOF'
import json, sys, pathlib
raw = pathlib.Path(sys.argv[1])
load = lambda name: json.loads((raw / name).read_text())

e1_1 = load("e1_n01_rep1.json")["cells"]
e1_5 = load("e1_n05_rep1.json")["cells"]
c1, noop1 = e1_1["cold_apply"], e1_1["noop_apply"]
c5, noop5 = e1_5["cold_apply"], e1_5["noop_apply"]
ph1, ph5 = c1 / 1, c5 / 5
diff = abs(ph5 - ph1) / max(ph1, ph5) * 100

ans = load("e2_n10_forksdefault_rep1.json")
af = load("e2_af_sanity_python3_image.json")["cells"]
ans_first, ans_noop = ans["cells"]["first_apply"], ans["cells"]["noop_apply"]
af_first, af_noop = af["cold_apply_parallel"], af["noop_apply"]
yaml_lines = sum(ans["effort"].values())
ratio = ans_noop / af_noop if af_noop else float("inf")

ok_scale = diff < 40 and noop5 < 2
ok_ansible = ratio > 5 and af_noop < 2
ok = ok_scale and ok_ansible
v = "OK" if ok else "FAIL"
bar = "=" * 70
print(f"""
{bar}
  Claim #1: linear per-host cost, and instant "is anything pending?"
{bar}
  (a) Scalability (base image, measured live)
      N=1  cold apply : {c1:6.1f} s     no-op apply : {noop1:.2f} s
      N=5  cold apply : {c5:6.1f} s     no-op apply : {noop5:.2f} s
      Per-host cold   : N=1 {ph1:.1f} s/host   N=5 {ph5:.1f} s/host   (diff {diff:.1f}%)

  (b) Comparison with Ansible at N=10 (python3 image, measured live)
      First apply     : AdminForge {af_first:6.1f} s (parallel)   Ansible {ans_first:6.1f} s
      No-op re-run    : AdminForge {af_noop:6.2f} s (local)      Ansible {ans_noop:6.2f} s   ({ratio:.0f}x faster)
      Write effort    : AdminForge 29 commands    Ansible {yaml_lines} lines of YAML

  Assertions (hardware-independent):
    per-host cold flat (<40% diff)                         -> {"OK" if diff<40 else "FAIL"}
    no-op apply < 2 s                                      -> {"OK" if noop5<2 else "FAIL"}
    AdminForge no-op >= 5x faster than Ansible re-run      -> {"OK" if ratio>5 else "FAIL"}
  Overall  ->  {v}
{bar}""")
sys.exit(0 if ok else 1)
PYEOF
