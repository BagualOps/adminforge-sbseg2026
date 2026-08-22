#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK
"""AdminForge CLI: argparse tree, one `cmd_*` handler per subcommand, and the `main()` entry point.

Commands only ever mutate two things: the local declared state under
`--state` (add/edit/delete/grant/... — always local, never touches a server)
and, for `apply`/`apply verify`/`audit server`, the remote servers over SSH.
Every command's own module docstring in the parser (`_build_parser`) has the
full `--help` text; this module documents the side effects that are not
obvious from `--help` alone.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from adminforge import __version__
from adminforge.cli import completers, ui
from adminforge.core.core import Core
from adminforge.domain import (
    PermissionLevel,
    ActionType,
)
from adminforge.exceptions import LockBusy
from adminforge.i18n import t as _


EPILOG_GERAL = (
    "EXAMPLES\n"
    "  adminforge user add --username marina --name \"Marina Silva\" --email marina@empresa.com --key-file ~/.ssh/marina.pub\n"
    "  adminforge user-group create --name sysadmins\n"
    "  adminforge user-group add-member --group sysadmins --username marina\n"
    "  adminforge server add --hostname web-01 --ip 10.0.0.10 --auto\n"
    "  adminforge server-group create --name producao\n"
    "  adminforge server-group add-member --group producao --hostname web-01\n"
    "  adminforge permission grant --user-group sysadmins --server-group producao --level sudo\n"
    "  adminforge preview\n"
    "  adminforge apply\n"
    "\n"
    "DOCS\n"
    "  Detailed model: docs/modelagem-v1.pdf\n"
    "  Use-case cookbook: docs/USAGE.md\n"
)


def _state_dir(args: argparse.Namespace) -> Path:
    """Return the state directory the current command should act on, from the parsed --state flag."""
    return Path(args.state)


def _superadmin() -> str:
    """Resolve who is running the command, for the history/audit log.

    Prefers $ADMINFORGE_SUPERADMIN, then falls back to $USER, then the
    literal string "unknown" — it never prompts or fails, so audit entries
    are always written even in unusual environments (e.g. cron, containers).
    """
    return os.environ.get("ADMINFORGE_SUPERADMIN") or os.environ.get("USER") or "unknown"


def _split_tokens(items: list[str]) -> list[str]:
    """Accept 'a b c' (space), 'a,b,c' (comma) or mixed. Drop empty items."""
    out: list[str] = []
    for it in items:
        out.extend(s.strip() for s in it.split(",") if s.strip())
    return out


def _emit_listing(
    args: argparse.Namespace,
    headers: list[str],
    lines: list[list[str]],
    json_keys: list[str] | None = None,
    json_data: list[dict] | None = None,
) -> int:
    """Print a listing in the format requested by --format. Default 'table'.
    For 'json', use json_data if provided (richer structure); otherwise, zip(headers, lines)."""
    fmt = getattr(args, "format", "table")
    if fmt == "json":
        if json_data is None:
            keys = json_keys or [h.lower() for h in headers]
            json_data = [dict(zip(keys, line)) for line in lines]
        print(json.dumps(json_data, indent=2, ensure_ascii=False))
        return 0
    ui.tabela(headers, lines)
    return 0


def _core(args: argparse.Namespace, com_ssh: bool = False) -> Core:
    """Build the Core (core domain object) that every command runs against.

    With `com_ssh=True`, also wires a real SSHDeployer so the command can
    reach remote servers — needed only by `apply`, `apply verify` and
    `audit server`. The SSH private key path, remote service username and
    whether to auto-create the Unix account are read from environment
    variables (ADMINFORGE_SSH_KEY, ADMINFORGE_SSH_USER,
    ADMINFORGE_CREATE_UNIX_USER), not from any CLI flag. With
    `com_ssh=False` (the default), the returned Core can only read/write
    local declared state — it never touches the network.
    """
    deployer = None
    if com_ssh:
        from adminforge.deployer.ssh_deployer import SSHDeployer

        key = os.environ.get("ADMINFORGE_SSH_KEY") or str(Path.home() / ".ssh" / "adminforge_id")
        user = os.environ.get("ADMINFORGE_SSH_USER", "adminforge")
        create_account = os.environ.get("ADMINFORGE_CREATE_UNIX_USER", "true").lower() != "false"
        known_hosts = _state_dir(args) / "known_hosts"
        deployer = SSHDeployer(
            private_key_path=Path(key),
            known_hosts_path=known_hosts,
            service_user=user,
            create_unix_account=create_account,
        )
    return Core.montar(_state_dir(args), deployer=deployer, superadmin=_superadmin())


# ---------------------------------------------------------------------------
# UC-1: user
# ---------------------------------------------------------------------------
def cmd_user_add(args: argparse.Namespace) -> int:
    """Register a new user in local declared state, optionally with an initial SSH key.

    Local only — does not touch any server; the key only reaches servers on
    the next `apply`. If both `--key-file` and `--key-string` are omitted the
    user is created with no key. Returns 2 if `--key-file` cannot be read
    (after the user record has already been created).
    """
    core = _core(args)
    rc = ui.print_result(core.cadastrar_user(args.username, args.name, args.email))
    if rc != 0:
        return rc
    key = getattr(args, "key_string", None)
    if key is None and getattr(args, "key_file", None):
        try:
            key = Path(args.key_file).read_text(encoding="utf-8")
        except OSError as e:
            ui.fail(_("could not read key file {f}: {e}").format(f=repr(args.key_file), e=e))
            return 2
    if key:
        rc = ui.print_result(core.register_key(args.username, key))
    return rc


def cmd_user_list(args: argparse.Namespace) -> int:
    """List all users in local declared state (username, name, email, status)."""
    core = _core(args)
    users = core.store.list_users()
    lines = [[u.username, u.name, u.email, u.status.value] for u in users]
    json_data = [
        {"username": u.username, "name": u.name, "email": u.email, "status": u.status.value}
        for u in users
    ]
    return _emit_listing(args, ["USERNAME", "NAME", "EMAIL", "STATUS"], lines, json_data=json_data)


def cmd_user_show(args: argparse.Namespace) -> int:
    """Print one user's details, all of their credentials and the user-groups they belong to.

    Returns 2 if the username does not exist in local declared state.
    """
    core = _core(args)
    u = core.store.get_user(args.username)
    if not u:
        ui.fail(_("user {u} does not exist").format(u=args.username))
        return 2
    ui.heading(_("User"))
    ui.kv(_("username"), u.username)
    ui.kv(_("name"), u.name)
    ui.kv(_("email"), u.email)
    ui.kv(_("status"), u.status.value)
    creds = core.store.list_credentials(args.username)
    ui.heading(_("Credentials ({n})").format(n=len(creds)))
    ui.tabela(["FINGERPRINT", "STATUS"], [[c.fingerprint, c.status.value] for c in creds])
    groups = [g.name for g in core.store.list_user_groups() if args.username in g.members]
    ui.heading(_("Groups ({n})").format(n=len(groups)))
    if groups:
        ui.echo("  " + ", ".join(groups))
    else:
        ui.secho(_("  (none)"), dim=True)
    return 0


def cmd_user_disable(args: argparse.Namespace) -> int:
    """Disable a user and revoke all of their keys in local declared state.

    Prompts for confirmation unless `--yes`. This only marks the change
    locally — the keys are not actually removed from any server's
    authorized_keys until the next `apply`. Returns 1 if the user cancels
    the prompt.
    """
    if not args.yes and not ui.confirmar(
        _("Disable {u} and revoke their keys? (apply removes them from servers)").format(u=args.username)
    ):
        ui.warn(_("operation cancelled"))
        return 1
    op = _core(args).desabilitar_user(args.username)
    return ui.print_result(op)


def cmd_user_edit(args: argparse.Namespace) -> int:
    """Update a user's name and/or e-mail in local declared state (does not touch keys or servers).

    Requires at least one of `--name`/`--email`; returns 2 if both are omitted.
    """
    if args.name is None and args.email is None:
        ui.fail(_("provide --name and/or --email"))
        return 2
    op = _core(args).editar_user(args.username, name=args.name, email=args.email)
    return ui.print_result(op)


def cmd_user_rename(args: argparse.Namespace) -> int:
    """Rename a user in local declared state, cascading the rename into every user-group membership."""
    op = _core(args).rename_user(args.de, args.para)
    return ui.print_result(op)


# ---------------------------------------------------------------------------
# UC-2: user key
# ---------------------------------------------------------------------------
def cmd_user_key_add(args: argparse.Namespace) -> int:
    """Register an SSH key for a user, from `--file` or `--string` (mutually exclusive).

    Local only; the key is pushed to servers on the next `apply`. Returns 2
    if both or neither of `--file`/`--string` is given, or if `--file`
    cannot be read.
    """
    if args.file and args.string:
        ui.fail(_("use --file OR --string, not both"))
        return 2
    key = args.string
    if args.file:
        try:
            key = Path(args.file).read_text(encoding="utf-8")
        except OSError as e:
            ui.fail(_("could not read key file {f}: {e}").format(f=repr(args.file), e=e))
            return 2
    if not key:
        ui.fail(_("provide --file or --string"))
        return 2
    op = _core(args).register_key(args.username, key)
    return ui.print_result(op)


def cmd_user_key_revoke(args: argparse.Namespace) -> int:
    """Revoke an SSH key by fingerprint in local declared state.

    Local only — the key is not removed from any server's authorized_keys
    until the next `apply`.
    """
    op = _core(args).revoke_key(args.fingerprint)
    return ui.print_result(op)


def cmd_user_key_list(args: argparse.Namespace) -> int:
    """List a user's SSH keys (fingerprint and status) from local declared state."""
    core = _core(args)
    creds = core.store.list_credentials(args.username)
    lines = [[c.fingerprint, c.status.value] for c in creds]
    json_data = [{"fingerprint": c.fingerprint, "status": c.status.value} for c in creds]
    return _emit_listing(args, ["FINGERPRINT", "STATUS"], lines, json_data=json_data)


