#!/usr/bin/env bash
# Reivindicacao #3: executed code surface under 4,600 lines, zero third-party
# runtime imports in the base install. Deterministic; no Docker; ~5 s.
set -euo pipefail
cd "$(dirname "$0")"

LINES=$(find adminforge -name '*.py' -not -path '*__pycache__*' -print0 | xargs -0 cat | wc -l)

THIRD=$(PYTHONPATH=. python3 - <<'PY'
import sys
base = set(sys.modules)
import adminforge.cli.main  # noqa: F401  (imports every runtime module)
allowed = {"adminforge", "setuptools", "pkg_resources", "_distutils_hack", "_virtualenv"}
third = sorted({
    (name.split(".")[0])
    for name, mod in sys.modules.items()
    if name not in base
    and getattr(mod, "__file__", None)
    and "site-packages" in (mod.__file__ or "")
    and name.split(".")[0] not in allowed
})
print(",".join(third))
PY
)
[ -z "$THIRD" ] && NTHIRD=0 || NTHIRD=$(echo "$THIRD" | tr ',' '\n' | wc -l)

if [ "$LINES" -lt 4600 ] && [ "$NTHIRD" -eq 0 ]; then VERDICT="OK"; else VERDICT="FAIL"; fi

cat <<EOF
══════════════════════════════════════════════════════════════
  Claim #3: attack surface of the base install
══════════════════════════════════════════════════════════════
  Own source (adminforge/**.py) : ${LINES} lines   (claim: < 4,600)
  Third-party runtime imports   : ${NTHIRD}${THIRD:+  ($THIRD)}   (claim: 0)

  Expected: lines < 4,600 and 0 third-party imports  →  ${VERDICT}
══════════════════════════════════════════════════════════════
EOF
[ "$VERDICT" = "OK" ]
