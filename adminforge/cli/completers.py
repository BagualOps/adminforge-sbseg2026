"""Completers dinamicos para argcomplete: leem o state/ e devolvem opcoes."""
from __future__ import annotations

import json
import os
from pathlib import Path


def _state_dir(parsed_args) -> Path:
    if parsed_args is not None and getattr(parsed_args, "state", None):
        return Path(parsed_args.state)
    return Path(os.environ.get("ADMINFORGE_STATE", "./state"))


def _stems(directory: Path, prefix: str) -> list[str]:
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json") if p.stem.startswith(prefix))


def usernames(prefix="", parsed_args=None, **_):
    return _stems(_state_dir(parsed_args) / "users", prefix)


def hostnames(prefix="", parsed_args=None, **_):
    return _stems(_state_dir(parsed_args) / "servers", prefix)


def user_groups(prefix="", parsed_args=None, **_):
    return _stems(_state_dir(parsed_args) / "user-groups", prefix)


def server_groups(prefix="", parsed_args=None, **_):
    return _stems(_state_dir(parsed_args) / "server-groups", prefix)


def fingerprints(prefix="", parsed_args=None, **_):
    out: list[str] = []
    users_dir = _state_dir(parsed_args) / "users"
    if not users_dir.is_dir():
        return out
    for arquivo in users_dir.glob("*.json"):
        try:
            data = json.loads(arquivo.read_text(encoding="utf-8"))
        except Exception:
            continue
        for c in data.get("credenciais", []):
            fp = c.get("fingerprint", "")
            if fp.startswith(prefix):
                out.append(fp)
    return sorted(set(out))