# ---------------------------------------------------------------------------
# UC-3: user-group
# ---------------------------------------------------------------------------
def cmd_ug_create(args: argparse.Namespace) -> int:
    """Create an empty user-group in local declared state."""
    return ui.print_result(_core(args).create_user_group(args.name))


def cmd_ug_add_member(args: argparse.Namespace) -> int:
    """Add one or more users (space- or comma-separated) to a user-group.

    Local only — membership changes only reach servers through the
    permissions the group holds, on the next `apply`.
    """
    return ui.print_result(_core(args).add_members_user_group(args.group, _split_tokens(args.username)))


def cmd_ug_remove_member(args: argparse.Namespace) -> int:
    """Remove one or more users (space- or comma-separated) from a user-group.

    Local only; affected keys are only revoked from servers on the next
    `apply`.
    """
    return ui.print_result(_core(args).remove_members_user_group(args.group, _split_tokens(args.username)))


def cmd_ug_delete(args: argparse.Namespace) -> int:
    """Delete a user-group from local declared state."""
    return ui.print_result(_core(args).delete_user_group(args.name))


def cmd_ug_rename(args: argparse.Namespace) -> int:
    """Rename a user-group, cascading the rename into every permission that references it."""
    return ui.print_result(_core(args).rename_user_group(args.de, args.para))


def cmd_ug_list(args: argparse.Namespace) -> int:
    """List all user-groups and their members from local declared state."""
    core = _core(args)
    groups = core.store.list_user_groups()
    lines = [[g.name, ", ".join(g.members) or "-"] for g in groups]
    json_data = [{"name": g.name, "members": list(g.members)} for g in groups]
    return _emit_listing(args, ["NAME", "MEMBERS"], lines, json_data=json_data)


# ---------------------------------------------------------------------------
# UC-4: server
# ---------------------------------------------------------------------------
def cmd_server_add(args: argparse.Namespace) -> int:
    """Register a server with a trust-on-first-use (TOFU) host key.

    With `--auto` and no `--host-key`, this connects to the server over SSH
    right away (before any confirmation) to capture its host key — unlike
    every other `cmd_*` in this section, it is not purely local. The
    captured fingerprint is then shown for confirmation before the server is
    actually registered. Returns 2 if capture fails, or if neither
    `--host-key` nor `--auto` is given. Returns 1 if the captured fingerprint
    is not confirmed.
    """
    host_key = args.host_key
    if args.auto and not host_key:
        from adminforge.deployer.ssh_deployer import SSHDeployer

        deployer = SSHDeployer(
            private_key_path=Path("/dev/null"),
            known_hosts_path=_state_dir(args) / "known_hosts",
        )
        try:
            host_key, fp = deployer.capture_host_key(args.hostname, args.ip, args.port)
        except Exception as e:
            ui.fail(_("failed to capture host_key: {e}").format(e=e))
            return 2
        ui.info(_("captured host_key: {fp}").format(fp=fp))
        if not ui.confirmar(_("Confirm the fingerprint?")):
            ui.warn(_("registration aborted"))
            return 1
    if not host_key:
        ui.fail(_("provide --host-key or --auto"))
        return 2
    op = _core(args).register_server(args.hostname, args.ip, args.port, host_key)
    return ui.print_result(op)


def cmd_server_list(args: argparse.Namespace) -> int:
    """List all registered servers (hostname, IPv4, port, number of installed keys)."""
    core = _core(args)
    servers = core.store.list_servers()
    lines = [
        [s.hostname, s.ipv4, str(s.ssh_port), str(len(s.installed_keys))]
        for s in servers
    ]
    json_data = [
        {"hostname": s.hostname, "ipv4": s.ipv4, "port": s.ssh_port,
         "installed_keys": list(s.installed_keys)}
        for s in servers
    ]
    return _emit_listing(args, ["HOSTNAME", "IPV4", "PORT", "KEYS"], lines, json_data=json_data)


def cmd_server_show(args: argparse.Namespace) -> int:
    """Print one server's details and the keys declared as installed on it (per local state, not verified live).

    Returns 2 if the hostname does not exist in local declared state. Use
    `apply verify` or `audit server` to check what is actually on the
    server.
    """
    core = _core(args)
    s = core.store.get_server(args.hostname)
    if not s:
        ui.fail(_("server {h} does not exist").format(h=args.hostname))
        return 2
    ui.heading(_("Server"))
    ui.kv(_("hostname"), s.hostname)
    ui.kv(_("ipv4"), s.ipv4)
    ui.kv(_("port"), str(s.ssh_port))
    ui.kv(_("host_key"), s.host_key[:80] + ("..." if len(s.host_key) > 80 else ""))
    ui.heading(_("Installed keys ({n})").format(n=len(s.installed_keys)))
    lines = []
    for item in s.installed_keys:
        if isinstance(item, dict):
            lines.append([item.get("ref", "?"), item.get("level", "?")])
        else:
            lines.append([str(item), "shell"])
    ui.tabela(["REF", "LEVEL"], lines)
    return 0


def cmd_server_remove(args: argparse.Namespace) -> int:
    """Remove a server from local declared state only — does NOT clean its keys or sudoers on the server itself.

    Prompts for confirmation unless `--yes`; returns 1 if the user cancels.
    """
    if not args.yes and not ui.confirmar(
        _("Remove {h} from AdminForge? (does not clean keys on the server)").format(h=args.hostname)
    ):
        ui.warn(_("operation cancelled"))
        return 1
    return ui.print_result(_core(args).delete_server(args.hostname))


def cmd_server_edit(args: argparse.Namespace) -> int:
    """Update a server's IP, port and/or host_key in local declared state.

    Requires at least one of `--ip`/`--port`/`--host-key`; returns 2 if none
    is given. Rotating `--host-key` changes the key AdminForge trusts for
    this host without re-verifying it (no TOFU capture like `server add
    --auto`) — use with care.
    """
    if args.ip is None and args.port is None and args.host_key is None:
        ui.fail(_("provide --ip, --port and/or --host-key"))
        return 2
    op = _core(args).edit_server(
        args.hostname, ipv4=args.ip, porta=args.port, host_key=args.host_key,
    )
    return ui.print_result(op)


def cmd_server_rename(args: argparse.Namespace) -> int:
    """Rename a server, cascading the rename into every server-group membership."""
    op = _core(args).rename_server(args.de, args.para)
    return ui.print_result(op)


# ---------------------------------------------------------------------------
# UC-5: server-group
# ---------------------------------------------------------------------------
def cmd_sg_create(args: argparse.Namespace) -> int:
    """Create an empty server-group in local declared state."""
    return ui.print_result(_core(args).create_server_group(args.name))


def cmd_sg_add(args: argparse.Namespace) -> int:
    """Add one or more hostnames (space- or comma-separated) to a server-group.

    Local only — reaches servers only through the permissions this group is
    granted, on the next `apply`.
    """
    return ui.print_result(_core(args).add_members_server_group(args.group, _split_tokens(args.hostname)))


def cmd_sg_rm(args: argparse.Namespace) -> int:
    """Remove one or more hostnames (space- or comma-separated) from a server-group.

    Local only; affected keys are only revoked from the removed server on
    the next `apply`.
    """
    return ui.print_result(_core(args).remove_members_server_group(args.group, _split_tokens(args.hostname)))


def cmd_sg_delete(args: argparse.Namespace) -> int:
    """Delete a server-group from local declared state."""
    return ui.print_result(_core(args).delete_server_group(args.name))


def cmd_sg_rename(args: argparse.Namespace) -> int:
    """Rename a server-group, cascading the rename into every permission that references it."""
    return ui.print_result(_core(args).rename_server_group(args.de, args.para))


def cmd_sg_list(args: argparse.Namespace) -> int:
    """List all server-groups and their members from local declared state."""
    core = _core(args)
    groups = core.store.list_server_groups()
    lines = [[g.name, ", ".join(g.members) or "-"] for g in groups]
    json_data = [{"name": g.name, "members": list(g.members)} for g in groups]
    return _emit_listing(args, ["NAME", "MEMBERS"], lines, json_data=json_data)


