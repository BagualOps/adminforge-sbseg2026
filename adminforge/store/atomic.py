"""Low-level, dependency-free file I/O primitives shared by the store and auditor layers.

Both helpers fsync before returning, so data is durable on disk (not just
sitting in the OS page cache) once the call returns. Neither function takes
a lock: callers that may write the same path concurrently are responsible
for their own serialization (see ``JsonStore.lock``/``unlock``).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_atomic(path: Path, content: str, mode: int = 0o600) -> None:
    """Replace the contents of ``path`` with ``content`` as a single atomic step.

    Writes to a temp file created in ``path``'s own directory (so the final
    swap is a same-filesystem rename, never a cross-device copy), fsyncs it,
    then calls ``os.replace`` to swap it onto ``path`` in one syscall. If the
    process dies at any point before that final rename, ``path`` is left
    exactly as it was before the call — readers can never observe a
    partially written file. On any exception the temp file is removed before
    the exception is re-raised.
    """
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
    """Append one line to ``path``, creating the file first if needed, then fsync.

    Unlike ``write_atomic`` this does not go through a temp-file swap: it
    opens ``path`` in append mode and writes directly. A crash mid-write can
    therefore in principle leave a truncated trailing line, but it can never
    corrupt or rewrite bytes already committed by earlier calls — the file
    is strictly append-only. There is no locking here; the audit log that
    uses this relies on its caller to prevent interleaved writers.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch(mode=mode)
    with path.open("a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")
        f.flush()
        os.fsync(f.fileno())
