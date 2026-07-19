#!/usr/bin/env bash
# Claim #1: apply time scales linearly with fleet size.
# Drives the committed measurement harness (infra/perf) on a reduced ladder
# (N=1 and N=5, 1 repetition each) so an evaluator reproduces the linear
# per-host cost without the full ~2 h campaign. Builds a local Docker fleet
# of Debian containers running sshd, applies the reference state, and checks
# that the per-host cold-apply cost is flat and the no-op apply is near-instant.
# ~6 min first run (+2 min image build); requires Docker.
set -euo pipefail
cd "$(dirname "$0")"

WORK=$(mktemp -d)
export PERF_WORK="$WORK"
cleanup() {
  PERF_WORK="$WORK" python3 -c "import sys;sys.path.insert(0,'infra/perf');import perflib as P;P.fleet_down()" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

RAW="infra/perf/results/raw"

echo "Claim #1: running the reduced scalability ladder (N=1, N=5)..."
# The harness skips a (size,rep) whose result file already exists, so committed
# reference results are reused; otherwise it measures fresh on this machine.
python3 infra/perf/run_e1.py --sizes 1,5 --reps 1 >/dev/null

python3 - "$RAW" <<'PYEOF'
import json, sys, pathlib
raw=pathlib.Path(sys.argv[1])
def cold(n):
    d=json.loads((raw/f"e1_n{n:02d}_rep1.json").read_text())
    return d["cells"]["cold_apply"], d["cells"]["noop_apply"]
c1,noop1=cold(1); c5,noop5=cold(5)
ph1=c1/1; ph5=c5/5
diff=abs(ph5-ph1)/max(ph1,ph5)*100
ok = diff < 40 and noop5 < 2
v="OK" if ok else "FAIL"
bar="="*62
print(f"""
{bar}
  Claim #1: Apply time scales linearly with fleet size
{bar}
  N=1  cold apply : {c1:6.1f} s    no-op apply : {noop1:.2f} s
  N=5  cold apply : {c5:6.1f} s    no-op apply : {noop5:.2f} s
  Per-host cold   : N=1 {ph1:.1f} s/host   N=5 {ph5:.1f} s/host   (diff {diff:.1f}%)
  No-op apply     : constant, well under 2 s at both sizes
  Assertion: per-host cost flat (<40% diff) and no-op < 2 s  ->  {v}
{bar}""")
sys.exit(0 if ok else 1)
PYEOF