# ---------------------------------------------------------------------------
# UC-6: permission grant / revoke / list / show
# ---------------------------------------------------------------------------
def cmd_permission_show(args: argparse.Namespace) -> int:
    """Reverse query: 'which servers does X have access to?' (--user) or
    'which grants reach server-group X?' (--server-group) or
    'which servers does user-group X grant?' (--user-group)."""
    core = _core(args)
    s = core.store

    # Useful indices
    user_groups = {g.name: g for g in s.list_user_groups()}
    server_groups = {g.name: g for g in s.list_server_groups()}
    perms = s.list_permissions()

    if args.user:
        user = s.get_user(args.user)
        if not user:
            ui.fail(_("user {u} does not exist").format(u=args.user))
            return 2
        user_groups = sorted(g.name for g in user_groups.values() if args.user in g.members)
        # For each of the user's groups, expand the permissions; aggregate by (hostname).
        from adminforge.planner.planner import _merge_profile, InstalledKey, _maior

        agregado: dict[str, dict] = {}  # hostname -> {level, profile, via}
        for perm in perms:
            if perm.user_group not in user_groups:
                continue
            sg = server_groups.get(perm.server_group)
            if not sg:
                continue
            for hostname in sg.members:
                exist = agregado.get(hostname)
                if exist is None:
                    agregado[hostname] = {
                        "level": perm.level,
                        "profile": perm.profile,
                        "via": [perm.user_group],
                    }
                    continue
                ch = InstalledKey(ref="x", username=args.user, level=exist["level"], profile=exist["profile"])
                new_level = _maior(exist["level"], perm.level)
                novo_profile = _merge_profile(ch, perm.level, perm.profile, new_level)
                agregado[hostname] = {
                    "level": new_level,
                    "profile": novo_profile,
                    "via": exist["via"] + [perm.user_group],
                }

        if getattr(args, "format", "table") == "json":
            print(json.dumps({
                "user": args.user,
                "groups": user_groups,
                "servers": [
                    {
                        "hostname": h,
                        "level": v["level"].value,
                        "profile": v["profile"],
                        "via": sorted(set(v["via"])),
                    }
                    for h, v in sorted(agregado.items())
                ],
            }, indent=2, ensure_ascii=False))
            return 0

        ui.heading(_("User {u}").format(u=args.user))
        ui.kv(_("status"), user.status.value)
        ui.kv("groups", ", ".join(user_groups) if user_groups else _("(none)"))
        ui.heading(_("Effective server access ({n})").format(n=len(agregado)))
        if not agregado:
            ui.secho(_("  (no servers accessible)"), dim=True)
            if not user_groups:
                ui.info(_("user is not in any user-group; try: adminforge user-group add-member --group <g> --username {u}").format(u=args.user))
            return 0
        lines = [
            [h, v["level"].value, v["profile"] or "—", ", ".join(sorted(set(v["via"])))]
            for h, v in sorted(agregado.items())
        ]
        ui.tabela(["HOSTNAME", "LEVEL", "PROFILE", "VIA"], lines)
        return 0

    if args.user_group:
        if args.user_group not in user_groups:
            ui.fail(_("user-group {g} does not exist").format(g=args.user_group))
            return 2
        relevantes = [p for p in perms if p.user_group == args.user_group]
        json_data = [
            {"server_group": p.server_group, "level": p.level.value, "profile": p.profile}
            for p in relevantes
        ]
        if getattr(args, "format", "table") == "json":
            print(json.dumps({"user_group": args.user_group, "grants": json_data}, indent=2))
            return 0
        ui.heading(_("Grants from user-group {ug} ({n})").format(ug=args.user_group, n=len(relevantes)))
        if not relevantes:
            ui.secho(_("  (no grants)"), dim=True)
            return 0
        ui.tabela(
            ["SERVER_GROUP", "LEVEL", "PROFILE"],
            [[p.server_group, p.level.value, p.profile or "—"] for p in relevantes],
        )
        return 0

    if args.server_group:
        if args.server_group not in server_groups:
            ui.fail(_("server-group {g} does not exist").format(g=args.server_group))
            return 2
        relevantes = [p for p in perms if p.server_group == args.server_group]
        if getattr(args, "format", "table") == "json":
            print(json.dumps({
                "server_group": args.server_group,
                "grants": [
                    {"user_group": p.user_group, "level": p.level.value, "profile": p.profile}
                    for p in relevantes
                ],
            }, indent=2))
            return 0
        ui.heading(_("Grants to server-group {sg} ({n})").format(sg=args.server_group, n=len(relevantes)))
        if not relevantes:
            ui.secho(_("  (no grants)"), dim=True)
            return 0
        ui.tabela(
            ["USER_GROUP", "LEVEL", "PROFILE"],
            [[p.user_group, p.level.value, p.profile or "—"] for p in relevantes],
        )
        return 0

    ui.fail(_("provide one of: --user, --user-group, --server-group"))
    return 2


def cmd_permission_list(args: argparse.Namespace) -> int:
    """List all permission grants (user-group -> server-group, level, profile) from local declared state."""
    core = _core(args)
    perms = core.store.list_permissions()
    lines = [
        [p.user_group, p.server_group, p.level.value, p.profile or "—"] for p in perms
    ]
    json_data = [
        {"user_group": p.user_group, "server_group": p.server_group,
         "level": p.level.value, "profile": p.profile}
        for p in perms
    ]
    return _emit_listing(
        args, ["USER_GROUP", "SERVER_GROUP", "LEVEL", "PROFILE"], lines, json_data=json_data
    )


def cmd_permission_grant(args: argparse.Namespace) -> int:
    """Grant access from a user-group to a server-group at `--level` (shell or sudo).

    Local only — new keys/sudoers only land on servers on the next `apply`.
    `--profile` is only meaningful with `--level sudo`; without it, sudo
    grants full NOPASSWD:ALL rather than a restricted command set.
    """
    return ui.print_result(
        _core(args).grant(
            args.user_group, args.server_group, PermissionLevel(args.level),
            profile=getattr(args, "profile", None),
        )
    )


# ---------------------------------------------------------------------------
# sudo-profile
# ---------------------------------------------------------------------------
def cmd_sudo_profile_create(args: argparse.Namespace) -> int:
    """Create a named sudo profile from one or more absolute `--command` paths (repeatable flag).

    Local only; profiles do nothing until granted via `permission grant
    --level sudo --profile <name>` and then applied.
    """
    return ui.print_result(_core(args).create_sudo_profile(args.name, args.command))


def cmd_sudo_profile_list(args: argparse.Namespace) -> int:
    """List sudo profiles with their command count and a truncated preview of the commands."""
    core = _core(args)
    profiles = core.store.list_sudo_profiles()
    lines = []
    for p in profiles:
        commands_str = ", ".join(p.commands)
        if len(commands_str) > 80:
            commands_str = commands_str[:77] + "…"
        lines.append([p.name, str(len(p.commands)), commands_str])
    json_data = [{"name": p.name, "commands": list(p.commands)} for p in profiles]
    return _emit_listing(args, ["NAME", "#CMDS", "COMMANDS"], lines, json_data=json_data)


def cmd_sudo_profile_show(args: argparse.Namespace) -> int:
    """Print every command allowed by a sudo profile, one per line. Returns 2 if the profile does not exist."""
    core = _core(args)
    p = core.store.get_sudo_profile(args.name)
    if not p:
        ui.fail(_("sudo-profile {n} does not exist").format(n=args.name))
        return 2
    ui.heading(_("sudo-profile {n}").format(n=p.name))
    for c in p.commands:
        ui.echo(f"  {c}")
    return 0


def cmd_sudo_profile_delete(args: argparse.Namespace) -> int:
    """Delete a sudo profile. Fails (non-zero, via print_result) if any permission still references it."""
    return ui.print_result(_core(args).delete_sudo_profile(args.name))


def cmd_sudo_profile_rename(args: argparse.Namespace) -> int:
    """Rename a sudo profile, cascading the rename into every permission that references it."""
    return ui.print_result(_core(args).rename_sudo_profile(args.de, args.para))


def cmd_permission_revoke(args: argparse.Namespace) -> int:
    """Revoke access between a user-group and a server-group in local declared state.

    Prompts for confirmation unless `--yes`; the actual keys are only
    removed from servers on the next `apply`. Returns 1 if the user cancels.
    """
    if not args.yes and not ui.confirmar(
        _("Revoke {ug} -> {sg}? (apply removes keys)").format(ug=args.user_group, sg=args.server_group)
    ):
        ui.warn(_("operation cancelled"))
        return 1
    return ui.print_result(_core(args).revoke(args.user_group, args.server_group))


# ---------------------------------------------------------------------------
# UC-7 / UC-8: preview / apply
# ---------------------------------------------------------------------------
def cmd_preview(args: argparse.Namespace) -> int:
    """Compute and print the delta between local declared state and what was last applied.

    Read-only: does not touch any server (does not even open an SSH
    connection) and does not ask for confirmation. Grouped by server, with
    "+" for keys/sudoers to add and "-" for ones to remove. Always returns 0.
    """
    core = _core(args)
    sub_actions = core.preview()
    if not sub_actions:
        ui.ok(_("nothing to do — state in sync"))
        return 0
    ui.info(_("{n} sub-actions across {s} servers").format(n=len(sub_actions), s=len({sb.server for sb in sub_actions})))
    for hostname in sorted({s.server for s in sub_actions}):
        ui.heading(hostname)
        for s in sub_actions:
            if s.server != hostname:
                continue
            sinal = "+" if s.action == ActionType.ADD_KEY else "-"
            cor = ui._GREEN if s.action == ActionType.ADD_KEY else ui._RED
            ui.secho(
                f"  {sinal} {s.action.value:18} {s.credential:50} {(s.level.value if s.level else '-')}",
                cor,
            )
    return 0


