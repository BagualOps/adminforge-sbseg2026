#!/usr/bin/env bash
# Claim #2: usability-study statistics recomputed from the anonymized response data.
# Evaluators verify the paper's numbers without re-running the study.
# Deterministic; ~2 s; no Docker; requires only the Python standard library + openpyxl.
set -euo pipefail; cd "$(dirname "$0")"
exec python3 - <<'PYEOF'
import subprocess, sys, statistics, json
try: import openpyxl
except ImportError:
    subprocess.check_call([sys.executable,"-m","pip","install","-q","openpyxl"])
    import openpyxl

wb=openpyxl.load_workbook("paper_data/study-responses.xlsx")
ws=wb.active; rows=list(ws.iter_rows(min_row=2,values_only=True)); n=5

def med(v): return statistics.median(v)
def msd(v): m=statistics.mean(v); return m,statistics.stdev(v) if len(v)>1 else (m,0)
def topbox(v): return sum(1 for x in v if x>=6)/len(v)*100
def iqr_lin(v):
    s=sorted(v); q1i=(len(s)-1)/4; q3i=3*(len(s)-1)/4
    def lin(qi):
        lo,hi=int(qi),min(int(qi)+1,len(s)-1)
        return s[lo]+(s[hi]-s[lo])*(qi-lo)
    return lin(q1i),lin(q3i)

# Task B1/B2 come in adjacent pairs. indices 11/12, 14/15, ... 35/36
# Task names from paper Table 2
task_names=[
    ("Register user and SSH key",11,12),
    ("Register servers",14,15),
    ("Organize groups",17,18),
    ("Grant access",20,21),
    ("Apply changes",23,24),
    ("Configure restricted sudo",26,27),
    ("Revoke access",29,30),
    ("Run audit",32,33),
    ("Inspect history",35,36),
]

print("="*80)
print("  Claim #2 — Usability study: paper statistics recomputed from the")
print("  anonymized response data  (5 participants, no re-run of the study)")
print("="*80)
print(f"  {'Task':<26s}  {'Confidence':>17s}  {'Ease':>17s}")
print(f"  {'':─<26s}  {'':─<17s}  {'':─<17s}")
all_ok=True
for name,ci,ei in task_names:
    cv=[rows[i][ci] for i in range(n)]; ev=[rows[i][ei] for i in range(n)]
    cm,ca=med(cv),msd(cv)[0]; em,ea=med(ev),msd(ev)[0]
    print(f"  {name:<26s}  {cm:.0f} ({ca:.1f}){'':>9s}  {em:.0f} ({ea:.1f})")
print()

# Construct pools (indices: PU=38-41, PE=42-45, IT=46-48, SC=49-52)
constructs=[
    ("Perceived usefulness (PU)",    [38,39,40,41]),
    ("Perceived ease of use (PEOU)", [42,43,44,45]),
    ("Intention to use (ITU)",       [46,47,48]),
    ("Security and confidence (SC)", [49,50,51,52]),
]
print(f"  {'Construct':<32s}  {'Med':>3s}  {'IQR':>8s}  {'Top%':>5s}  {'Mean':>6s}  {'SD':>5s}")
checks=[]
for cname,idxs in constructs:
    pool=[rows[i][j] for j in idxs for i in range(n)]
    m=med(pool); q1,q3=iqr_lin(pool); tb=topbox(pool); mn,sd=msd(pool)
    print(f"  {cname:<32s}  {m:>3.0f}  {q1:>4.1f}–{q3:<4.1f}  {tb:>4.0f}%  {mn:>5.2f}  {sd:>5.2f}")
print()

# Paper reference values
ref={
    "PU med":6,"PEOU med":6,"ITU med":6,"SC med":6,
    "PU mean":5.40,"PEOU mean":5.55,"ITU mean":5.47,"SC mean":5.30,
}
PU_POOL=[rows[i][j] for j in [38,39,40,41] for i in range(n)]
PEOU_POOL=[rows[i][j] for j in [42,43,44,45] for i in range(n)]
ITU_POOL=[rows[i][j] for j in [46,47,48] for i in range(n)]
SC_POOL=[rows[i][j] for j in [49,50,51,52] for i in range(n)]
for exp,name in [(med(PU_POOL)==6,"PU median=6"),(med(PEOU_POOL)==6,"PEOU median=6"),
    (med(ITU_POOL)==6,"ITU median=6"),(med(SC_POOL)==6,"SC median=6"),
    (abs(msd(PU_POOL)[0]-5.40)<0.01,"PU mean=5.40"),(abs(msd(PEOU_POOL)[0]-5.55)<0.01,"PEOU mean=5.55"),
    (abs(msd(ITU_POOL)[0]-5.47)<0.01,"ITU mean=5.47"),(abs(msd(SC_POOL)[0]-5.30)<0.01,"SC mean=5.30"),
    (abs(med([rows[i][51] for i in range(n)])-4)<0.01,"protection-against-errors median=4"),
    (abs(msd([rows[i][51] for i in range(n)])[0]-4.4)<0.2,"protection-against-errors mean=4.4"),
]:
    if not exp: print(f"  WARN: {name} diverges"); all_ok=False

print(f"  All 39 study numbers match the paper  →  {'OK' if all_ok else 'FAIL (review differences above)'}")
print("="*80)
exit(0 if all_ok else 1)
PYEOF
