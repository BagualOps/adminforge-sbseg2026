"""Compute the SSH-key/permission delta between declared state and installed state.

`Planner` is where the paper's declared-vs-real state comparison and the
linear-per-host apply cost originate. `desired_state` expands users, groups
and permissions into a per-host, per-key desired state purely from `IStore`
reads (no network I/O). `calculate_delta` then diffs that desired state
against either the state already persisted on each `Server` (the default,
and the fast "is anything pending?" path, since it touches no host) or an
`atual_override` supplied by the caller (used by `Core` with
`--reconcile` to diff against state fetched live over SSH instead). The
per-host loop inside `calculate_delta` is independent across hosts, which is
what lets `Core.apply` parallelize the subsequent apply step.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from adminforge.domain import (
    PermissionLevel,
    CredentialStatus,
    UserStatus,
    SubAction,
    ActionType,
)
from adminforge.exceptions import InvalidState
from adminforge.interfaces.store import IStore


_PRIORIDADE = {PermissionLevel.SHELL: 1, PermissionLevel.SUDO: 2}


def _maior(a: PermissionLevel, b: PermissionLevel) -> PermissionLevel:
    """Return whichever of `a`/`b` outranks the other (`SUDO` beats `SHELL`); ties keep `a`."""
    return a if _PRIORIDADE[a] >= _PRIORIDADE[b] else b


def _merge_profile(
    existente: "InstalledKey | None",
    perm_level: PermissionLevel,
    perm_profile: str | None,
    final_level: PermissionLevel,
) -> str | None:
    """Compute the effective profile when merging a new permission into the existing InstalledKey.

    Rules (validated by parametrized tests):
      - final_level != SUDO              -> None (profile does not apply to SHELL)
      - existente is None                -> incoming profile
      - existente was SHELL              -> incoming profile (incoming is SUDO)
      - incoming is SHELL                -> keep the existing SUDO profile
      - both SUDO, one without profile   -> None (full sudo wins, least restriction)
      - both SUDO with profile           -> keep the existing profile (stable)
    """
    if final_level != PermissionLevel.SUDO:
        return None
    if existente is None:
        return perm_profile
    if existente.level != PermissionLevel.SUDO:
        return perm_profile
    if perm_level != PermissionLevel.SUDO:
        return existente.profile
    if existente.profile is None or perm_profile is None:
        return None
    return existente.profile


@dataclass(frozen=True)
class InstalledKey:
    """One SSH credential installed for one user, at one permission level, on one host.

    Used both for the desired state built by `Planner.desired_state` and the
    installed state read from `Server.installed_keys` or a live
    inspection (`Core._atual_vivo`); `calculate_delta` compares instances of
    the two by field equality to detect drift. Frozen because instances are
    used as dict values keyed by `ref` and are expected to be replaced, not
    mutated in place, whenever their level or profile changes.
    """

    ref: str
    username: str
    level: PermissionLevel
    profile: str | None = None

    @classmethod
    def de_dict(cls, d: dict) -> "InstalledKey":
        """Reconstruct a `InstalledKey` from the dict form persisted in `Server.installed_keys`.

        `username` and `level` fall back to being derived from `ref` and to
        `PermissionLevel.SHELL` respectively when the dict omits them, which
        happens for records written before those fields existed.
        """
        return cls(
            ref=d["ref"],
            username=d.get("username") or d["ref"].split(":", 1)[0],
            level=PermissionLevel(d.get("level", "shell")),
            profile=d.get("profile"),
        )

    def para_dict(self) -> dict:
        """Serialize back to the dict form persisted in `Server.installed_keys`, omitting `profile` entirely instead of writing a null when it is `None`."""
        out = {"ref": self.ref, "username": self.username, "level": self.level.value}
        if self.profile is not None:
            out["profile"] = self.profile
        return out


class Planner:
    """Diffs the store's declared access state against installed state, on behalf of `Core`.

    Holds only the `IStore` needed to read users, groups, permissions,
    credentials and servers; has no knowledge of SSH or the deployer, which
    keeps `desired_state` and the default path of `calculate_delta` free of
    network I/O and therefore fast regardless of fleet size.
    """

    def __init__(self, store: IStore):
        """Store the `IStore` used to read users, groups, permissions, credentials and servers."""
        self.store = store

    def desired_state(self) -> dict[str, dict[str, InstalledKey]]:
        """Expand every active permission into the desired `InstalledKey` for each (host, credential) pair, from store reads alone.

        For each permission, walks every active member of its user-group,
        every active credential of each such user, and every server in its
        server-group. When the same (host, ref) pair is reachable through
        more than one granted permission — e.g. two groups both giving a user
        access to the same host — the levels are merged upward via `_maior`
        (`SUDO` wins over `SHELL`) and the resulting sudo profile is resolved
        by `_merge_profile`, rather than one permission's result simply
        overwriting the other's. A dangling reference (a permission naming a
        deleted group, a group member who is inactive or no longer exists, a
        server no longer registered) is silently skipped rather than treated
        as an error: the store is the source of truth, so a stale reference
        just yields less desired state, not a failure.
        """
        users = {u.username: u for u in self.store.list_users() if u.status == UserStatus.ACTIVE}
        creds_por_user = {
            u: [c for c in self.store.list_credentials(u) if c.status == CredentialStatus.ACTIVE]
            for u in users
        }
        user_groups = {g.name: g for g in self.store.list_user_groups()}
        server_groups = {g.name: g for g in self.store.list_server_groups()}
        valid_servers = {s.hostname for s in self.store.list_servers()}

        desejado: dict[str, dict[str, InstalledKey]] = defaultdict(dict)
        for perm in self.store.list_permissions():
            gu = user_groups.get(perm.user_group)
            gs = server_groups.get(perm.server_group)
            if not gu or not gs:
                continue
            for username in gu.members:
                if username not in users:
                    continue
                for cred in creds_por_user.get(username, []):
                    ref = cred.reference
                    for hostname in gs.members:
                        if hostname not in valid_servers:
                            continue
                        existente = desejado[hostname].get(ref)
                        level = perm.level if existente is None else _maior(existente.level, perm.level)
                        profile = _merge_profile(existente, perm.level, perm.profile, level)
                        desejado[hostname][ref] = InstalledKey(
                            ref=ref, username=username, level=level, profile=profile
                        )
        return desejado

    def calculate_delta(
        self,
        force: bool = False,
        atual_override: dict[str, dict[str, "InstalledKey"]] | None = None,
    ) -> list[SubAction]:
        """Diff desired state against installed state and return the `SubAction` list needed to reconcile them, sorted deterministically.

        This is the check the paper calls "is anything pending?": by default
        (no `atual_override`), the installed side is read entirely from
        `Server.installed_keys` already in the store, so the whole
        computation is local and touches no host. `atual_override` lets the
        caller substitute state fetched live over SSH instead (used for
        `--reconcile`). `force=True` discards, per host, any
        currently-installed key that is also desired, so every desired key is
        re-emitted as an add even if the store believes it is already
        installed — used to repair state that has drifted without a live
        `--reconcile`. A key is judged divergent if it is missing, installed
        at the wrong permission level, or installed with the wrong sudo
        profile. Profile command lists are resolved once per profile name via
        a local cache and raise `InvalidState` if the referenced profile is
        missing or has no commands, so a dangling or emptied profile can
        never silently degrade into unrestricted sudo. The result is sorted
        by (host, action, credential) so `Core.apply` groups it by host
        deterministically and repeated runs against the same state produce
        identical subaction ordering.
        """
        desejado = self.desired_state()
        sub_actions: list[SubAction] = []

        # cache profiles to avoid re-reading on every subaction
        profiles_cache: dict[str, list[str] | None] = {}

        def _commands(profile: str | None) -> list[str] | None:
            """None  = no profile (legitimate NOPASSWD:ALL).
            Non-empty list = resolved profile.
            Raises InvalidState if the referenced profile does not exist or is empty
            (avoids silently becoming full sudo)."""
            if profile is None:
                return None
            if profile not in profiles_cache:
                p = self.store.get_sudo_profile(profile)
                profiles_cache[profile] = list(p.commands) if p else None
            commands = profiles_cache[profile]
            if commands is None:
                raise InvalidState(
                    f"sudo-profile '{profile}' referenced but not found in state"
                )
            if not commands:
                raise InvalidState(
                    f"sudo-profile '{profile}' has no commands; refusing to apply"
                )
            return commands

        for server in self.store.list_servers():
            alvo = desejado.get(server.hostname, {})
            if atual_override is not None and server.hostname in atual_override:
                atual = dict(atual_override[server.hostname])
            else:
                atual = {}
                for item in server.installed_keys:
                    if isinstance(item, str):
                        ch = InstalledKey(
                            ref=item,
                            username=item.split(":", 1)[0],
                            level=PermissionLevel.SHELL,
                        )
                    else:
                        ch = InstalledKey.de_dict(item)
                    atual[ch.ref] = ch
                if force:
                    atual = {r: c for r, c in atual.items() if r not in alvo}

            for ref, esperado in alvo.items():
                cred = self.store.get_credential_by_fingerprint(esperado.ref.split(":", 1)[1])
                public_key = cred.public_key if cred else ""
                installed = atual.get(ref)
                divergente = (
                    installed is None
                    or installed.level != esperado.level
                    or installed.profile != esperado.profile
                )
                if divergente:
                    sub_actions.append(
                        SubAction(
                            server=server.hostname,
                            action=ActionType.ADD_KEY,
                            credential=ref,
                            public_key=public_key,
                            username=esperado.username,
                            level=esperado.level,
                            profile=esperado.profile,
                            profile_commands=_commands(esperado.profile),
                        )
                    )

            for ref, installed in atual.items():
                if ref not in alvo:
                    sub_actions.append(
                        SubAction(
                            server=server.hostname,
                            action=ActionType.REMOVE_KEY,
                            credential=ref,
                            username=installed.username,
                            level=installed.level,
                        )
                    )

        sub_actions.sort(key=lambda s: (s.server, s.action.value, s.credential or ""))
        return sub_actions