def _print_diff(core: Core, sub_actions: list) -> None:
    """Show a unified diff of the authorized_keys of each (server, username) affected."""
    import difflib
    from adminforge import authorized_keys as ak

    por_user: dict[tuple[str, str], list] = {}
    for s in sub_actions:
        if s.action not in (ActionType.ADD_KEY, ActionType.REMOVE_KEY):
            continue
        if not s.username:
            continue
        por_user.setdefault((s.server, s.username), []).append(s)

    ui.heading(_("Diff (authorized_keys)"))
    for (hostname, username), lote in sorted(por_user.items()):
        server = core.store.get_server(hostname)
        if server is None:
            continue
        ui.secho(f"  {hostname}:{username}", bold=True)
        # read_authorized_keys can fail (ssh, host_key etc); it must not abort the diff of the others.
        try:
            atual, ok = core.deployer.read_authorized_keys(server, username)
        except Exception as e:
            ui.fail(_("    ssh: {e}").format(e=e))
            continue
        if not ok:
            ui.fail(_("    ssh: could not read authorized_keys (sudo blocked?)"))
            continue
        novo = atual
        for s in lote:
            if s.action == ActionType.ADD_KEY and s.public_key and s.credential:
                novo = ak.replace_block(novo, s.credential, ak.block(s.credential, s.public_key))
            elif s.action == ActionType.REMOVE_KEY and s.credential:
                novo = ak.replace_block(novo, s.credential, "")
        for line in difflib.unified_diff(
            atual.splitlines(), novo.splitlines(),
            fromfile="current", tofile="planned", lineterm="",
        ):
            if line.startswith("+") and not line.startswith("+++"):
                ui.secho(f"    {line}", ui._GREEN)
            elif line.startswith("-") and not line.startswith("---"):
                ui.secho(f"    {line}", ui._RED)
            elif line.startswith("@@"):
                ui.secho(f"    {line}", ui._CYAN)
            else:
                ui.echo(f"    {line}")


_SUDOERS_PREFIX = "adminforge-"


def _expected_from_server(server) -> tuple[dict[str, str], dict[str, str | None]]:
    """Read installed_keys and return ({ref: username} of the blocks,
    {username: profile} of those with sudo — profile None = full sudo)."""
    blocks: dict[str, str] = {}
    sudo: dict[str, str | None] = {}
    for item in server.installed_keys:
        if isinstance(item, dict):
            ref = item["ref"]
            u = item.get("username") or ref.split(":", 1)[0]
            blocks[ref] = u
            if item.get("level") == "sudo":
                sudo[u] = item.get("profile")
        else:
            blocks[item] = item.split(":", 1)[0]
    return blocks, sudo


def _regra_e_full_sudo(regra: str) -> bool:
    """Heuristic: the sudoers rule grants ALL commands (NOPASSWD:ALL).
    Reliable because AdminForge writes these files itself."""
    return "NOPASSWD:ALL" in regra.replace(" ", "").upper()


def _mapear_hosts(fn, itens, jobs):
    """Run fn over itens, up to `jobs` at once when jobs > 1 (order preserved)."""
    itens = list(itens)
    jobs = max(1, jobs)
    if jobs > 1 and len(itens) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(jobs, len(itens))) as pool:
            return list(pool.map(fn, itens))
    return [fn(x) for x in itens]


def cmd_apply_verify(args: argparse.Namespace) -> int:
    """Compare declared state vs the real server state: AdminForge blocks in
    authorized_keys + `adminforge-<user>` files in /etc/sudoers.d/ (presence
    and level — full sudo vs restricted profile)."""
    from adminforge import authorized_keys as ak

    core = _core(args, com_ssh=not args.dry_run)
    total_ok = 0
    total_div = 0
    ssh_errors: list[str] = []

    servers = core.store.list_servers()

    def _coletar(server):
        """Gather one server's expected vs. real authorized_keys/sudoers state over SSH.

        Pure data collection with no printing, so it is safe to run
        concurrently via `_mapear_hosts`; all rendering happens later in the
        (necessarily sequential) loop below.
        """
        # SSH-only gathering for one host (no printing, safe to run concurrently).
        esperado_blocks, esperado_sudo = _expected_from_server(server)
        data = {"esperado_blocks": esperado_blocks, "esperado_sudo": esperado_sudo,
                 "real_blocks": {}, "blocks_erro": None, "report": None}
        if esperado_blocks:
            real_blocks: dict[str, str] = {}
            for u in sorted(set(esperado_blocks.values())):
                try:
                    conteudo, ok = core.deployer.read_authorized_keys(server, u)
                except Exception as e:
                    data["blocks_erro"] = _("  ssh failed reading {u}: {e}").format(u=u, e=e)
                    break
                if not ok:
                    data["blocks_erro"] = _("  ssh: could not read authorized_keys for {u} (sudo blocked?)").format(u=u)
                    break
                for ref in ak.parse_blocks(conteudo):
                    real_blocks[ref] = u
            data["real_blocks"] = real_blocks
        try:
            data["report"] = core.deployer.inspect(server)
        except Exception as e:
            data["report"] = {"error": str(e)}
        rel = data["report"]
        users = rel.get("users", []) if isinstance(rel, dict) and "error" not in rel else []
        data["real_users"] = {u["name"] for u in users} if users else None
        return data

    coletados = _mapear_hosts(_coletar, servers, getattr(args, "jobs", 1))

    for server, data in zip(servers, coletados):
        esperado_blocks = data["esperado_blocks"]
        esperado_sudo = data["esperado_sudo"]
        ui.heading(server.hostname)

        # 1) authorized_keys — only if there are declared blocks
        if esperado_blocks:
            if data["blocks_erro"]:
                ui.fail(data["blocks_erro"])
                ssh_errors.append(server.hostname)
                continue
            real_blocks = data["real_blocks"]
            real_users = data["real_users"]
            for ref, username in sorted(esperado_blocks.items()):
                if real_users is not None and username not in real_users:
                    ui.fail(_("  {u} {ref} — declared but account missing on server").format(u=f"{username:20}", ref=ref))
                    total_div += 1
                    continue
                real_user = real_blocks.get(ref)
                if real_user is None:
                    ui.fail(_("  {u} {ref} — declared but not present on server").format(u=f"{username:20}", ref=ref))
                    total_div += 1
                elif real_user != username:
                    ui.fail(_("  {u} {ref} — declared under {decl} but found under {real}").format(u=f"{username:20}", ref=ref, decl=repr(username), real=repr(real_user)))
                    total_div += 1
                else:
                    ui.ok(f"  {username:20} {ref}")
                    total_ok += 1
            for ref, username in sorted(real_blocks.items()):
                if ref not in esperado_blocks:
                    ui.warn(_("  {u} {ref} — block on server but not in state").format(u=f"{username:20}", ref=ref))
                    total_div += 1
        else:
            ui.secho(_("  (no installed keys declared)"), dim=True)

        # 2) sudoers — always runs (even without declared blocks, to find orphan files)
        report = data["report"]
        if "error" in report:
            ui.fail(_("  ssh failed listing sudoers: {e}").format(e=report["error"]))
            ssh_errors.append(server.hostname)
            continue
        files = report.get("sudoers_arquivos") or []
        real_sudo = {
            a["name"][len(_SUDOERS_PREFIX):] for a in files
            if a.get("adminforge") and a.get("name", "").startswith(_SUDOERS_PREFIX)
        }
        # real rules per user (1st column; ignore group rules '%...')
        real_regras: dict[str, list[str]] = {}
        for regra in report.get("sudoers_regras") or []:
            col = regra.split(None, 1)[0] if regra else ""
            if col and not col.startswith("%"):
                real_regras.setdefault(col, []).append(regra)

        for u, profile in sorted(esperado_sudo.items()):
            if u not in real_sudo:
                ui.fail(_("  {u} sudoers — declared but missing on server").format(u=f"{u:20}"))
                total_div += 1
                continue
            real_full = any(_regra_e_full_sudo(r) for r in real_regras.get(u, []))
            esperado_full = profile is None
            if real_full != esperado_full:
                if esperado_full:
                    ui.fail(_("  {u} sudoers — expected full sudo, server has a restricted profile").format(u=f"{u:20}"))
                else:
                    ui.fail(_("  {u} sudoers — expected restricted profile {p}, server grants full sudo").format(u=f"{u:20}", p=repr(profile)))
                total_div += 1
            else:
                level = "full" if esperado_full else "restricted"
                ui.ok(_("  {u} sudoers — present ({lvl})").format(u=f"{u:20}", lvl=level))
                total_ok += 1
        for u in sorted(real_sudo - set(esperado_sudo)):
            ui.warn(_("  {u} sudoers — present on server but not declared").format(u=f"{u:20}"))
            total_div += 1

    ui.echo()
    ui.heading(_("Summary"))
    ui.kv(_("matches"), str(total_ok))
    ui.kv(_("divergences"), str(total_div))
    if ssh_errors:
        ui.kv(_("ssh errors"), ", ".join(ssh_errors))
    return 0 if total_div == 0 and not ssh_errors else 2


