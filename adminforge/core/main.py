#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from adminforge import __version__
from adminforge.cli import completers, ui
from adminforge.core.nucleo import Nucleo
from adminforge.domain import (
    NivelPermissao,
    TipoAcao,
)
from adminforge.exceptions import LockOcupado
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
    return Path(args.state)


def _superadmin() -> str:
    return os.environ.get("ADMINFORGE_SUPERADMIN") or os.environ.get("USER") or "unknown"


def _split_tokens(items: list[str]) -> list[str]:
    """Aceita 'a b c' (espaco), 'a,b,c' (virgula) ou misto. Remove vazios."""
    out: list[str] = []
    for it in items:
        out.extend(s.strip() for s in it.split(",") if s.strip())
    return out


def _emit_listagem(
    args: argparse.Namespace,
    headers: list[str],
    linhas: list[list[str]],
    json_keys: list[str] | None = None,
    json_data: list[dict] | None = None,
) -> int:
    """Imprime listagem no formato pedido por --format. Default 'table'.
    Para 'json', usa json_data se fornecido (estrutura rica); senao, zip(headers, linhas)."""
    fmt = getattr(args, "format", "table")
    if fmt == "json":
        if json_data is None:
            keys = json_keys or [h.lower() for h in headers]
            json_data = [dict(zip(keys, linha)) for linha in linhas]
        print(json.dumps(json_data, indent=2, ensure_ascii=False))
        return 0
    ui.tabela(headers, linhas)
    return 0


def _nucleo(args: argparse.Namespace, com_ssh: bool = False) -> Nucleo:
    deployer = None
    if com_ssh:
        from adminforge.deployer.ssh_deployer import SSHDeployer

        chave = os.environ.get("ADMINFORGE_SSH_KEY") or str(Path.home() / ".ssh" / "adminforge_id")
        usuario = os.environ.get("ADMINFORGE_SSH_USER", "adminforge")
        criar_conta = os.environ.get("ADMINFORGE_CREATE_UNIX_USER", "true").lower() != "false"
        known_hosts = _state_dir(args) / "known_hosts"
        deployer = SSHDeployer(
            chave_privada_path=Path(chave),
            known_hosts_path=known_hosts,
            usuario_servico=usuario,
            criar_conta_unix=criar_conta,
        )
    return Nucleo.montar(_state_dir(args), deployer=deployer, superadmin=_superadmin())


# ---------------------------------------------------------------------------
# UC-1: user
# ---------------------------------------------------------------------------
def cmd_user_add(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    rc = ui.imprimir_resultado(nucleo.cadastrar_user(args.username, args.name, args.email))
    if rc != 0:
        return rc
    chave = getattr(args, "key_string", None)
    if chave is None and getattr(args, "key_file", None):
        try:
            chave = Path(args.key_file).read_text(encoding="utf-8")
        except OSError as e:
            ui.fail(_("could not read key file {f}: {e}").format(f=repr(args.key_file), e=e))
            return 2
    if chave:
        rc = ui.imprimir_resultado(nucleo.cadastrar_chave(args.username, chave))
    return rc


def cmd_user_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    users = nucleo.store.list_users()
    linhas = [[u.username, u.nome, u.email, u.status.value] for u in users]
    json_data = [
        {"username": u.username, "name": u.nome, "email": u.email, "status": u.status.value}
        for u in users
    ]
    return _emit_listagem(args, ["USERNAME", "NAME", "EMAIL", "STATUS"], linhas, json_data=json_data)


def cmd_user_show(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    u = nucleo.store.get_user(args.username)
    if not u:
        ui.fail(_("user {u} does not exist").format(u=args.username))
        return 2
    ui.heading(_("User"))
    ui.kv(_("username"), u.username)
    ui.kv(_("name"), u.nome)
    ui.kv(_("email"), u.email)
    ui.kv(_("status"), u.status.value)
    creds = nucleo.store.list_credenciais(args.username)
    ui.heading(_("Credentials ({n})").format(n=len(creds)))
    ui.tabela(["FINGERPRINT", "STATUS"], [[c.fingerprint, c.status.value] for c in creds])
    grupos = [g.nome for g in nucleo.store.list_grupos_user() if args.username in g.membros]
    ui.heading(_("Groups ({n})").format(n=len(grupos)))
    if grupos:
        ui.echo("  " + ", ".join(grupos))
    else:
        ui.secho(_("  (none)"), dim=True)
    return 0


def cmd_user_disable(args: argparse.Namespace) -> int:
    if not args.yes and not ui.confirmar(
        _("Disable {u} and revoke their keys? (apply removes them from servers)").format(u=args.username)
    ):
        ui.warn(_("operation cancelled"))
        return 1
    op = _nucleo(args).desabilitar_user(args.username)
    return ui.imprimir_resultado(op)


def cmd_user_edit(args: argparse.Namespace) -> int:
    if args.name is None and args.email is None:
        ui.fail(_("provide --name and/or --email"))
        return 2
    op = _nucleo(args).editar_user(args.username, nome=args.name, email=args.email)
    return ui.imprimir_resultado(op)


def cmd_user_rename(args: argparse.Namespace) -> int:
    op = _nucleo(args).renomear_user(args.de, args.para)
    return ui.imprimir_resultado(op)


# ---------------------------------------------------------------------------
# UC-2: user key
# ---------------------------------------------------------------------------
def cmd_user_key_add(args: argparse.Namespace) -> int:
    if args.file and args.string:
        ui.fail(_("use --file OR --string, not both"))
        return 2
    chave = args.string
    if args.file:
        try:
            chave = Path(args.file).read_text(encoding="utf-8")
        except OSError as e:
            ui.fail(_("could not read key file {f}: {e}").format(f=repr(args.file), e=e))
            return 2
    if not chave:
        ui.fail(_("provide --file or --string"))
        return 2
    op = _nucleo(args).cadastrar_chave(args.username, chave)
    return ui.imprimir_resultado(op)


def cmd_user_key_revoke(args: argparse.Namespace) -> int:
    op = _nucleo(args).revogar_chave(args.fingerprint)
    return ui.imprimir_resultado(op)


def cmd_user_key_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    creds = nucleo.store.list_credenciais(args.username)
    linhas = [[c.fingerprint, c.status.value] for c in creds]
    json_data = [{"fingerprint": c.fingerprint, "status": c.status.value} for c in creds]
    return _emit_listagem(args, ["FINGERPRINT", "STATUS"], linhas, json_data=json_data)


# ---------------------------------------------------------------------------
# UC-3: user-group
# ---------------------------------------------------------------------------
def cmd_ug_create(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).criar_grupo_user(args.name))


def cmd_ug_add_member(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).adicionar_membros_grupo_user(args.group, _split_tokens(args.username)))


