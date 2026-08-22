"""Dynamic completers for argcomplete: read the state/ dir and return options."""
from __future__ import annotations

import json
import os
from pathlib import Path


def _state_dir(parsed_args) -> Path:
    """Resolve the state directory to complete against.

    Prefers the ``--state`` value already parsed on the command line (so
    completion matches the same state the command will actually run against),
    falling back to $ADMINFORGE_STATE and then ``./state``.
    """
    if parsed_args is not None and getattr(parsed_args, "state", None):
        return Path(parsed_args.state)
    return Path(os.environ.get("ADMINFORGE_STATE", "./state"))


def _stems(directory: Path, prefix: str) -> list[str]:
    """List filename stems (JSON records) under `directory` that start with `prefix`.

    Reads the state directory directly from disk rather than going through the
    Store, so it stays cheap enough to run on every keystroke; returns an
    empty list instead of raising when the directory does not exist yet.
    """
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json") if p.stem.startswith(prefix))


def usernames(prefix="", parsed_args=None, **_):
    """Complete --username values from usernames declared in state/users/."""
    return _stems(_state_dir(parsed_args) / "users", prefix)


def hostnames(prefix="", parsed_args=None, **_):
    """Complete --hostname values from servers declared in state/servers/."""
    return _stems(_state_dir(parsed_args) / "servers", prefix)


def user_groups(prefix="", parsed_args=None, **_):
    """Complete --group/--user-group values from state/user-groups/."""
    return _stems(_state_dir(parsed_args) / "user-groups", prefix)


def server_groups(prefix="", parsed_args=None, **_):
    """Complete --group/--server-group values from state/server-groups/."""
    return _stems(_state_dir(parsed_args) / "server-groups", prefix)


def sudo_profiles(prefix="", parsed_args=None, **_):
    """Complete --profile values from state/sudo-profiles/."""
    return _stems(_state_dir(parsed_args) / "sudo-profiles", prefix)


def fingerprints(prefix="", parsed_args=None, **_):
    """Complete --fingerprint values by scanning every user's stored credentials.

    Unlike the other completers this has to open and parse every JSON file
    under state/users/ (fingerprints are nested inside each user record, not
    encoded in a filename), so it is the most expensive completer here.
    """
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