def cmd_apply(args: argparse.Namespace) -> int:
    """Push the pending delta (declared vs. last-applied state) to servers over real SSH.

    Prints the planned changes (and, with `--diff`, a per-user
    authorized_keys unified diff) and asks for confirmation before doing
    anything, unless `--yes`. Not idempotent by default — it only pushes
    what the Store believes has changed; `--force` re-applies every declared
    key/sudoers entry regardless, and `--reconcile` additionally reads each
    server's live state first and converges onto it (re-creating
    manually-deleted users/keys, removing orphan blocks among declared
    users). `--dry-run` uses a fake deployer instead of real SSH.
    `--jobs N` applies to up to N hosts concurrently. Every apply is written
    to the history log regardless of outcome. Returns 0 if every sub-action
    succeeded, 1 if some succeeded and some failed (re-running `apply`
    retries only the failed ones), 2 if all failed or there was nothing to
    retry.
    """
    core = _core(args, com_ssh=not args.dry_run)
    force = getattr(args, "force", False)
    reconcile = getattr(args, "reconcile", False)
    sub_actions = core.preview(force=force, reconcile=reconcile)
    if not sub_actions:
        ui.ok(_("nothing to do — state in sync"))
        return 0

    ui.info(_("{n} sub-actions across {s} servers").format(n=len(sub_actions), s=len({sb.server for sb in sub_actions})))
    for hostname in sorted({s.server for s in sub_actions}):
        ui.secho(f"  {hostname}", bold=True)
        for s in sub_actions:
            if s.server != hostname:
                continue
            sinal = "+" if s.action == ActionType.ADD_KEY else "-"
            ui.echo(f"    {sinal} {s.action.value:18} {s.credential}")

    if args.diff:
        _print_diff(core, sub_actions)

    if not args.yes and not ui.confirmar(_("Apply {n} change(s) now?").format(n=len(sub_actions))):
        ui.warn(_("apply cancelled"))
        return 1

    op = core.apply(jobs=max(1, getattr(args, "jobs", 1)), force=force, reconcile=reconcile, sub_actions=sub_actions)
    successes = sum(1 for s in op.sub_actions if s.status == "success")
    failures = sum(1 for s in op.sub_actions if s.status == "failure")
    ui.heading(_("Result"))
    for s in op.sub_actions:
        if s.status == "success":
            ui.ok(f"{s.server:24} {s.action.value:18} {s.credential or ''}")
        else:
            ui.fail(f"{s.server:24} {s.action.value:18} {s.credential or ''} — {s.error}")
    ui.echo()
    ui.kv(_("operation"), op.id)
    ui.kv(_("status"), op.status.value.upper())
    ui.kv(_("successes"), str(successes))
    ui.kv(_("failures"), str(failures))
    if failures:
        ui.echo()
        ui.info(_("re-running 'adminforge apply' retries only the failed sub-actions"))
        return 1 if successes else 2
    return 0


# ---------------------------------------------------------------------------
# UC-9: history
# ---------------------------------------------------------------------------
def _history_rows_and_json(ops: list) -> tuple[list[list[str]], list[dict]]:
    """Render a list of Operation records into (table rows, JSON dicts) for --format.

    Shared by `history list` and `history failed` so both commands render
    identically. The command in the table row is truncated to 40 characters;
    the JSON form keeps the full command string.
    """
    lines = [
        [
            op.id,
            op.timestamp.strftime("%Y-%m-%d %H:%M"),
            op.superadmin,
            op.command[:40],
            op.status.value.upper(),
        ]
        for op in ops
    ]
    json_data = [
        {
            "id": op.id,
            "when": op.timestamp.isoformat(timespec="seconds"),
            "superadmin": op.superadmin,
            "command": op.command,
            "status": op.status.value,
            "subactions": len(op.sub_actions),
        }
        for op in ops
    ]
    return lines, json_data


def cmd_history_list(args: argparse.Namespace) -> int:
    """List the most recent operations from the local audit log (default: last 50, newest first)."""
    core = _core(args)
    ops = core.auditor.list_operations(args.limit)
    lines, json_data = _history_rows_and_json(ops)
    return _emit_listing(
        args, ["ID", "WHEN", "SUPERADMIN", "COMMAND", "STATUS"], lines, json_data=json_data
    )


def cmd_history_show(args: argparse.Namespace) -> int:
    """Print full detail of one operation by `--id`: metadata, hash chain links, and every sub-action.

    Returns 2 if the operation id does not exist in the audit log.
    """
    core = _core(args)
    op = core.auditor.find(args.op_id)
    if not op:
        ui.fail(_("operation {i} does not exist").format(i=args.op_id))
        return 2
    ui.heading(_("Operation"))
    ui.kv(_("id"), op.id)
    ui.kv(_("when"), op.timestamp.isoformat())
    ui.kv(_("superadmin"), op.superadmin)
    ui.kv(_("command"), op.command)
    ui.kv(_("status"), op.status.value)
    ui.kv(_("hash"), op.hash or "-")
    ui.kv(_("prev_hash"), op.previous_hash or "-")
    ui.heading(_("Sub-actions ({n})").format(n=len(op.sub_actions)))
    lines = [
        [
            s.server or "-",
            s.action.value,
            s.credential or s.username or "-",
            s.status,
            (s.error or s.message or "")[:60],
        ]
        for s in op.sub_actions
    ]
    ui.tabela(["SERVER", "ACTION", "TARGET", "STATUS", "DETAIL"], lines)
    return 0


def cmd_history_failed(args: argparse.Namespace) -> int:
    """List only the operations that failed or partially failed, most recent first."""
    core = _core(args)
    ops = core.auditor.list_failures(args.limit)
    lines, json_data = _history_rows_and_json(ops)
    return _emit_listing(
        args, ["ID", "WHEN", "SUPERADMIN", "COMMAND", "STATUS"], lines, json_data=json_data
    )


def cmd_history_verify(args: argparse.Namespace) -> int:
    """Verify the tamper-evidence hash chain of the local audit log is intact end to end.

    Read-only. Returns 2 (and prints the exception message) if any link in
    the chain does not match; returns 0 and prints the last hash otherwise.
    """
    core = _core(args)
    try:
        _ok, ultimo = core.auditor.verify_chain()
    except Exception as e:
        ui.fail(_("chain broken: {e}").format(e=e))
        return 2
    ui.ok(_("chain intact (last hash: {h})").format(h=ultimo or "-"))
    return 0


# ---------------------------------------------------------------------------
# Dump global
# ---------------------------------------------------------------------------
def _collect_state(core: Core) -> dict:
    """Gather the full local declared state (users, groups, servers, permissions, sudo-profiles) into one dict.

    Read-only, local only. Used by `cmd_dump` for both the JSON and table
    renderings, so the two stay consistent.
    """
    return {
        "users": [
            {
                "username": u.username,
                "name": u.name,
                "email": u.email,
                "status": u.status.value,
                "credentials": [
                    {"fingerprint": c.fingerprint, "status": c.status.value}
                    for c in core.store.list_credentials(u.username)
                ],
            }
            for u in core.store.list_users()
        ],
        "user_groups": [
            {"name": g.name, "members": list(g.members)}
            for g in core.store.list_user_groups()
        ],
        "servers": [
            {
                "hostname": s.hostname,
                "ipv4": s.ipv4,
                "port": s.ssh_port,
                "host_key": s.host_key,
                "installed_keys": list(s.installed_keys),
            }
            for s in core.store.list_servers()
        ],
        "server_groups": [
            {"name": g.name, "members": list(g.members)}
            for g in core.store.list_server_groups()
        ],
        "permissions": [
            {
                "user_group": p.user_group,
                "server_group": p.server_group,
                "level": p.level.value,
                "profile": p.profile,
            }
            for p in core.store.list_permissions()
        ],
        "sudo_profiles": [
            {"name": p.name, "commands": list(p.commands)}
            for p in core.store.list_sudo_profiles()
        ],
    }