def cmd_ug_remove_member(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).remover_membros_grupo_user(args.group, _split_tokens(args.username)))


def cmd_ug_delete(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).excluir_grupo_user(args.name))


def cmd_ug_rename(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).renomear_grupo_user(args.de, args.para))


def cmd_ug_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    grupos = nucleo.store.list_grupos_user()
    linhas = [[g.nome, ", ".join(g.membros) or "-"] for g in grupos]
    json_data = [{"name": g.nome, "members": list(g.membros)} for g in grupos]
    return _emit_listagem(args, ["NAME", "MEMBERS"], linhas, json_data=json_data)


# ---------------------------------------------------------------------------
# UC-4: server
# ---------------------------------------------------------------------------
def cmd_server_add(args: argparse.Namespace) -> int:
    host_key = args.host_key
    if args.auto and not host_key:
        from adminforge.deployer.ssh_deployer import SSHDeployer

        deployer = SSHDeployer(
            chave_privada_path=Path("/dev/null"),
            known_hosts_path=_state_dir(args) / "known_hosts",
        )
        try:
            host_key, fp = deployer.capturar_host_key(args.hostname, args.ip, args.port)
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
    op = _nucleo(args).cadastrar_servidor(args.hostname, args.ip, args.port, host_key)
    return ui.imprimir_resultado(op)


def cmd_server_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    servidores = nucleo.store.list_servidores()
    linhas = [
        [s.hostname, s.ipv4, str(s.porta_ssh), str(len(s.chaves_instaladas))]
        for s in servidores
    ]
    json_data = [
        {"hostname": s.hostname, "ipv4": s.ipv4, "port": s.porta_ssh,
         "installed_keys": list(s.chaves_instaladas)}
        for s in servidores
    ]
    return _emit_listagem(args, ["HOSTNAME", "IPV4", "PORT", "KEYS"], linhas, json_data=json_data)


def cmd_server_show(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    s = nucleo.store.get_servidor(args.hostname)
    if not s:
        ui.fail(_("server {h} does not exist").format(h=args.hostname))
        return 2
    ui.heading(_("Server"))
    ui.kv(_("hostname"), s.hostname)
    ui.kv(_("ipv4"), s.ipv4)
    ui.kv(_("port"), str(s.porta_ssh))
    ui.kv(_("host_key"), s.chave_host[:80] + ("..." if len(s.chave_host) > 80 else ""))
    ui.heading(_("Installed keys ({n})").format(n=len(s.chaves_instaladas)))
    linhas = []
    for item in s.chaves_instaladas:
        if isinstance(item, dict):
            linhas.append([item.get("ref", "?"), item.get("nivel", "?")])
        else:
            linhas.append([str(item), "shell"])
    ui.tabela(["REF", "LEVEL"], linhas)
    return 0


def cmd_server_remove(args: argparse.Namespace) -> int:
    if not args.yes and not ui.confirmar(
        _("Remove {h} from AdminForge? (does not clean keys on the server)").format(h=args.hostname)
    ):
        ui.warn(_("operation cancelled"))
        return 1
    return ui.imprimir_resultado(_nucleo(args).excluir_servidor(args.hostname))


def cmd_server_edit(args: argparse.Namespace) -> int:
    if args.ip is None and args.port is None and args.host_key is None:
        ui.fail(_("provide --ip, --port and/or --host-key"))
        return 2
    op = _nucleo(args).editar_servidor(
        args.hostname, ipv4=args.ip, porta=args.port, chave_host=args.host_key,
    )
    return ui.imprimir_resultado(op)


def cmd_server_rename(args: argparse.Namespace) -> int:
    op = _nucleo(args).renomear_servidor(args.de, args.para)
    return ui.imprimir_resultado(op)


# ---------------------------------------------------------------------------
# UC-5: server-group
# ---------------------------------------------------------------------------
def cmd_sg_create(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).criar_grupo_servidor(args.name))


