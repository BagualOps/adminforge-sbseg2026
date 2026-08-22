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
# Host tools: git, docker, python3, ssh/ssh-keygen (checked below; GNU time optional). First run pulls the base
# image and builds the fleet/ansible images; requires Docker and internet.
# Wall-clock times scale with CPU speed; the assertions are ratios/thresholds.
set -euo pipefail
cd "$(dirname "$0")"

# --dry-run: check the comparison logic without Docker. It feeds the stored
# reference measurements to the same assertion block the live run uses, so the
# thresholds and the arithmetic are exercised end to end; what it does NOT do is
# measure this machine. Use it to see what the claim asserts, not to confirm it.
DRY=0
case "${1:-}" in
  --dry-run) DRY=1 ;;
  "") ;;
  *) echo "usage: $0 [--dry-run]" >&2; exit 2 ;;
esac

if [ "$DRY" -eq 1 ]; then
  RAW="infra/perf/results/raw"
  echo "Claim #1 --dry-run: no Docker, no measurement; reading stored reference results."
else

# Every external tool this claim shells out to, checked before anything is built, so a
# missing one names itself here instead of surfacing as a traceback ten minutes in.
missing=""
for t in git docker python3 ssh ssh-keygen; do
  command -v "$t" >/dev/null 2>&1 || missing="$missing $t"
done
if [ -n "$missing" ]; then
  echo "missing required tool(s):$missing" >&2
  # A tool name is not a package name -- ssh-keygen ships inside openssh-client, so
  # echoing the tool list back as an apt line hands the evaluator a command that
  # cannot succeed. Map each tool to the package of the manager actually present.
  if   command -v apt-get >/dev/null 2>&1; then mgr="sudo apt-get update && sudo apt-get install -y"; d=apt
  elif command -v dnf     >/dev/null 2>&1; then mgr="sudo dnf install -y";                            d=dnf
  elif command -v pacman  >/dev/null 2>&1; then mgr="sudo pacman -Sy --needed";                       d=pacman
  elif command -v zypper  >/dev/null 2>&1; then mgr="sudo zypper install -y";                         d=zypper
  else mgr=""; d=other; fi
  pkgs=""
  for t in $missing; do
    case "$t/$d" in
      docker/apt)                  p=docker.io ;;
      docker/*)                    p=docker ;;
      python3/pacman)              p=python ;;
      python3/*)                   p=python3 ;;
      ssh/apt|ssh-keygen/apt)      p=openssh-client ;;
      ssh/pacman|ssh-keygen/pacman) p=openssh ;;
      ssh/*|ssh-keygen/*)          p=openssh-clients ;;
      *)                           p=$t ;;
    esac
    case " $pkgs " in *" $p "*) ;; *) pkgs="$pkgs $p" ;; esac
  done
  if [ -n "$mgr" ]; then echo "  $mgr$pkgs" >&2
  else echo "  install the equivalent of:$pkgs" >&2; fi
  exit 1
fi
docker info >/dev/null 2>&1 || { echo "docker is installed but not usable by this user." >&2
  echo "  start it (sudo systemctl start docker) or add yourself: sudo usermod -aG docker \$USER" >&2; exit 1; }
# GNU time is optional: it only fills the peak-memory column. Without it the run
# proceeds and that column reads "n/a"; no assertion depends on it.
command -v time >/dev/null 2>&1 || [ -x /usr/bin/time ] || \
  echo "note: GNU time not installed, peak-memory column will be blank (sudo apt update && sudo apt install -y time)"

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
fi

python3 - "$RAW" "$DRY" <<'PYEOF'
import json, sys, pathlib
raw = pathlib.Path(sys.argv[1])
dry = sys.argv[2] == "1"
origem = "stored reference results, NOT measured here" if dry else "measured live"
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
if "cold_apply_parallel" in af:
    af_first, rotulo = af["cold_apply_parallel"], "(parallel)"
else:
    af_first, rotulo = af["cold_apply"], "(sequential)"
af_noop = af["noop_apply"]
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
  (a) Scalability (base image, {origem})
      N=1  cold apply : {c1:6.1f} s     no-op apply : {noop1:.2f} s
      N=5  cold apply : {c5:6.1f} s     no-op apply : {noop5:.2f} s
      Per-host cold   : N=1 {ph1:.1f} s/host   N=5 {ph5:.1f} s/host   (diff {diff:.1f}%)

  (b) Comparison with Ansible at N=10 (python3 image, {origem})
      First apply     : AdminForge {af_first:6.1f} s {rotulo}   Ansible {ans_first:6.1f} s
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