def cmd_status(args: argparse.Namespace) -> int:
    """Quick 'git status'-like overview: counts, pending changes and last operation."""
    core = _core(args)
    s = core.store
    counts = {
        "users": len(s.list_users()),
        "user_groups": len(s.list_user_groups()),
        "servers": len(s.list_servers()),
        "server_groups": len(s.list_server_groups()),
        "permissions": len(s.list_permissions()),
        "sudo_profiles": len(s.list_sudo_profiles()),
    }

    try:
        pending = core.preview()
        pending_servers = len({sb.server for sb in pending})
        pending_error = None
    except Exception as e:
        pending = []
        pending_servers = 0
        pending_error = str(e)

    ultima = core.auditor.list_operations(1)
    ultima_op = ultima[0] if ultima else None

    chain_ok = True
    chain_error = None
    try:
        core.auditor.verify_chain()
    except Exception as e:
        chain_ok = False
        chain_error = str(e)

    if getattr(args, "format", "table") == "json":
        print(json.dumps({
            "counts": counts,
            "pending": {
                "subactions": len(pending),
                "servers": pending_servers,
                "error": pending_error,
            },
            "last_operation": (
                {
                    "id": ultima_op.id,
                    "command": ultima_op.command,
                    "status": ultima_op.status.value,
                    "when": ultima_op.timestamp.isoformat(timespec="seconds"),
                    "superadmin": ultima_op.superadmin,
                } if ultima_op else None
            ),
            "history_chain": {"ok": chain_ok, "error": chain_error},
        }, indent=2, ensure_ascii=False))
        return 0

    ui.heading(_("State"))
    ui.echo(_("  {users} users, {ugroups} user-groups, {servers} servers, {sgroups} server-groups, {perms} permissions, {sprofiles} sudo-profiles").format(
        users=counts["users"], ugroups=counts["user_groups"], servers=counts["servers"],
        sgroups=counts["server_groups"], perms=counts["permissions"], sprofiles=counts["sudo_profiles"]))

    ui.heading(_("Pending"))
    if pending_error:
        ui.fail(_("  could not compute delta: {e}").format(e=pending_error))
    elif not pending:
        ui.ok(_("  no pending changes — state is in sync with declared"))
    else:
        ui.warn(_("  {n} sub-action(s) across {s} server(s) — run 'adminforge preview' to see, 'adminforge apply' to apply").format(n=len(pending), s=pending_servers))

    ui.heading(_("Last operation"))
    if ultima_op is None:
        ui.secho(_("  (no operations yet)"), dim=True)
    else:
        ui.kv(_("id"), ultima_op.id)
        ui.kv(_("command"), ultima_op.command)
        ui.kv(_("status"), ultima_op.status.value)
        ui.kv(_("when"), ultima_op.timestamp.isoformat(timespec="seconds"))
        ui.kv(_("by"), ultima_op.superadmin)

    ui.heading(_("History chain"))
    if chain_ok:
        ui.ok(_("  intact"))
    else:
        ui.fail(_("  broken: {e}").format(e=chain_error))

    if counts["users"] == 0:
        ui.echo()
        ui.info(_("Empty state. Try: adminforge user add --username <name> --name '<full>' --email <email>"))
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    """Print the entire local declared state: users, user-groups, servers, server-groups, permissions and sudo-profiles.

    Read-only. Unlike most other list commands here, `--format` has no
    "table" default fallback via `_emit_listing` — `table` prints one table
    per section instead of a single flat table.
    """
    state = _collect_state(_core(args))
    if args.format == "json":
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return 0

    ui.heading(_("Users ({n})").format(n=len(state["users"])))
    ui.tabela(
        ["USERNAME", "NOME", "EMAIL", "STATUS", "CHAVES"],
        [
            [u["username"], u["name"], u["email"], u["status"], str(len(u["credentials"]))]
            for u in state["users"]
        ],
    )

    ui.heading(_("User groups ({n})").format(n=len(state["user_groups"])))
    ui.tabela(
        ["NOME", "MEMBROS"],
        [[g["name"], ", ".join(g["members"]) or "-"] for g in state["user_groups"]],
    )

    ui.heading(_("Servers ({n})").format(n=len(state["servers"])))
    ui.tabela(
        ["HOSTNAME", "IPV4", "PORTA", "CHAVES_INSTALADAS"],
        [
            [s["hostname"], s["ipv4"], str(s["port"]), str(len(s["installed_keys"]))]
            for s in state["servers"]
        ],
    )

    ui.heading(_("Server groups ({n})").format(n=len(state["server_groups"])))
    ui.tabela(
        ["NOME", "MEMBROS"],
        [[g["name"], ", ".join(g["members"]) or "-"] for g in state["server_groups"]],
    )

    ui.heading(_("Permissions ({n})").format(n=len(state["permissions"])))
    ui.tabela(
        ["USER_GROUP", "SERVER_GROUP", "LEVEL", "PROFILE"],
        [
            [p["user_group"], p["server_group"], p["level"], p.get("profile") or "—"]
            for p in state["permissions"]
        ],
    )

    ui.heading(_("Sudo profiles ({n})").format(n=len(state["sudo_profiles"])))
    ui.tabela(
        ["NAME", "#CMDS", "COMMANDS"],
        [[p["name"], str(len(p["commands"])), ", ".join(p["commands"])[:60]] for p in state["sudo_profiles"]],
    )
    return 0


# ---------------------------------------------------------------------------
# UC-10: audit server
# ---------------------------------------------------------------------------
def _hosts_para_auditar(core: Core, args: argparse.Namespace) -> list[str] | None:
    """Resolve the set of hostnames to audit. Returns None when it has already
    reported an error (e.g. nonexistent server-group) — the caller prints nothing more."""
    if getattr(args, "all", False):
        return [s.hostname for s in core.store.list_servers()]
    if getattr(args, "server_group", None):
        g = core.store.get_server_group(args.server_group)
        if not g:
            ui.fail(_("server-group {g} does not exist").format(g=repr(args.server_group)))
            return None
        return list(g.members)
    return list(args.hostname or [])


def cmd_audit_server(args: argparse.Namespace) -> int:
    """Inspect one or more real servers over SSH: users, groups, sudoers files/rules and running services.

    Read-only on the server — never modifies anything, local or remote.
    Target is one of `--hostname` (one or more), `--server-group` or `--all`
    (mutually exclusive). With `--jobs N`, inspects up to N hosts
    concurrently. Returns 2 if the target server-group does not exist, if no
    servers resolve, or if any host fails to respond over SSH (other hosts'
    results are still printed).
    """
    core = _core(args, com_ssh=True)
    hostnames = _hosts_para_auditar(core, args)
    if hostnames is None:
        return 2
    if not hostnames:
        ui.fail(_("no servers to audit"))
        return 2
    resultados = _mapear_hosts(core.audit_server, hostnames, getattr(args, "jobs", 1))

    any_failure = False
    for i, (hostname, (op, report)) in enumerate(zip(hostnames, resultados)):
        if i > 0:
            ui.echo()
            ui.secho("─" * 60, dim=True)
        if "error" in report:
            ui.fail(f"{hostname}: {report['error']}")
            any_failure = True
            continue
        _print_audit_report(args, hostname, op, report)
    return 2 if any_failure else 0