def cmd_sg_add(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).adicionar_membros_grupo_servidor(args.group, _split_tokens(args.hostname)))


def cmd_sg_rm(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).remover_membros_grupo_servidor(args.group, _split_tokens(args.hostname)))


def cmd_sg_delete(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).excluir_grupo_servidor(args.name))


def cmd_sg_rename(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).renomear_grupo_servidor(args.de, args.para))


def cmd_sg_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    grupos = nucleo.store.list_grupos_servidor()
    linhas = [[g.nome, ", ".join(g.membros) or "-"] for g in grupos]
    json_data = [{"name": g.nome, "members": list(g.membros)} for g in grupos]
    return _emit_listagem(args, ["NAME", "MEMBERS"], linhas, json_data=json_data)


# ---------------------------------------------------------------------------
# UC-6: permission grant / revoke / list / show
# ---------------------------------------------------------------------------
def cmd_permission_show(args: argparse.Namespace) -> int:
    """Query reversa: 'a que servidores X tem acesso?' (--user) ou
    'que grupos concedem ao server-group X?' (--server-group) ou
    'que servidores o user-group X concede?' (--user-group)."""
    nucleo = _nucleo(args)
    s = nucleo.store

    # Indices uteis
    grupos_user = {g.nome: g for g in s.list_grupos_user()}
    grupos_servidor = {g.nome: g for g in s.list_grupos_servidor()}
    perms = s.list_permissoes()

    if args.user:
        user = s.get_user(args.user)
        if not user:
            ui.fail(_("user {u} does not exist").format(u=args.user))
            return 2
        user_groups = sorted(g.nome for g in grupos_user.values() if args.user in g.membros)
        # Para cada grupo do user, expandir as permissoes; agregar por (hostname).
        from adminforge.planner.planner import _merge_profile, ChaveInstalada, _maior

        agregado: dict[str, dict] = {}  # hostname -> {nivel, profile, via}
        for perm in perms:
            if perm.grupo_user not in user_groups:
                continue
            sg = grupos_servidor.get(perm.grupo_servidor)
            if not sg:
                continue
            for hostname in sg.membros:
                exist = agregado.get(hostname)
                if exist is None:
                    agregado[hostname] = {
                        "nivel": perm.nivel,
                        "profile": perm.profile,
                        "via": [perm.grupo_user],
                    }
                    continue
                ch = ChaveInstalada(ref="x", username=args.user, nivel=exist["nivel"], profile=exist["profile"])
                novo_nivel = _maior(exist["nivel"], perm.nivel)
                novo_profile = _merge_profile(ch, perm.nivel, perm.profile, novo_nivel)
                agregado[hostname] = {
                    "nivel": novo_nivel,
                    "profile": novo_profile,
                    "via": exist["via"] + [perm.grupo_user],
                }

        if getattr(args, "format", "table") == "json":
            print(json.dumps({
                "user": args.user,
                "groups": user_groups,
                "servers": [
                    {
                        "hostname": h,
                        "level": v["nivel"].value,
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
        linhas = [
            [h, v["nivel"].value, v["profile"] or "—", ", ".join(sorted(set(v["via"])))]
            for h, v in sorted(agregado.items())
        ]
        ui.tabela(["HOSTNAME", "LEVEL", "PROFILE", "VIA"], linhas)
        return 0

    if args.user_group:
        if args.user_group not in grupos_user:
            ui.fail(_("user-group {g} does not exist").format(g=args.user_group))
            return 2
        relevantes = [p for p in perms if p.grupo_user == args.user_group]
        json_data = [
            {"server_group": p.grupo_servidor, "level": p.nivel.value, "profile": p.profile}
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
            [[p.grupo_servidor, p.nivel.value, p.profile or "—"] for p in relevantes],
        )
        return 0

    if args.server_group:
        if args.server_group not in grupos_servidor:
            ui.fail(_("server-group {g} does not exist").format(g=args.server_group))
            return 2
        relevantes = [p for p in perms if p.grupo_servidor == args.server_group]
        if getattr(args, "format", "table") == "json":
            print(json.dumps({
                "server_group": args.server_group,
                "grants": [
                    {"user_group": p.grupo_user, "level": p.nivel.value, "profile": p.profile}
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
            [[p.grupo_user, p.nivel.value, p.profile or "—"] for p in relevantes],
        )
        return 0

    ui.fail(_("provide one of: --user, --user-group, --server-group"))
    return 2


def cmd_permission_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    perms = nucleo.store.list_permissoes()
    linhas = [
        [p.grupo_user, p.grupo_servidor, p.nivel.value, p.profile or "—"] for p in perms
    ]
    json_data = [
        {"user_group": p.grupo_user, "server_group": p.grupo_servidor,
         "level": p.nivel.value, "profile": p.profile}
        for p in perms
    ]
    return _emit_listagem(
        args, ["USER_GROUP", "SERVER_GROUP", "LEVEL", "PROFILE"], linhas, json_data=json_data
    )


def cmd_permission_grant(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(
        _nucleo(args).conceder(
            args.user_group, args.server_group, NivelPermissao(args.level),
            profile=getattr(args, "profile", None),
        )
    )


# ---------------------------------------------------------------------------
# sudo-profile
# ---------------------------------------------------------------------------
def cmd_sudo_profile_create(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).criar_sudo_profile(args.name, args.command))


def cmd_sudo_profile_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    profiles = nucleo.store.list_sudo_profiles()
    linhas = []
    for p in profiles:
        comandos_str = ", ".join(p.comandos)
        if len(comandos_str) > 80:
            comandos_str = comandos_str[:77] + "…"
        linhas.append([p.nome, str(len(p.comandos)), comandos_str])
    json_data = [{"name": p.nome, "commands": list(p.comandos)} for p in profiles]
    return _emit_listagem(args, ["NAME", "#CMDS", "COMMANDS"], linhas, json_data=json_data)


def cmd_sudo_profile_show(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    p = nucleo.store.get_sudo_profile(args.name)
    if not p:
        ui.fail(_("sudo-profile {n} does not exist").format(n=args.name))
        return 2
    ui.heading(_("sudo-profile {n}").format(n=p.nome))
    for c in p.comandos:
        ui.echo(f"  {c}")
    return 0


def cmd_sudo_profile_delete(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).excluir_sudo_profile(args.name))


def cmd_sudo_profile_rename(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).renomear_sudo_profile(args.de, args.para))


def cmd_permission_revoke(args: argparse.Namespace) -> int:
    if not args.yes and not ui.confirmar(
        _("Revoke {ug} -> {sg}? (apply removes keys)").format(ug=args.user_group, sg=args.server_group)
    ):
        ui.warn(_("operation cancelled"))
        return 1
    return ui.imprimir_resultado(_nucleo(args).revogar(args.user_group, args.server_group))


# ---------------------------------------------------------------------------
# UC-7 / UC-8: preview / apply
# ---------------------------------------------------------------------------
def cmd_preview(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    subacoes = nucleo.preview()
    if not subacoes:
        ui.ok(_("nothing to do — state in sync"))
        return 0
    ui.info(_("{n} sub-actions across {s} servers").format(n=len(subacoes), s=len({sb.servidor for sb in subacoes})))
    for hostname in sorted({s.servidor for s in subacoes}):
        ui.heading(hostname)
        for s in subacoes:
            if s.servidor != hostname:
                continue
            sinal = "+" if s.acao == TipoAcao.ADICIONAR_CHAVE else "-"
            cor = ui._GREEN if s.acao == TipoAcao.ADICIONAR_CHAVE else ui._RED
            ui.secho(
                f"  {sinal} {s.acao.value:18} {s.credencial:50} {(s.nivel.value if s.nivel else '-')}",
                cor,
            )
    return 0


def _imprimir_diff(nucleo: Nucleo, subacoes: list) -> None:
    """Mostra unified diff do authorized_keys de cada (servidor, username) afetado."""
    import difflib
    from adminforge import authorized_keys as ak

    por_user: dict[tuple[str, str], list] = {}
    for s in subacoes:
        if s.acao not in (TipoAcao.ADICIONAR_CHAVE, TipoAcao.REMOVER_CHAVE):
            continue
        if not s.username:
            continue
        por_user.setdefault((s.servidor, s.username), []).append(s)

    ui.heading(_("Diff (authorized_keys)"))
    for (hostname, username), lote in sorted(por_user.items()):
        servidor = nucleo.store.get_servidor(hostname)
        if servidor is None:
            continue
        ui.secho(f"  {hostname}:{username}", bold=True)
        # ler_authorized_keys pode falhar (ssh, host_key etc); nao deve abortar o diff dos demais.
        try:
            atual, ok = nucleo.deployer.ler_authorized_keys(servidor, username)
        except Exception as e:
            ui.fail(_("    ssh: {e}").format(e=e))
            continue
        if not ok:
            ui.fail(_("    ssh: could not read authorized_keys (sudo blocked?)"))
            continue
        novo = atual
        for s in lote:
            if s.acao == TipoAcao.ADICIONAR_CHAVE and s.chave_publica and s.credencial:
                novo = ak.substituir_bloco(novo, s.credencial, ak.bloco(s.credencial, s.chave_publica))
            elif s.acao == TipoAcao.REMOVER_CHAVE and s.credencial:
                novo = ak.substituir_bloco(novo, s.credencial, "")
        for linha in difflib.unified_diff(
            atual.splitlines(), novo.splitlines(),
            fromfile="current", tofile="planned", lineterm="",
        ):
            if linha.startswith("+") and not linha.startswith("+++"):
                ui.secho(f"    {linha}", ui._GREEN)
            elif linha.startswith("-") and not linha.startswith("---"):
                ui.secho(f"    {linha}", ui._RED)
            elif linha.startswith("@@"):
                ui.secho(f"    {linha}", ui._CYAN)
            else:
                ui.echo(f"    {linha}")


_SUDOERS_PREFIX = "adminforge-"


def _esperado_do_servidor(servidor) -> tuple[dict[str, str], dict[str, str | None]]:
    """Lê chaves_instaladas e retorna ({ref: username} dos blocos,
    {username: profile} dos que têm sudo — profile None = sudo total)."""
    blocks: dict[str, str] = {}
    sudo: dict[str, str | None] = {}
    for item in servidor.chaves_instaladas:
        if isinstance(item, dict):
            ref = item["ref"]
            u = item.get("username") or ref.split(":", 1)[0]
            blocks[ref] = u
            if item.get("nivel") == "sudo":
                sudo[u] = item.get("profile")
        else:
            blocks[item] = item.split(":", 1)[0]
    return blocks, sudo


def _regra_e_full_sudo(regra: str) -> bool:
    """Heurística: a regra do sudoers concede TODOS os comandos (NOPASSWD:ALL).
    Confiável porque o AdminForge escreve esses arquivos ele mesmo."""
    return "NOPASSWD:ALL" in regra.replace(" ", "").upper()


def cmd_apply_verify(args: argparse.Namespace) -> int:
    """Compara o estado declarado vs o real do servidor: blocos AdminForge no
    authorized_keys + arquivos `adminforge-<user>` em /etc/sudoers.d/ (presença
    e nível — sudo total vs perfil restrito)."""
    from adminforge import authorized_keys as ak

    nucleo = _nucleo(args, com_ssh=not args.dry_run)
    total_ok = 0
    total_div = 0
    erros_ssh: list[str] = []

    for servidor in nucleo.store.list_servidores():
        esperado_blocks, esperado_sudo = _esperado_do_servidor(servidor)
        ui.heading(servidor.hostname)

        # 1) authorized_keys — só se há blocos declarados
        if esperado_blocks:
            ssh_falhou = False
            real_blocks: dict[str, str] = {}
            for u in sorted(set(esperado_blocks.values())):
                try:
                    conteudo, ok = nucleo.deployer.ler_authorized_keys(servidor, u)
                except Exception as e:
                    ui.fail(_("  ssh failed reading {u}: {e}").format(u=u, e=e))
                    ssh_falhou = True
                    break
                if not ok:
                    ui.fail(_("  ssh: could not read authorized_keys for {u} (sudo blocked?)").format(u=u))
                    ssh_falhou = True
                    break
                for ref in ak.parse_blocos(conteudo):
                    real_blocks[ref] = u
            if ssh_falhou:
                erros_ssh.append(servidor.hostname)
                continue
            for ref, username in sorted(esperado_blocks.items()):
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

        # 2) sudoers — sempre roda (mesmo sem blocos declarados, p/ achar arquivos órfãos)
        try:
            relatorio = nucleo.deployer.inspecionar(servidor)
        except Exception as e:
            ui.fail(_("  ssh failed listing sudoers: {e}").format(e=e))
            erros_ssh.append(servidor.hostname)
            continue
        if "erro" in relatorio:
            ui.fail(_("  ssh failed listing sudoers: {e}").format(e=relatorio["erro"]))
            erros_ssh.append(servidor.hostname)
            continue
        arquivos = relatorio.get("sudoers_arquivos") or []
        real_sudo = {
            a["nome"][len(_SUDOERS_PREFIX):] for a in arquivos
            if a.get("adminforge") and a.get("nome", "").startswith(_SUDOERS_PREFIX)
        }
        # regras reais por usuário (1ª coluna; ignora regras de grupo '%...')
        real_regras: dict[str, list[str]] = {}
        for regra in relatorio.get("sudoers_regras") or []:
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
                nivel = "full" if esperado_full else "restricted"
                ui.ok(_("  {u} sudoers — present ({lvl})").format(u=f"{u:20}", lvl=nivel))
                total_ok += 1
        for u in sorted(real_sudo - set(esperado_sudo)):
            ui.warn(_("  {u} sudoers — present on server but not declared").format(u=f"{u:20}"))
            total_div += 1

    ui.echo()
    ui.heading(_("Summary"))
    ui.kv(_("matches"), str(total_ok))
    ui.kv(_("divergences"), str(total_div))
    if erros_ssh:
        ui.kv(_("ssh errors"), ", ".join(erros_ssh))
    return 0 if total_div == 0 and not erros_ssh else 2


def cmd_apply(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args, com_ssh=not args.dry_run)
    subacoes = nucleo.preview()
    if not subacoes:
        ui.ok(_("nothing to do — state in sync"))
        return 0

    ui.info(_("{n} sub-actions across {s} servers").format(n=len(subacoes), s=len({sb.servidor for sb in subacoes})))
    for hostname in sorted({s.servidor for s in subacoes}):
        ui.secho(f"  {hostname}", bold=True)
        for s in subacoes:
            if s.servidor != hostname:
                continue
            sinal = "+" if s.acao == TipoAcao.ADICIONAR_CHAVE else "-"
            ui.echo(f"    {sinal} {s.acao.value:18} {s.credencial}")

    if args.diff:
        _imprimir_diff(nucleo, subacoes)

    if not args.yes and not ui.confirmar(_("Apply {n} change(s) now?").format(n=len(subacoes))):
        ui.warn(_("apply cancelled"))
        return 1

    op = nucleo.aplicar(jobs=max(1, getattr(args, "jobs", 1)))
    sucessos = sum(1 for s in op.subacoes if s.status == "sucesso")
    falhas = sum(1 for s in op.subacoes if s.status == "falha")
    ui.heading(_("Result"))
    for s in op.subacoes:
        if s.status == "sucesso":
            ui.ok(f"{s.servidor:24} {s.acao.value:18} {s.credencial or ''}")
        else:
            ui.fail(f"{s.servidor:24} {s.acao.value:18} {s.credencial or ''} — {s.erro}")
    ui.echo()
    ui.kv(_("operation"), op.id)
    ui.kv(_("status"), op.status.value.upper())
    ui.kv(_("successes"), str(sucessos))
    ui.kv(_("failures"), str(falhas))
    if falhas:
        ui.echo()
        ui.info(_("re-running 'adminforge apply' retries only the failed sub-actions"))
        return 1 if sucessos else 2
    return 0


# ---------------------------------------------------------------------------
# UC-9: history
# ---------------------------------------------------------------------------
def _historico_linhas_e_json(ops: list) -> tuple[list[list[str]], list[dict]]:
    linhas = [
        [
            op.id,
            op.momento.strftime("%Y-%m-%d %H:%M"),
            op.superadmin,
            op.comando[:40],
            op.status.value.upper(),
        ]
        for op in ops
    ]
    json_data = [
        {
            "id": op.id,
            "when": op.momento.isoformat(timespec="seconds"),
            "superadmin": op.superadmin,
            "command": op.comando,
            "status": op.status.value,
            "subactions": len(op.subacoes),
        }
        for op in ops
    ]
    return linhas, json_data


def cmd_history_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    ops = nucleo.auditor.listar(args.limit)
    linhas, json_data = _historico_linhas_e_json(ops)
    return _emit_listagem(
        args, ["ID", "WHEN", "SUPERADMIN", "COMMAND", "STATUS"], linhas, json_data=json_data
    )


def cmd_history_show(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    op = nucleo.auditor.buscar(args.op_id)
    if not op:
        ui.fail(_("operation {i} does not exist").format(i=args.op_id))
        return 2
    ui.heading(_("Operation"))
    ui.kv(_("id"), op.id)
    ui.kv(_("when"), op.momento.isoformat())
    ui.kv(_("superadmin"), op.superadmin)
    ui.kv(_("command"), op.comando)
    ui.kv(_("status"), op.status.value)
    ui.kv(_("hash"), op.hash or "-")
    ui.kv(_("prev_hash"), op.hash_anterior or "-")
    ui.heading(_("Sub-actions ({n})").format(n=len(op.subacoes)))
    linhas = [
        [
            s.servidor or "-",
            s.acao.value,
            s.credencial or s.username or "-",
            s.status,
            (s.erro or s.mensagem or "")[:60],
        ]
        for s in op.subacoes
    ]
    ui.tabela(["SERVER", "ACTION", "TARGET", "STATUS", "DETAIL"], linhas)
    return 0


def cmd_history_failed(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    ops = nucleo.auditor.listar_falhas(args.limit)
    linhas, json_data = _historico_linhas_e_json(ops)
    return _emit_listagem(
        args, ["ID", "WHEN", "SUPERADMIN", "COMMAND", "STATUS"], linhas, json_data=json_data
    )


def cmd_history_verify(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    try:
        _ok, ultimo = nucleo.auditor.verificar_cadeia()
    except Exception as e:
        ui.fail(_("chain broken: {e}").format(e=e))
        return 2
    ui.ok(_("chain intact (last hash: {h})").format(h=ultimo or "-"))
    return 0


# ---------------------------------------------------------------------------
# Dump global
# ---------------------------------------------------------------------------
def _coletar_estado(nucleo: Nucleo) -> dict:
    return {
        "users": [
            {
                "username": u.username,
                "name": u.nome,
                "email": u.email,
                "status": u.status.value,
                "credentials": [
                    {"fingerprint": c.fingerprint, "status": c.status.value}
                    for c in nucleo.store.list_credenciais(u.username)
                ],
            }
            for u in nucleo.store.list_users()
        ],
        "user_groups": [
            {"name": g.nome, "members": list(g.membros)}
            for g in nucleo.store.list_grupos_user()
        ],
        "servers": [
            {
                "hostname": s.hostname,
                "ipv4": s.ipv4,
                "port": s.porta_ssh,
                "host_key": s.chave_host,
                "installed_keys": list(s.chaves_instaladas),
            }
            for s in nucleo.store.list_servidores()
        ],
        "server_groups": [
            {"name": g.nome, "members": list(g.membros)}
            for g in nucleo.store.list_grupos_servidor()
        ],
        "permissions": [
            {
                "user_group": p.grupo_user,
                "server_group": p.grupo_servidor,
                "level": p.nivel.value,
                "profile": p.profile,
            }
            for p in nucleo.store.list_permissoes()
        ],
        "sudo_profiles": [
            {"name": p.nome, "commands": list(p.comandos)}
            for p in nucleo.store.list_sudo_profiles()
        ],
    }


def cmd_status(args: argparse.Namespace) -> int:
    """Overview rapido tipo 'git status': contagens, pendencias e ultima operacao."""
    nucleo = _nucleo(args)
    s = nucleo.store
    counts = {
        "users": len(s.list_users()),
        "user_groups": len(s.list_grupos_user()),
        "servers": len(s.list_servidores()),
        "server_groups": len(s.list_grupos_servidor()),
        "permissions": len(s.list_permissoes()),
        "sudo_profiles": len(s.list_sudo_profiles()),
    }

    try:
        pendentes = nucleo.preview()
        pendentes_servers = len({sb.servidor for sb in pendentes})
        pendentes_erro = None
    except Exception as e:
        pendentes = []
        pendentes_servers = 0
        pendentes_erro = str(e)

    ultima = nucleo.auditor.listar(1)
    ultima_op = ultima[0] if ultima else None

    cadeia_ok = True
    cadeia_erro = None
    try:
        nucleo.auditor.verificar_cadeia()
    except Exception as e:
        cadeia_ok = False
        cadeia_erro = str(e)

    if getattr(args, "format", "table") == "json":
        print(json.dumps({
            "counts": counts,
            "pending": {
                "subactions": len(pendentes),
                "servers": pendentes_servers,
                "error": pendentes_erro,
            },
            "last_operation": (
                {
                    "id": ultima_op.id,
                    "command": ultima_op.comando,
                    "status": ultima_op.status.value,
                    "when": ultima_op.momento.isoformat(timespec="seconds"),
                    "superadmin": ultima_op.superadmin,
                } if ultima_op else None
            ),
            "history_chain": {"ok": cadeia_ok, "error": cadeia_erro},
        }, indent=2, ensure_ascii=False))
        return 0

    ui.heading(_("State"))
    ui.echo(_("  {users} users, {ugroups} user-groups, {servers} servers, {sgroups} server-groups, {perms} permissions, {sprofiles} sudo-profiles").format(
        users=counts["users"], ugroups=counts["user_groups"], servers=counts["servers"],
        sgroups=counts["server_groups"], perms=counts["permissions"], sprofiles=counts["sudo_profiles"]))

    ui.heading(_("Pending"))
    if pendentes_erro:
        ui.fail(_("  could not compute delta: {e}").format(e=pendentes_erro))
    elif not pendentes:
        ui.ok(_("  no pending changes — state is in sync with declared"))
    else:
        ui.warn(_("  {n} sub-action(s) across {s} server(s) — run 'adminforge preview' to see, 'adminforge apply' to apply").format(n=len(pendentes), s=pendentes_servers))

    ui.heading(_("Last operation"))
    if ultima_op is None:
        ui.secho(_("  (no operations yet)"), dim=True)
    else:
        ui.kv(_("id"), ultima_op.id)
        ui.kv(_("command"), ultima_op.comando)
        ui.kv(_("status"), ultima_op.status.value)
        ui.kv(_("when"), ultima_op.momento.isoformat(timespec="seconds"))
        ui.kv(_("by"), ultima_op.superadmin)

    ui.heading(_("History chain"))
    if cadeia_ok:
        ui.ok(_("  intact"))
    else:
        ui.fail(_("  broken: {e}").format(e=cadeia_erro))

    if counts["users"] == 0:
        ui.echo()
        ui.info(_("Empty state. Try: adminforge user add --username <name> --name '<full>' --email <email>"))
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    estado = _coletar_estado(_nucleo(args))
    if args.format == "json":
        print(json.dumps(estado, indent=2, ensure_ascii=False))
        return 0

    ui.heading(_("Users ({n})").format(n=len(estado["users"])))
    ui.tabela(
        ["USERNAME", "NOME", "EMAIL", "STATUS", "CHAVES"],
        [
            [u["username"], u["name"], u["email"], u["status"], str(len(u["credentials"]))]
            for u in estado["users"]
        ],
    )

    ui.heading(_("User groups ({n})").format(n=len(estado["user_groups"])))
    ui.tabela(
        ["NOME", "MEMBROS"],
        [[g["name"], ", ".join(g["members"]) or "-"] for g in estado["user_groups"]],
    )

    ui.heading(_("Servers ({n})").format(n=len(estado["servers"])))
    ui.tabela(
        ["HOSTNAME", "IPV4", "PORTA", "CHAVES_INSTALADAS"],
        [
            [s["hostname"], s["ipv4"], str(s["port"]), str(len(s["installed_keys"]))]
            for s in estado["servers"]
        ],
    )

    ui.heading(_("Server groups ({n})").format(n=len(estado["server_groups"])))
    ui.tabela(
        ["NOME", "MEMBROS"],
        [[g["name"], ", ".join(g["members"]) or "-"] for g in estado["server_groups"]],
    )

    ui.heading(_("Permissions ({n})").format(n=len(estado["permissions"])))
    ui.tabela(
        ["USER_GROUP", "SERVER_GROUP", "LEVEL", "PROFILE"],
        [
            [p["user_group"], p["server_group"], p["level"], p.get("profile") or "—"]
            for p in estado["permissions"]
        ],
    )

    ui.heading(_("Sudo profiles ({n})").format(n=len(estado["sudo_profiles"])))
    ui.tabela(
        ["NAME", "#CMDS", "COMMANDS"],
        [[p["name"], str(len(p["commands"])), ", ".join(p["commands"])[:60]] for p in estado["sudo_profiles"]],
    )
    return 0


# ---------------------------------------------------------------------------
# UC-10: audit server
# ---------------------------------------------------------------------------
def _hosts_para_auditar(nucleo: Nucleo, args: argparse.Namespace) -> list[str] | None:
    """Resolve o conjunto de hostnames a auditar. Retorna None quando já reportou
    um erro (ex.: server-group inexistente) — o chamador não imprime nada a mais."""
    if getattr(args, "all", False):
        return [s.hostname for s in nucleo.store.list_servidores()]
    if getattr(args, "server_group", None):
        g = nucleo.store.get_grupo_servidor(args.server_group)
        if not g:
            ui.fail(_("server-group {g} does not exist").format(g=repr(args.server_group)))
            return None
        return list(g.membros)
    return list(args.hostname or [])


def cmd_audit_server(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args, com_ssh=True)
    hostnames = _hosts_para_auditar(nucleo, args)
    if hostnames is None:
        return 2
    if not hostnames:
        ui.fail(_("no servers to audit"))
        return 2
    qualquer_falha = False
    for i, hostname in enumerate(hostnames):
        if i > 0:
            ui.echo()
            ui.secho("─" * 60, dim=True)
        op, relatorio = nucleo.auditar_servidor(hostname)
        if "erro" in relatorio:
            ui.fail(f"{hostname}: {relatorio['erro']}")
            qualquer_falha = True
            continue
        _imprimir_audit_relatorio(args, hostname, op, relatorio)
    return 2 if qualquer_falha else 0


def _imprimir_audit_relatorio(args: argparse.Namespace, hostname: str, op, relatorio: dict) -> None:
    usuarios = relatorio.get("usuarios", [])
    grupos = relatorio.get("grupos", [])
    servicos = relatorio.get("servicos", [])
    arquivos_sudoers = relatorio.get("sudoers_arquivos", [])
    regras_sudo = relatorio.get("sudoers_regras", [])

    if args.humans:
        usuarios = [u for u in usuarios if u.get("categoria") == "human"]

    ui.heading(hostname)
    # Users
    titulo = _("Users ({n})").format(n=len(usuarios))
    if args.humans:
        titulo = _("Users ({n}) — humans only (UID >= 1000)").format(n=len(usuarios))
    ui.heading(titulo)
    if usuarios:
        linhas = []
        for u in usuarios:
            destacar = bool(args.user and args.user in u["nome"])
            marca = "*" if destacar else " "
            grupos_str = ",".join(u.get("grupos", []))[:40]
            sudo_str = "yes" if u.get("sudo") else "—"
            linhas.append([marca, u["nome"], str(u["uid"]), u["categoria"], u["shell"], grupos_str, sudo_str])
        ui.tabela([" ", "USERNAME", "UID", "CATEGORY", "SHELL", "GROUPS", "SUDO"], linhas)
    else:
        ui.secho(_("  (none)"), dim=True)

    # Groups
    if args.group:
        alvo = [g for g in grupos if args.group in g["nome"]]
        ui.heading(_("Groups matching {g} ({n})").format(g=repr(args.group), n=len(alvo)))
        for g in alvo:
            membros = ", ".join(g["membros"]) or "-"
            ui.echo(f"  {g['nome']} (gid={g['gid']}): {membros}")
    else:
        ui.heading(_("Groups ({n})").format(n=len(grupos)))
        com_membros = [g for g in grupos if g["membros"]]
        if com_membros:
            ui.tabela(
                ["NAME", "GID", "MEMBERS"],
                [[g["nome"], str(g["gid"]), ", ".join(g["membros"])[:60]] for g in com_membros],
            )
        else:
            ui.secho(_("  (no group with explicit members)"), dim=True)

    # Sudoers
    ui.heading(_("Sudoers — files in /etc/sudoers.d/ ({n})").format(n=len(arquivos_sudoers)))
    if arquivos_sudoers:
        for a in arquivos_sudoers:
            origem = "adminforge" if a["adminforge"] else "manual"
            cor = ui._GREEN if a["adminforge"] else ui._YELLOW
            ui.secho(f"  [{origem:10}] {a['nome']}", cor)
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
        nomes = {u["nome"] for u in usuarios}
        if args.user in nomes and not any(args.user in s for s in servicos):
            alertas.append(_("user {u} exists but no matching service is running").format(u=repr(args.user)))
    sudoers_manuais = [a["nome"] for a in arquivos_sudoers if not a["adminforge"]]
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

    # user key (subcomando aninhado de user)
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

    # permission — todas as acoes de gerenciamento de permissoes ficam sob este menu
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
    p_apply.set_defaults(func=cmd_apply)
    s_apply = p_apply.add_subparsers(dest="apply_sub", required=False)
    a = s_apply.add_parser(
        "verify",
        help=_("Compare declared state vs real servers (authorized_keys + sudoers)."),
    )
    a.add_argument("--dry-run", action="store_true")
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
    alvo.add_argument("--all", action="store_true", help=_("Audit every registered server."))
    a.add_argument("--user", help=_("Highlight occurrences of this user."))
    a.add_argument("--group", help=_("Filter groups by substring."))
    a.add_argument("--service", help=_("Highlight occurrences of this service."))
    a.add_argument("--humans", action="store_true", help=_("Show only human users (UID >= 1000)."))
    a.set_defaults(func=cmd_audit_server)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except ImportError:
        pass
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except LockOcupado as e:
        ui.fail(str(e))
        return 3


if __name__ == "__main__":
    sys.exit(main())
