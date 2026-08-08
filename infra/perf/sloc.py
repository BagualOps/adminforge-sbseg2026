"""Count the executed code surface of a Python package, in lines.

Claim #3 is about the code a reader has to audit and the interpreter has to run,
so this counts statements only: blank lines, `#` comments and docstrings are all
documentation, not executed code, and none of them is counted. Counting
docstrings would make the measured surface grow every time the package is better
documented, which is the opposite of what the claim is about.

Usage: python3 infra/perf/sloc.py <package-dir>
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def docstring_lines(tree: ast.AST) -> set[int]:
    """Return the 1-based line numbers occupied by docstrings in `tree`.

    A docstring is the first statement of a module, class or function when that
    statement is a bare string literal. Multi-line docstrings contribute every
    line they span, not just the line they start on.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


def count_file(path: Path) -> int:
    """Return the number of executed code lines in a single source file.

    A file that does not parse is reported on stderr and counted as zero rather
    than aborting the whole measurement, so one bad file cannot silently turn a
    partial count into the published number.
    """
    source = path.read_text(encoding="utf-8")
    try:
        skip = docstring_lines(ast.parse(source))
    except SyntaxError as exc:
        print(f"sloc: cannot parse {path}: {exc}", file=sys.stderr)
        return 0
    total = 0
    for number, line in enumerate(source.splitlines(), start=1):
        if number in skip:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        total += 1
    return total


def count_tree(root: Path) -> int:
    """Return the executed code lines of every `*.py` under `root`, caches aside."""
    return sum(
        count_file(p)
        for p in sorted(root.rglob("*.py"))
        if "__pycache__" not in p.parts
    )


def main(argv: list[str]) -> int:
    """Print the executed line count of the package given as the only argument."""
    if len(argv) != 2:
        print("usage: sloc.py <package-dir>", file=sys.stderr)
        return 2
    root = Path(argv[1])
    if not root.is_dir():
        print(f"sloc: not a directory: {root}", file=sys.stderr)
        return 2
    print(count_tree(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