def _print_audit_report(args: argparse.Namespace, hostname: str, op, report: dict) -> None:
    """Pretty-print one server's audit report: users, groups, sudoers, services and heuristic alerts.

    With `--humans`, only users with UID >= 1000 are listed. `--user`,
    `--group` and `--service` each highlight/filter matching rows on their
    respective section. Alerts include sudoers files found under
    /etc/sudoers.d/ that were not written by AdminForge.
    """
    users = report.get("users", [])
    groups = report.get("groups", [])
    servicos = report.get("servicos", [])
    sudoers_files = report.get("sudoers_arquivos", [])
    regras_sudo = report.get("sudoers_regras", [])

    if args.humans:
        users = [u for u in users if u.get("categoria") == "human"]

    ui.heading(hostname)
    # Users
    titulo = _("Users ({n})").format(n=len(users))
    if args.humans:
        titulo = _("Users ({n}) — humans only (UID >= 1000)").format(n=len(users))
    ui.heading(titulo)
    if users:
        lines = []
        for u in users:
            destacar = bool(args.user and args.user in u["name"])
            marca = "*" if destacar else " "
            groups_str = ",".join(u.get("groups", []))[:40]
            sudo_str = "yes" if u.get("sudo") else "—"
            lines.append([marca, u["name"], str(u["uid"]), u["categoria"], u["shell"], groups_str, sudo_str])
        ui.tabela([" ", "USERNAME", "UID", "CATEGORY", "SHELL", "GROUPS", "SUDO"], lines)
    else:
        ui.secho(_("  (none)"), dim=True)

    # Groups
    if args.group:
        alvo = [g for g in groups if args.group in g["name"]]
        ui.heading(_("Groups matching {g} ({n})").format(g=repr(args.group), n=len(alvo)))
        for g in alvo:
            members = ", ".join(g["members"]) or "-"
            ui.echo(f"  {g['name']} (gid={g['gid']}): {members}")
    else:
        ui.heading(_("Groups ({n})").format(n=len(groups)))
        with_members = [g for g in groups if g["members"]]
        if with_members:
            ui.tabela(
                ["NAME", "GID", "MEMBERS"],
                [[g["name"], str(g["gid"]), ", ".join(g["members"])[:60]] for g in with_members],
            )
        else:
            ui.secho(_("  (no group with explicit members)"), dim=True)

    # Sudoers
    ui.heading(_("Sudoers — files in /etc/sudoers.d/ ({n})").format(n=len(sudoers_files)))
    if sudoers_files:
        for a in sudoers_files:
            source = "adminforge" if a["adminforge"] else "manual"
            cor = ui._GREEN if a["adminforge"] else ui._YELLOW
            ui.secho(f"  [{source:10}] {a['name']}", cor)
    else:
        ui.secho(_("  (could not list — ssh has no sudo on the server?)"), dim=True)

    if regras_sudo:
        ui.heading(_("Active sudo rules ({n})").format(n=len(regras_sudo)))
        for r in regras_sudo[:20]:
            ui.echo(f"  {r}")
        if len(regras_sudo) > 20:
            ui.secho(_("  ... +{n} rules (use --format json for full output)").format(n=len(regras_sudo) - 20), dim=True)

    # Services
    ui.heading(_("Running services ({n})").format(n=len(servicos)))
    for s in servicos:
        if args.service and args.service in s:
            ui.secho(f"  * {s}", ui._YELLOW, bold=True)
        else:
            ui.echo(f"    {s}")

    # Heuristic alerts
    alertas = []
    if args.user:
        names = {u["name"] for u in users}
        if args.user in names and not any(args.user in s for s in servicos):
            alertas.append(_("user {u} exists but no matching service is running").format(u=repr(args.user)))
    sudoers_manuais = [a["name"] for a in sudoers_files if not a["adminforge"]]
    if sudoers_manuais:
        alertas.append(_("{n} file(s) in /etc/sudoers.d/ outside AdminForge: {files}").format(
            n=len(sudoers_manuais),
            files=", ".join(sudoers_manuais[:5]) + (" ..." if len(sudoers_manuais) > 5 else "")))

    if alertas:
        ui.heading(_("Alerts"))
        for a in alertas:
            ui.warn(a)

    ui.kv(_("operation"), op.id)
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    """Build the full argparse CLI tree: one subparser (and nested sub-subparsers) per top-level command.

    Wires the `func` default on every leaf parser to the `cmd_*` handler
    that runs it, plus argcomplete `.completer` attributes on arguments that
    reference existing state (usernames, hostnames, group names, sudo
    profiles, fingerprints). Called once per process from `main()`; builds a
    fresh parser every time rather than caching one at import time.
    """
    parser = argparse.ArgumentParser(
        prog="adminforge",
        description=_(
            "AdminForge - manages who has privileged access (SSH keys and sudo) on a fleet of "
            "Linux servers.\n\n"
            "You edit the desired state with these commands; 'apply' pushes the changes to the "
            "servers over SSH. Every command goes into history.jsonl.\n\n"
            "Every command has its own --help, e.g. 'adminforge user --help', "
            "'adminforge permission grant --help'."
        ),
        epilog=_(EPILOG_GERAL),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version=f"adminforge {__version__}")
    parser.add_argument(
        "--state",
        default=os.environ.get("ADMINFORGE_STATE", "./state"),
        help=_("State directory (default: ./state or $ADMINFORGE_STATE)."),
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    # user
    p_user = sub.add_parser(
        "user",
        help=_("Register, lifecycle and SSH keys of users."),
        epilog=_(
            "Examples:\n"
            "  adminforge user add --username marina --name 'Marina' --email marina@empresa.com --key-file ~/.ssh/marina.pub\n"
            "  adminforge user key add --username marina --file ~/.ssh/marina.pub   # ou em dois passos\n"
            "  adminforge user disable --username marina"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s_user = p_user.add_subparsers(dest="sub", required=True)
    a = s_user.add_parser("add", help=_("Register a new user (optionally with their SSH key)."))
    a.add_argument("--username", required=True)
    a.add_argument("--name", required=True)
    a.add_argument("--email", required=True)
    g = a.add_mutually_exclusive_group()
    g.add_argument("--key-file", dest="key_file", help=_("Also register this .pub file as the user's key."))
    g.add_argument("--key-string", dest="key_string", help=_("Also register this full key string as the user's key."))
    a.set_defaults(func=cmd_user_add)
    a = s_user.add_parser("list", help=_("List users."))
    a.add_argument("--format", choices=["table", "json"], default="table")
    a.set_defaults(func=cmd_user_list)
    a = s_user.add_parser("show", help=_("Show user details."))
    a.add_argument("--username", required=True).completer = completers.usernames
    a.set_defaults(func=cmd_user_show)
    a = s_user.add_parser("disable", help=_("Disable user (revokes all keys)."))
    a.add_argument("--username", required=True).completer = completers.usernames
    a.add_argument("--yes", action="store_true")
    a.set_defaults(func=cmd_user_disable)

    a = s_user.add_parser("edit", help=_("Edit a user's name or e-mail."))
    a.add_argument("--username", required=True).completer = completers.usernames
    a.add_argument("--name", help=_("New full name."))
    a.add_argument("--email", help=_("New e-mail."))
    a.set_defaults(func=cmd_user_edit)

    a = s_user.add_parser("rename", help=_("Rename a user (cascades to group memberships)."))
    a.add_argument("--from", dest="de", required=True, help=_("Current username.")).completer = completers.usernames
    a.add_argument("--to", dest="para", required=True, help=_("New username."))
    a.set_defaults(func=cmd_user_rename)

    # user key (nested subcommand of user)
    p_uk = s_user.add_parser("key", help=_("Register and revoke user SSH keys."))
    s_uk = p_uk.add_subparsers(dest="key_sub", required=True)
    a = s_uk.add_parser("add", help=_("Register an SSH key."))
    a.add_argument("--username", required=True).completer = completers.usernames
    a.add_argument("--file", help=_("Path to a .pub file."))
    a.add_argument("--string", help=_("Paste the full key."))
    a.set_defaults(func=cmd_user_key_add)
    a = s_uk.add_parser("revoke", help=_("Revoke a key by fingerprint."))
    a.add_argument("--fingerprint", required=True).completer = completers.fingerprints
    a.set_defaults(func=cmd_user_key_revoke)
    a = s_uk.add_parser("list", help=_("List user keys."))
    a.add_argument("--username", required=True).completer = completers.usernames
    a.add_argument("--format", choices=["table", "json"], default="table")
    a.set_defaults(func=cmd_user_key_list)

    # user-group
    p_ug = sub.add_parser(
        "user-group",
        help=_("User groups."),
        epilog=_(
            "Examples:\n"
            "  adminforge user-group create --name sysadmins\n"
            "  adminforge user-group add-member --group sysadmins --username alice bob carla\n"
            "  adminforge user-group remove-member --group sysadmins --username bob"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s_ug = p_ug.add_subparsers(dest="sub", required=True)

    a = s_ug.add_parser("create")
    a.add_argument("--name", required=True)
    a.set_defaults(func=cmd_ug_create)

    a = s_ug.add_parser("add-member")
    a.add_argument("--group", required=True).completer = completers.user_groups
    a.add_argument("--username", required=True, nargs="+", help=_("one or more usernames (separated by space or comma)")).completer = completers.usernames
    a.set_defaults(func=cmd_ug_add_member)

    a = s_ug.add_parser("remove-member")
    a.add_argument("--group", required=True).completer = completers.user_groups
    a.add_argument("--username", required=True, nargs="+", help=_("one or more usernames (separated by space or comma)")).completer = completers.usernames
    a.set_defaults(func=cmd_ug_remove_member)

    a = s_ug.add_parser("delete")
    a.add_argument("--name", required=True).completer = completers.user_groups
    a.set_defaults(func=cmd_ug_delete)

    a = s_ug.add_parser("rename", help=_("Rename a user-group (cascades to permissions)."))
    a.add_argument("--from", dest="de", required=True, help=_("Current name.")).completer = completers.user_groups
    a.add_argument("--to", dest="para", required=True, help=_("New name."))
    a.set_defaults(func=cmd_ug_rename)

    a = s_ug.add_parser("list")
    a.add_argument("--format", choices=["table", "json"], default="table")
    a.set_defaults(func=cmd_ug_list)

    # server
    p_server = sub.add_parser(
        "server",
        help=_("Server registration."),
        epilog=_(
            "Examples:\n"
            "  adminforge server add --hostname web-01 --ip 10.0.0.10 --auto\n"
            "  adminforge server show --hostname web-01\n"
            "\n"
            "About --auto and the fingerprint: see docs/USAGE.md (UC-4)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s_server = p_server.add_subparsers(dest="sub", required=True)
    a = s_server.add_parser("add", help=_("Register a server (TOFU host_key)."))
    a.add_argument("--hostname", required=True)
    a.add_argument("--ip", required=True, help=_("Server IPv4."))
    a.add_argument("--port", type=int, default=22, help=_("SSH port on the server (default: 22)."))
    a.add_argument("--host-key", help=_("ssh-keyscan output, e.g. 'ssh-ed25519 AAAA...'"))
    a.add_argument("--auto", action="store_true", help=_("Capture host_key via ssh-keyscan."))
    a.set_defaults(func=cmd_server_add)

    a = s_server.add_parser("list")
    a.add_argument("--format", choices=["table", "json"], default="table")
    a.set_defaults(func=cmd_server_list)

    a = s_server.add_parser("show")
    a.add_argument("--hostname", required=True).completer = completers.hostnames
    a.set_defaults(func=cmd_server_show)

    a = s_server.add_parser("remove")
    a.add_argument("--hostname", required=True).completer = completers.hostnames
    a.add_argument("--yes", action="store_true")
    a.set_defaults(func=cmd_server_remove)

    a = s_server.add_parser("edit", help=_("Edit a server's IP, port or host_key."))
    a.add_argument("--hostname", required=True).completer = completers.hostnames
    a.add_argument("--ip", help=_("New IPv4."))
    a.add_argument("--port", type=int, help=_("New SSH port."))
    a.add_argument("--host-key", dest="host_key", help=_("New host_key (rotates the trusted key — use with care)."))
    a.set_defaults(func=cmd_server_edit)

    a = s_server.add_parser("rename", help=_("Rename a server (cascades to server-groups)."))
    a.add_argument("--from", dest="de", required=True, help=_("Current hostname.")).completer = completers.hostnames
    a.add_argument("--to", dest="para", required=True, help=_("New hostname."))
    a.set_defaults(func=cmd_server_rename)

    # server-group
    p_sg = sub.add_parser(
        "server-group",
        help=_("Server groups."),
        epilog=_(
            "Examples:\n"
            "  adminforge server-group create --name producao\n"
            "  adminforge server-group add-member --group producao --hostname web-01 web-02 db-03"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s_sg = p_sg.add_subparsers(dest="sub", required=True)

    a = s_sg.add_parser("create")
    a.add_argument("--name", required=True)
    a.set_defaults(func=cmd_sg_create)

    a = s_sg.add_parser("add-member")
    a.add_argument("--group", required=True).completer = completers.server_groups
    a.add_argument("--hostname", required=True, nargs="+", help=_("one or more hostnames (separated by space or comma)")).completer = completers.hostnames
    a.set_defaults(func=cmd_sg_add)

    a = s_sg.add_parser("remove-member")
    a.add_argument("--group", required=True).completer = completers.server_groups
    a.add_argument("--hostname", required=True, nargs="+", help=_("one or more hostnames (separated by space or comma)")).completer = completers.hostnames
    a.set_defaults(func=cmd_sg_rm)

    a = s_sg.add_parser("delete")
    a.add_argument("--name", required=True).completer = completers.server_groups
    a.set_defaults(func=cmd_sg_delete)

    a = s_sg.add_parser("rename", help=_("Rename a server-group (cascades to permissions)."))
    a.add_argument("--from", dest="de", required=True, help=_("Current name.")).completer = completers.server_groups
    a.add_argument("--to", dest="para", required=True, help=_("New name."))
    a.set_defaults(func=cmd_sg_rename)

    a = s_sg.add_parser("list")
    a.add_argument("--format", choices=["table", "json"], default="table")
    a.set_defaults(func=cmd_sg_list)

    # permission — all permission-management actions live under this menu
    p_perm = sub.add_parser(
        "permission",
        help=_("Manage permissions: grant / revoke / list / show."),
        epilog=_(
            "Examples:\n"
            "  adminforge permission grant --user-group sa --server-group prod --level sudo\n"
            "  adminforge permission revoke --user-group sa --server-group prod\n"
            "  adminforge permission list\n"
            "  adminforge permission show --user alice"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s_perm = p_perm.add_subparsers(dest="sub", required=True)

    a = s_perm.add_parser("grant", help=_("Grant access from a user-group to a server-group."))
    a.add_argument("--user-group", dest="user_group", required=True).completer = completers.user_groups
    a.add_argument("--server-group", dest="server_group", required=True).completer = completers.server_groups
    a.add_argument("--level", choices=["shell", "sudo"], required=True)
    a.add_argument("--profile", help=_("Sudo profile name (only with --level sudo); without it, grants NOPASSWD:ALL.")).completer = completers.sudo_profiles
    a.set_defaults(func=cmd_permission_grant)

    a = s_perm.add_parser("revoke", help=_("Revoke access between two groups."))
    a.add_argument("--user-group", dest="user_group", required=True).completer = completers.user_groups
    a.add_argument("--server-group", dest="server_group", required=True).completer = completers.server_groups
    a.add_argument("--yes", action="store_true", help=_("Skip confirmation."))
    a.set_defaults(func=cmd_permission_revoke)

    a = s_perm.add_parser("list", help=_("List all permissions."))
    a.add_argument("--format", choices=["table", "json"], default="table")
    a.set_defaults(func=cmd_permission_list)

    a = s_perm.add_parser(
        "show",
        help=_("Reverse query: which servers a user effectively reaches, or which grants reach a group."),
        epilog=_(
            "Examples:\n"
            "  adminforge permission show --user alice\n"
            "  adminforge permission show --user-group sysadmins\n"
            "  adminforge permission show --server-group producao"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    grp = a.add_mutually_exclusive_group(required=True)
    grp.add_argument("--user").completer = completers.usernames
    grp.add_argument("--user-group", dest="user_group").completer = completers.user_groups
    grp.add_argument("--server-group", dest="server_group").completer = completers.server_groups
    a.add_argument("--format", choices=["table", "json"], default="table")
    a.set_defaults(func=cmd_permission_show)

    # sudo-profile
    p_sp = sub.add_parser(
        "sudo-profile",
        help=_("Manage named sudo profiles (allowed commands per role)."),
        epilog=_(
            "Examples:\n"
            "  adminforge sudo-profile create --name read-logs --command /bin/journalctl --command '/bin/cat /var/log/*'\n"
            "  adminforge sudo-profile list\n"
            "  adminforge permission grant --user-group monitoring --server-group prod --level sudo --profile read-logs"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s_sp = p_sp.add_subparsers(dest="sub", required=True)

    a = s_sp.add_parser("create", help=_("Create a sudo profile with one or more absolute commands."))
    a.add_argument("--name", required=True)
    a.add_argument("--command", required=True, action="append", help=_("Absolute path to allow (repeat)."))
    a.set_defaults(func=cmd_sudo_profile_create)

    a = s_sp.add_parser("list", help=_("List sudo profiles."))
    a.add_argument("--format", choices=["table", "json"], default="table")
    a.set_defaults(func=cmd_sudo_profile_list)

    a = s_sp.add_parser("show", help=_("Show commands of a sudo profile."))
    a.add_argument("--name", required=True).completer = completers.sudo_profiles
    a.set_defaults(func=cmd_sudo_profile_show)

    a = s_sp.add_parser("delete", help=_("Delete a sudo profile (must be unused)."))
    a.add_argument("--name", required=True).completer = completers.sudo_profiles
    a.set_defaults(func=cmd_sudo_profile_delete)

    a = s_sp.add_parser("rename", help=_("Rename a sudo profile (cascades to permissions)."))
    a.add_argument("--from", dest="de", required=True, help=_("Current name.")).completer = completers.sudo_profiles
    a.add_argument("--to", dest="para", required=True, help=_("New name."))
    a.set_defaults(func=cmd_sudo_profile_rename)

    # status
    a = sub.add_parser(
        "status",
        help=_("Quick overview: counts, pending changes, last operation, history chain."),
    )
    a.add_argument("--format", choices=["table", "json"], default="table")
    a.set_defaults(func=cmd_status)

    # dump
    a = sub.add_parser("dump", help=_("List the full declared state (users, groups, servers, permissions)."))
    a.add_argument("--format", choices=["table", "json"], default="table")
    a.set_defaults(func=cmd_dump)

    # preview
    a = sub.add_parser("preview", help=_("Show the delta without applying."))
    a.set_defaults(func=cmd_preview)

    # apply
    p_apply = sub.add_parser(
        "apply",
        help=_("Apply the delta to servers via SSH."),
        description=_(
            "Apply the delta (pending changes) to servers via SSH.\n\n"
            "Tip: run 'adminforge preview' first to see exactly what will change without\n"
            "touching anything. The 'apply' command also shows the changes and asks for\n"
            "confirmation before doing anything."
        ),
        epilog=_(
            "See also:\n"
            "  adminforge preview         # read-only: show the delta\n"
            "  adminforge apply verify    # compare declared state vs real servers"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_apply.add_argument("--yes", action="store_true", help=_("Skip confirmation."))
    p_apply.add_argument("--dry-run", action="store_true", help=_("Use the fake Deployer."))
    p_apply.add_argument("--diff", action="store_true", help=_("Show authorized_keys before/after diff per user."))
    p_apply.add_argument("--jobs", type=int, default=1, metavar="N", help=_("Apply to up to N hosts in parallel (default 1, sequential)."))
    _apply_mode = p_apply.add_mutually_exclusive_group()
    _apply_mode.add_argument(
        "--force", action="store_true",
        help=_("Re-apply every declared key (idempotent); ignores what the Store believes is installed."),
    )
    _apply_mode.add_argument(
        "--reconcile", action="store_true",
        help=_("Read each server's live state first, then converge: re-create manually-deleted users/keys and remove orphan blocks among declared users."),
    )
    p_apply.set_defaults(func=cmd_apply)
    s_apply = p_apply.add_subparsers(dest="apply_sub", required=False)
    a = s_apply.add_parser(
        "verify",
        help=_("Compare declared state vs real servers (authorized_keys + sudoers)."),
    )
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--jobs", type=int, default=1, metavar="N", help=_("Inspect up to N hosts in parallel (default 1)."))
    a.set_defaults(func=cmd_apply_verify)

    # history
    p_hist = sub.add_parser("history", help=_("Query operational history."))
    s_hist = p_hist.add_subparsers(dest="sub", required=True)

    a = s_hist.add_parser("list")
    a.add_argument("-n", "--limit", type=int, default=50)
    a.add_argument("--format", choices=["table", "json"], default="table")
    a.set_defaults(func=cmd_history_list)

    a = s_hist.add_parser("show")
    a.add_argument("--id", dest="op_id", required=True)
    a.set_defaults(func=cmd_history_show)

    a = s_hist.add_parser("failed")
    a.add_argument("-n", "--limit", type=int, default=50)
    a.add_argument("--format", choices=["table", "json"], default="table")
    a.set_defaults(func=cmd_history_failed)

    a = s_hist.add_parser("verify")
    a.set_defaults(func=cmd_history_verify)

    # audit
    p_audit = sub.add_parser("audit", help=_("Operational audit (read-only via SSH)."))
    s_audit = p_audit.add_subparsers(dest="sub", required=True)
    a = s_audit.add_parser(
        "server",
        help=_("Inspect users, groups, sudoers and services of one or more servers."),
        epilog=_(
            "Examples:\n"
            "  adminforge audit server --hostname web-01\n"
            "  adminforge audit server --hostname web-01 web-02\n"
            "  adminforge audit server --server-group prod\n"
            "  adminforge audit server --all"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    alvo = a.add_mutually_exclusive_group(required=True)
    alvo.add_argument("--hostname", nargs="+", help=_("One or more hostnames.")).completer = completers.hostnames
    alvo.add_argument("--server-group", dest="server_group", help=_("Audit every server in this group.")).completer = completers.server_groups
    a.add_argument("--jobs", type=int, default=1, metavar="N", help=_("Audit up to N hosts in parallel (default 1)."))
    alvo.add_argument("--all", action="store_true", help=_("Audit every registered server."))
    a.add_argument("--user", help=_("Highlight occurrences of this user."))
    a.add_argument("--group", help=_("Filter groups by substring."))
    a.add_argument("--service", help=_("Highlight occurrences of this service."))
    a.add_argument("--humans", action="store_true", help=_("Show only human users (UID >= 1000)."))
    a.set_defaults(func=cmd_audit_server)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: parse `argv` (or sys.argv when None) and dispatch to the matching `cmd_*` handler.

    Enables shell tab-completion via `argcomplete` when that package is
    installed, silently skipping it otherwise (the `# PYTHON_ARGCOMPLETE_OK`
    marker at the top of this file is what lets `register-python-argcomplete`
    find this hook). Converts a `LockBusy` exception — raised when another
    AdminForge process holds the state directory's lock — into a clean error
    message and exit code 3 instead of a traceback.
    """
    parser = _build_parser()
    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except ImportError:
        pass
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except LockBusy as e:
        ui.fail(str(e))
        return 3


if __name__ == "__main__":
    sys.exit(main())
