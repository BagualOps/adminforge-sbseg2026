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


EPILOG_GERAL = """\
EXAMPLES
  adminforge user add --username marina --name "Marina Silva" --email marina@empresa.com
  adminforge user key add --username marina --file ~/.ssh/marina.pub
  adminforge user-group create --name sysadmins
  adminforge user-group add-member --group sysadmins --username marina
  adminforge server add --hostname web-01 --ip 10.0.0.10 --auto
  adminforge server-group create --name producao
  adminforge server-group add-member --group producao --hostname web-01
  adminforge grant --user-group sysadmins --server-group producao --level sudo
  adminforge preview
  adminforge apply

DOCS
  Detailed model: docs/modelagem-v1.pdf
  Use-case cookbook: docs/USAGE.md
"""


def _state_dir(args: argparse.Namespace) -> Path:
    return Path(args.state)


def _superadmin() -> str:
    return os.environ.get("ADMINFORGE_SUPERADMIN") or os.environ.get("USER") or "desconhecido"


def _split_tokens(items: list[str]) -> list[str]:
    """Aceita 'a b c' (espaco), 'a,b,c' (virgula) ou misto. Remove vazios."""
    out: list[str] = []
    for it in items:
        out.extend(s.strip() for s in it.split(",") if s.strip())
    return out


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
    op = _nucleo(args).cadastrar_user(args.username, args.name, args.email)
    return ui.imprimir_resultado(op)


def cmd_user_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    linhas = [[u.username, u.nome, u.email, u.status.value] for u in nucleo.store.list_users()]
    ui.tabela(["USERNAME", "NAME", "EMAIL", "STATUS"], linhas)
    return 0


