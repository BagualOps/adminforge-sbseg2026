from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_atomic(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def append_line(path: Path, line: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch(mode=mode)
    with path.open("a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")
        f.flush()
        os.fsync(f.fileno())