def cmd_user_show(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    u = nucleo.store.get_user(args.username)
    if not u:
        ui.fail(f"user '{args.username}' does not exist")
        return 2
    ui.heading("User")
    ui.kv("username", u.username)
    ui.kv("name", u.nome)
    ui.kv("email", u.email)
    ui.kv("status", u.status.value)
    creds = nucleo.store.list_credenciais(args.username)
    ui.heading(f"Credentials ({len(creds)})")
    ui.tabela(["FINGERPRINT", "STATUS"], [[c.fingerprint, c.status.value] for c in creds])
    grupos = [g.nome for g in nucleo.store.list_grupos_user() if args.username in g.membros]
    ui.heading(f"Groups ({len(grupos)})")
    if grupos:
        ui.echo("  " + ", ".join(grupos))
    else:
        ui.secho("  (none)", dim=True)
    return 0


def cmd_user_disable(args: argparse.Namespace) -> int:
    if not args.yes and not ui.confirmar(
        f"Disable '{args.username}' and revoke their keys? (apply removes them from servers)"
    ):
        ui.warn("operation cancelled")
        return 1
    op = _nucleo(args).desabilitar_user(args.username)
    return ui.imprimir_resultado(op)


# ---------------------------------------------------------------------------
# UC-2: user key
# ---------------------------------------------------------------------------
def cmd_user_key_add(args: argparse.Namespace) -> int:
    if args.file and args.string:
        ui.fail("use --file OR --string, not both")
        return 2
    chave = args.string
    if args.file:
        chave = Path(args.file).read_text(encoding="utf-8")
    if not chave:
        ui.fail("provide --file or --string")
        return 2
    op = _nucleo(args).cadastrar_chave(args.username, chave)
    return ui.imprimir_resultado(op)


def cmd_user_key_revoke(args: argparse.Namespace) -> int:
    op = _nucleo(args).revogar_chave(args.fingerprint)
    return ui.imprimir_resultado(op)


def cmd_user_key_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    creds = nucleo.store.list_credenciais(args.username)
    ui.tabela(["FINGERPRINT", "STATUS"], [[c.fingerprint, c.status.value] for c in creds])
    return 0


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


def cmd_ug_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    linhas = [[g.nome, ", ".join(g.membros) or "-"] for g in nucleo.store.list_grupos_user()]
    ui.tabela(["NAME", "MEMBERS"], linhas)
    return 0


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
            ui.fail(f"failed to capture host_key: {e}")
            return 2
        ui.info(f"captured host_key: {fp}")
        if not ui.confirmar("Confirm the fingerprint?"):
            ui.warn("registration aborted")
            return 1
    if not host_key:
        ui.fail("provide --host-key or --auto")
        return 2
    op = _nucleo(args).cadastrar_servidor(args.hostname, args.ip, args.port, host_key)
    return ui.imprimir_resultado(op)


def cmd_server_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    linhas = [
        [s.hostname, s.ipv4, str(s.porta_ssh), str(len(s.chaves_instaladas))]
        for s in nucleo.store.list_servidores()
    ]
    ui.tabela(["HOSTNAME", "IPV4", "PORT", "KEYS"], linhas)
    return 0


def cmd_server_show(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    s = nucleo.store.get_servidor(args.hostname)
    if not s:
        ui.fail(f"server '{args.hostname}' does not exist")
        return 2
    ui.heading("Server")
    ui.kv("hostname", s.hostname)
    ui.kv("ipv4", s.ipv4)
    ui.kv("port", str(s.porta_ssh))
    ui.kv("host_key", s.chave_host[:80] + ("..." if len(s.chave_host) > 80 else ""))
    ui.heading(f"Installed keys ({len(s.chaves_instaladas)})")
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
        f"Remove '{args.hostname}' from AdminForge? (does not clean keys on the server)"
    ):
        ui.warn("operation cancelled")
        return 1
    return ui.imprimir_resultado(_nucleo(args).excluir_servidor(args.hostname))


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


def cmd_sg_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    linhas = [[g.nome, ", ".join(g.membros) or "-"] for g in nucleo.store.list_grupos_servidor()]
    ui.tabela(["NAME", "MEMBERS"], linhas)
    return 0


# ---------------------------------------------------------------------------
# UC-6: grant / revoke
# ---------------------------------------------------------------------------
def cmd_grant(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(
        _nucleo(args).conceder(
            args.user_group, args.server_group, NivelPermissao(args.level),
            profile=getattr(args, "profile", None),
        )
    )


def cmd_revoke(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).revogar(args.user_group, args.server_group))


# ---------------------------------------------------------------------------
# permission CRUD (list/update/delete; grant/revoke continue como atalhos)
# ---------------------------------------------------------------------------
def cmd_permission_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    perms = nucleo.store.list_permissoes()
    linhas = [
        [p.grupo_user, p.grupo_servidor, p.nivel.value, p.profile or "—"] for p in perms
    ]
    ui.tabela(["USER_GROUP", "SERVER_GROUP", "LEVEL", "PROFILE"], linhas)
    return 0


def cmd_permission_update(args: argparse.Namespace) -> int:
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
    linhas = [[p.nome, str(len(p.comandos)), ", ".join(p.comandos)[:80]] for p in profiles]
    ui.tabela(["NAME", "#CMDS", "COMMANDS"], linhas)
    return 0


def cmd_sudo_profile_show(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    p = nucleo.store.get_sudo_profile(args.name)
    if not p:
        ui.fail(f"sudo-profile '{args.name}' does not exist")
        return 2
    ui.heading(f"sudo-profile {p.nome}")
    for c in p.comandos:
        ui.echo(f"  {c}")
    return 0


def cmd_sudo_profile_delete(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).excluir_sudo_profile(args.name))


def cmd_permission_delete(args: argparse.Namespace) -> int:
    if not args.yes and not ui.confirmar(
        f"Revoke '{args.user_group}' -> '{args.server_group}'? (apply removes keys)"
    ):
        ui.warn("operation cancelled")
        return 1
    return ui.imprimir_resultado(_nucleo(args).revogar(args.user_group, args.server_group))


# ---------------------------------------------------------------------------
# UC-7 / UC-8: preview / apply
# ---------------------------------------------------------------------------
def cmd_preview(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    subacoes = nucleo.preview()
    if not subacoes:
        ui.ok("nothing to do — state in sync")
        return 0
    ui.info(f"{len(subacoes)} sub-actions across {len({s.servidor for s in subacoes})} servers")
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

    ui.heading("Diff (authorized_keys)")
    for (hostname, username), lote in sorted(por_user.items()):
        servidor = nucleo.store.get_servidor(hostname)
        if servidor is None:
            continue
        atual = nucleo.deployer.ler_authorized_keys(servidor, username)
        novo = atual
        for s in lote:
            if s.acao == TipoAcao.ADICIONAR_CHAVE and s.chave_publica and s.credencial:
                novo = ak.substituir_bloco(novo, s.credencial, ak.bloco(s.credencial, s.chave_publica))
            elif s.acao == TipoAcao.REMOVER_CHAVE and s.credencial:
                novo = ak.substituir_bloco(novo, s.credencial, "")
        ui.secho(f"  {hostname}:{username}", bold=True)
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


def cmd_apply_verify(args: argparse.Namespace) -> int:
    """Compara chaves_instaladas declarado vs blocos AdminForge reais via SSH."""
    from adminforge import authorized_keys as ak

    nucleo = _nucleo(args, com_ssh=not args.dry_run)
    total_ok = 0
    total_div = 0
    erros_ssh: list[str] = []

    for servidor in nucleo.store.list_servidores():
        # esperado: dict ref -> nome_user
        esperado: dict[str, str] = {}
        for item in servidor.chaves_instaladas:
            if isinstance(item, dict):
                esperado[item["ref"]] = item.get("username") or item["ref"].split(":", 1)[0]
            else:
                esperado[item] = item.split(":", 1)[0]

        # users a consultar (declarados + nada extra; extras seriam descobertos via audit server)
        usernames = sorted(set(esperado.values()))

        ui.heading(servidor.hostname)
        if not usernames:
            ui.secho("  (no installed keys declared)", dim=True)
            continue

        ssh_falhou = False
        real: dict[str, str] = {}
        for u in usernames:
            try:
                conteudo = nucleo.deployer.ler_authorized_keys(servidor, u)
            except Exception as e:
                ui.fail(f"  ssh failed reading {u}: {e}")
                ssh_falhou = True
                break
            for ref in ak.parse_blocos(conteudo):
                real[ref] = u

        if ssh_falhou:
            erros_ssh.append(servidor.hostname)
            continue

        for ref, username in sorted(esperado.items()):
            if ref in real:
                ui.ok(f"  {username:20} {ref}")
                total_ok += 1
            else:
                ui.fail(f"  {username:20} {ref} — declared but not present on server")
                total_div += 1
        for ref, username in sorted(real.items()):
            if ref not in esperado:
                ui.warn(f"  {username:20} {ref} — block on server but not in state")
                total_div += 1

    ui.echo()
    ui.heading("Summary")
    ui.kv("matches", str(total_ok))
    ui.kv("divergences", str(total_div))
    if erros_ssh:
        ui.kv("ssh errors", ", ".join(erros_ssh))
    return 0 if total_div == 0 and not erros_ssh else 2


def cmd_apply(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args, com_ssh=not args.dry_run)
    subacoes = nucleo.preview()
    if not subacoes:
        ui.ok("nothing to do — state in sync")
        return 0

    ui.info(f"{len(subacoes)} sub-actions across {len({s.servidor for s in subacoes})} servers")
    for hostname in sorted({s.servidor for s in subacoes}):
        ui.secho(f"  {hostname}", bold=True)
        for s in subacoes:
            if s.servidor != hostname:
                continue
            sinal = "+" if s.acao == TipoAcao.ADICIONAR_CHAVE else "-"
            ui.echo(f"    {sinal} {s.acao.value:18} {s.credencial}")

    if args.diff:
        _imprimir_diff(nucleo, subacoes)

    if not args.yes and not ui.confirmar("Apply now?"):
        ui.warn("apply cancelled")
        return 1

    op = nucleo.aplicar()
    sucessos = sum(1 for s in op.subacoes if s.status == "sucesso")
    falhas = sum(1 for s in op.subacoes if s.status == "falha")
    ui.heading("Result")
    for s in op.subacoes:
        if s.status == "sucesso":
            ui.ok(f"{s.servidor:24} {s.acao.value:18} {s.credencial or ''}")
        else:
            ui.fail(f"{s.servidor:24} {s.acao.value:18} {s.credencial or ''} — {s.erro}")
    ui.echo()
    ui.kv("operation", op.id)
    ui.kv("status", op.status.value.upper())
    ui.kv("successes", str(sucessos))
    ui.kv("failures", str(falhas))
    if falhas:
        ui.echo()
        ui.info("re-running 'adminforge apply' retries only the failed sub-actions")
        return 1 if sucessos else 2
    return 0


# ---------------------------------------------------------------------------
# UC-9: history
# ---------------------------------------------------------------------------
def cmd_history_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    ops = nucleo.auditor.listar(args.limit)
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
    ui.tabela(["ID", "WHEN", "SUPERADMIN", "COMMAND", "STATUS"], linhas)
    return 0


def cmd_history_show(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    op = nucleo.auditor.buscar(args.op_id)
    if not op:
        ui.fail(f"operation '{args.op_id}' does not exist")
        return 2
    ui.heading("Operation")
    ui.kv("id", op.id)
    ui.kv("when", op.momento.isoformat())
    ui.kv("superadmin", op.superadmin)
    ui.kv("command", op.comando)
    ui.kv("status", op.status.value)
    ui.kv("hash", op.hash or "-")
    ui.kv("prev_hash", op.hash_anterior or "-")
    ui.heading(f"Sub-actions ({len(op.subacoes)})")
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
    ui.tabela(["ID", "WHEN", "SUPERADMIN", "COMMAND", "STATUS"], linhas)
    return 0


def cmd_history_verify(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    try:
        _, ultimo = nucleo.auditor.verificar_cadeia()
    except Exception as e:
        ui.fail(f"chain broken: {e}")
        return 2
    ui.ok(f"chain intact (last hash: {ultimo or '-'})")
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


def cmd_dump(args: argparse.Namespace) -> int:
    estado = _coletar_estado(_nucleo(args))
    if args.format == "json":
        print(json.dumps(estado, indent=2, ensure_ascii=False))
        return 0

    ui.heading(f"Users ({len(estado['users'])})")
    ui.tabela(
        ["USERNAME", "NOME", "EMAIL", "STATUS", "CHAVES"],
        [
            [u["username"], u["name"], u["email"], u["status"], str(len(u["credentials"]))]
            for u in estado["users"]
        ],
    )

    ui.heading(f"User groups ({len(estado['user_groups'])})")
    ui.tabela(
        ["NOME", "MEMBROS"],
        [[g["name"], ", ".join(g["members"]) or "-"] for g in estado["user_groups"]],
    )

    ui.heading(f"Servers ({len(estado['servers'])})")
    ui.tabela(
        ["HOSTNAME", "IPV4", "PORTA", "CHAVES_INSTALADAS"],
        [
            [s["hostname"], s["ipv4"], str(s["port"]), str(len(s["installed_keys"]))]
            for s in estado["servers"]
        ],
    )

    ui.heading(f"Server groups ({len(estado['server_groups'])})")
    ui.tabela(
        ["NOME", "MEMBROS"],
        [[g["name"], ", ".join(g["members"]) or "-"] for g in estado["server_groups"]],
    )

    ui.heading(f"Permissions ({len(estado['permissions'])})")
    ui.tabela(
        ["USER_GROUP", "SERVER_GROUP", "LEVEL", "PROFILE"],
        [
            [p["user_group"], p["server_group"], p["level"], p.get("profile") or "—"]
            for p in estado["permissions"]
        ],
    )

    ui.heading(f"Sudo profiles ({len(estado['sudo_profiles'])})")
    ui.tabela(
        ["NAME", "#CMDS", "COMMANDS"],
        [[p["name"], str(len(p["commands"])), ", ".join(p["commands"])[:60]] for p in estado["sudo_profiles"]],
    )
    return 0


# ---------------------------------------------------------------------------
# UC-10: audit server
# ---------------------------------------------------------------------------
def cmd_audit_server(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args, com_ssh=not args.dry_run)
    op, relatorio = nucleo.auditar_servidor(args.hostname)
    if "erro" in relatorio:
        ui.fail(relatorio["erro"])
        return 2

    usuarios = relatorio.get("usuarios", [])
    grupos = relatorio.get("grupos", [])
    servicos = relatorio.get("servicos", [])
    arquivos_sudoers = relatorio.get("sudoers_arquivos", [])
    regras_sudo = relatorio.get("sudoers_regras", [])

    if args.humans:
        usuarios = [u for u in usuarios if u.get("categoria") == "humano"]

    # Users
    titulo = f"Users ({len(usuarios)})"
    if args.humans:
        titulo += " — humans only (UID >= 1000)"
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
        ui.secho("  (none)", dim=True)

    # Groups
    if args.group:
        alvo = [g for g in grupos if args.group in g["nome"]]
        ui.heading(f"Groups matching '{args.group}' ({len(alvo)})")
        for g in alvo:
            membros = ", ".join(g["membros"]) or "-"
            ui.echo(f"  {g['nome']} (gid={g['gid']}): {membros}")
    else:
        ui.heading(f"Groups ({len(grupos)})")
        com_membros = [g for g in grupos if g["membros"]]
        if com_membros:
            ui.tabela(
                ["NAME", "GID", "MEMBERS"],
                [[g["nome"], str(g["gid"]), ", ".join(g["membros"])[:60]] for g in com_membros],
            )
        else:
            ui.secho("  (no group with explicit members)", dim=True)

    # Sudoers
    ui.heading(f"Sudoers — files in /etc/sudoers.d/ ({len(arquivos_sudoers)})")
    if arquivos_sudoers:
        for a in arquivos_sudoers:
            origem = "adminforge" if a["adminforge"] else "manual"
            cor = ui._GREEN if a["adminforge"] else ui._YELLOW
            ui.secho(f"  [{origem:10}] {a['nome']}", cor)
    else:
        ui.secho("  (could not list — ssh has no sudo on the server?)", dim=True)

    if regras_sudo:
        ui.heading(f"Active sudo rules ({len(regras_sudo)})")
        for r in regras_sudo[:20]:
            ui.echo(f"  {r}")
        if len(regras_sudo) > 20:
            ui.secho(f"  ... +{len(regras_sudo) - 20} rules (use --format json for full output)", dim=True)

    # Services
    ui.heading(f"Running services ({len(servicos)})")
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
            alertas.append(f"user '{args.user}' exists but no matching service is running")
    sudoers_manuais = [a["nome"] for a in arquivos_sudoers if not a["adminforge"]]
    if sudoers_manuais:
        alertas.append(
            f"{len(sudoers_manuais)} file(s) in /etc/sudoers.d/ outside AdminForge: "
            + ", ".join(sudoers_manuais[:5])
            + (" ..." if len(sudoers_manuais) > 5 else "")
        )

    if alertas:
        ui.heading("Alerts")
        for a in alertas:
            ui.warn(a)

    ui.kv("operation", op.id)
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adminforge",
        description="AdminForge - privileged identity management for Linux server fleets.\n\n"
        "Operations change the desired state; 'apply' converges the real state to it "
        "via SSH. Every command is recorded in history.jsonl.",
        epilog=EPILOG_GERAL,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version=f"adminforge {__version__}")
    parser.add_argument(
        "--state",
        default=os.environ.get("ADMINFORGE_STATE", "./state"),
        help="State directory (default: ./state or $ADMINFORGE_STATE).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    # user
    p_user = sub.add_parser(
        "user",
        help="Register, lifecycle and SSH keys of users.",
        epilog=(
            "Exemplos:\n"
            "  adminforge user add --username marina --name 'Marina' --email marina@empresa.com\n"
            "  adminforge user key add --username marina --file ~/.ssh/marina.pub\n"
            "  adminforge user disable --username marina"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s_user = p_user.add_subparsers(dest="sub", required=True)
    a = s_user.add_parser("add", help="Register a new user.")
    a.add_argument("--username", required=True)
    a.add_argument("--name", required=True)
    a.add_argument("--email", required=True)
    a.set_defaults(func=cmd_user_add)
    a = s_user.add_parser("list", help="List users.")
    a.set_defaults(func=cmd_user_list)
    a = s_user.add_parser("show", help="Show user details.")
    a.add_argument("--username", required=True).completer = completers.usernames
    a.set_defaults(func=cmd_user_show)
    a = s_user.add_parser("disable", help="Disable user (revokes all keys).")
    a.add_argument("--username", required=True).completer = completers.usernames
    a.add_argument("--yes", action="store_true")
    a.set_defaults(func=cmd_user_disable)

    # user key (subcomando aninhado de user)
    p_uk = s_user.add_parser("key", help="Register and revoke user SSH keys.")
    s_uk = p_uk.add_subparsers(dest="key_sub", required=True)
    a = s_uk.add_parser("add", help="Register an SSH key.")
    a.add_argument("--username", required=True).completer = completers.usernames
    a.add_argument("--file", help="Path to a .pub file.")
    a.add_argument("--string", help="Paste the full key.")
    a.set_defaults(func=cmd_user_key_add)
    a = s_uk.add_parser("revoke", help="Revoke a key by fingerprint.")
    a.add_argument("--fingerprint", required=True).completer = completers.fingerprints
    a.set_defaults(func=cmd_user_key_revoke)
    a = s_uk.add_parser("list", help="List user keys.")
    a.add_argument("--username", required=True).completer = completers.usernames
    a.set_defaults(func=cmd_user_key_list)

    # user-group
    p_ug = sub.add_parser(
        "user-group",
        help="User groups.",
        epilog=(
            "Exemplos:\n"
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
    a.add_argument("--username", required=True, nargs="+", help="one or more usernames (separated by space or comma)").completer = completers.usernames
    a.set_defaults(func=cmd_ug_add_member)

    a = s_ug.add_parser("remove-member")
    a.add_argument("--group", required=True).completer = completers.user_groups
    a.add_argument("--username", required=True, nargs="+", help="one or more usernames (separated by space or comma)").completer = completers.usernames
    a.set_defaults(func=cmd_ug_remove_member)

    a = s_ug.add_parser("delete")
    a.add_argument("--name", required=True).completer = completers.user_groups
    a.set_defaults(func=cmd_ug_delete)

    a = s_ug.add_parser("list")
    a.set_defaults(func=cmd_ug_list)

    # server
    p_server = sub.add_parser(
        "server",
        help="Server registration.",
        epilog=(
            "Exemplos:\n"
            "  adminforge server add --hostname web-01 --ip 10.0.0.10 --auto\n"
            "  adminforge server show --hostname web-01\n"
            "\n"
            "Sobre --auto e fingerprint: ver docs/USAGE.md (UC-4)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s_server = p_server.add_subparsers(dest="sub", required=True)
    a = s_server.add_parser("add", help="Register a server (TOFU host_key).")
    a.add_argument("--hostname", required=True)
    a.add_argument("--ip", required=True, help="Server IPv4.")
    a.add_argument("--port", type=int, default=22)
    a.add_argument("--host-key", help="ssh-keyscan output, e.g. 'ssh-ed25519 AAAA...'")
    a.add_argument("--auto", action="store_true", help="Capture host_key via ssh-keyscan.")
    a.set_defaults(func=cmd_server_add)

    a = s_server.add_parser("list")
    a.set_defaults(func=cmd_server_list)

    a = s_server.add_parser("show")
    a.add_argument("--hostname", required=True).completer = completers.hostnames
    a.set_defaults(func=cmd_server_show)

    a = s_server.add_parser("remove")
    a.add_argument("--hostname", required=True).completer = completers.hostnames
    a.add_argument("--yes", action="store_true")
    a.set_defaults(func=cmd_server_remove)

    # server-group
    p_sg = sub.add_parser(
        "server-group",
        help="Server groups.",
        epilog=(
            "Exemplos:\n"
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
    a.add_argument("--hostname", required=True, nargs="+", help="one or more hostnames (separated by space or comma)").completer = completers.hostnames
    a.set_defaults(func=cmd_sg_add)

    a = s_sg.add_parser("remove-member")
    a.add_argument("--group", required=True).completer = completers.server_groups
    a.add_argument("--hostname", required=True, nargs="+", help="one or more hostnames (separated by space or comma)").completer = completers.hostnames
    a.set_defaults(func=cmd_sg_rm)

    a = s_sg.add_parser("delete")
    a.add_argument("--name", required=True).completer = completers.server_groups
    a.set_defaults(func=cmd_sg_delete)

    a = s_sg.add_parser("list")
    a.set_defaults(func=cmd_sg_list)

    # grant / revoke
    a = sub.add_parser("grant", help="Grant access from a user-group to a server-group.")
    a.add_argument("--user-group", dest="user_group", required=True).completer = completers.user_groups
    a.add_argument("--server-group", dest="server_group", required=True).completer = completers.server_groups
    a.add_argument("--level", choices=["shell", "sudo"], required=True)
    a.add_argument("--profile", help="Sudo profile name (only with --level sudo); without it, grants NOPASSWD:ALL.").completer = completers.sudo_profiles
    a.set_defaults(func=cmd_grant)

    a = sub.add_parser("revoke", help="Revoke access between two groups.")
    a.add_argument("--user-group", dest="user_group", required=True).completer = completers.user_groups
    a.add_argument("--server-group", dest="server_group", required=True).completer = completers.server_groups
    a.set_defaults(func=cmd_revoke)

    # permission (CRUD: list/update/delete; grant/revoke remain as shortcuts)
    p_perm = sub.add_parser(
        "permission",
        help="List, update or delete permissions.",
        epilog=(
            "Examples:\n"
            "  adminforge permission list\n"
            "  adminforge permission update --user-group sa --server-group prod --level sudo\n"
            "  adminforge permission delete --user-group sa --server-group prod"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s_perm = p_perm.add_subparsers(dest="sub", required=True)

    a = s_perm.add_parser("list", help="List all permissions.")
    a.set_defaults(func=cmd_permission_list)

    a = s_perm.add_parser("update", help="Create or update a permission (alias of grant).")
    a.add_argument("--user-group", dest="user_group", required=True).completer = completers.user_groups
    a.add_argument("--server-group", dest="server_group", required=True).completer = completers.server_groups
    a.add_argument("--level", choices=["shell", "sudo"], required=True)
    a.add_argument("--profile", help="Sudo profile name (only with --level sudo).").completer = completers.sudo_profiles
    a.set_defaults(func=cmd_permission_update)

    a = s_perm.add_parser("delete", help="Delete a permission (alias of revoke).")
    a.add_argument("--user-group", dest="user_group", required=True).completer = completers.user_groups
    a.add_argument("--server-group", dest="server_group", required=True).completer = completers.server_groups
    a.add_argument("--yes", action="store_true", help="Skip confirmation.")
    a.set_defaults(func=cmd_permission_delete)

    # sudo-profile
    p_sp = sub.add_parser(
        "sudo-profile",
        help="Manage named sudo profiles (allowed commands per role).",
        epilog=(
            "Examples:\n"
            "  adminforge sudo-profile create --name read-logs --command /bin/journalctl --command '/bin/cat /var/log/*'\n"
            "  adminforge sudo-profile list\n"
            "  adminforge grant --user-group monitoring --server-group prod --level sudo --profile read-logs"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s_sp = p_sp.add_subparsers(dest="sub", required=True)

    a = s_sp.add_parser("create", help="Create a sudo profile with one or more absolute commands.")
    a.add_argument("--name", required=True)
    a.add_argument("--command", required=True, action="append", help="Absolute path to allow (repeat).")
    a.set_defaults(func=cmd_sudo_profile_create)

    a = s_sp.add_parser("list", help="List sudo profiles.")
    a.set_defaults(func=cmd_sudo_profile_list)

    a = s_sp.add_parser("show", help="Show commands of a sudo profile.")
    a.add_argument("--name", required=True).completer = completers.sudo_profiles
    a.set_defaults(func=cmd_sudo_profile_show)

    a = s_sp.add_parser("delete", help="Delete a sudo profile (must be unused).")
    a.add_argument("--name", required=True).completer = completers.sudo_profiles
    a.set_defaults(func=cmd_sudo_profile_delete)

    # dump
    a = sub.add_parser("dump", help="List the full declared state (users, groups, servers, permissions).")
    a.add_argument("--format", choices=["table", "json"], default="table")
    a.set_defaults(func=cmd_dump)

    # preview
    a = sub.add_parser("preview", help="Show the delta without applying.")
    a.set_defaults(func=cmd_preview)

    # apply
    p_apply = sub.add_parser("apply", help="Apply the delta to servers via SSH.")
    p_apply.add_argument("--yes", action="store_true", help="Skip confirmation.")
    p_apply.add_argument("--dry-run", action="store_true", help="Use the fake Deployer.")
    p_apply.add_argument("--diff", action="store_true", help="Show authorized_keys before/after diff per user.")
    p_apply.set_defaults(func=cmd_apply)
    s_apply = p_apply.add_subparsers(dest="apply_sub", required=False)
    a = s_apply.add_parser("verify", help="Compare declared chaves_instaladas vs real authorized_keys.")
    a.add_argument("--dry-run", action="store_true")
    a.set_defaults(func=cmd_apply_verify)

    # history
    p_hist = sub.add_parser("history", help="Query operational history.")
    s_hist = p_hist.add_subparsers(dest="sub", required=True)

    a = s_hist.add_parser("list")
    a.add_argument("-n", "--limit", type=int, default=50)
    a.set_defaults(func=cmd_history_list)

    a = s_hist.add_parser("show")
    a.add_argument("--id", dest="op_id", required=True)
    a.set_defaults(func=cmd_history_show)

    a = s_hist.add_parser("failed")
    a.add_argument("-n", "--limit", type=int, default=50)
    a.set_defaults(func=cmd_history_failed)

    a = s_hist.add_parser("verify")
    a.set_defaults(func=cmd_history_verify)

    # audit
    p_audit = sub.add_parser("audit", help="Operational audit (read-only via SSH).")
    s_audit = p_audit.add_subparsers(dest="sub", required=True)
    a = s_audit.add_parser(
        "server",
        help="Inspect users, groups, sudoers and services of the server.",
    )
    a.add_argument("--hostname", required=True).completer = completers.hostnames
    a.add_argument("--user", help="Highlight occurrences of this user.")
    a.add_argument("--group", help="Filter groups by substring.")
    a.add_argument("--service", help="Highlight occurrences of this service.")
    a.add_argument("--humans", action="store_true", help="Show only human users (UID >= 1000).")
    a.add_argument("--dry-run", action="store_true")
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
