from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from adminforge import __version__, ssh_keys
from adminforge.cli import ui
from adminforge.core.nucleo import Nucleo
from adminforge.domain import (
    NivelPermissao,
    StatusOperacao,
    TipoAcao,
)
from adminforge.exceptions import LockOcupado


EPILOG_GERAL = """\
EXEMPLOS
  adminforge admin add marina --nome "Marina Silva" --email marina@empresa.com
  adminforge key add marina --file ~/.ssh/marina.pub
  adminforge group create sysadmins
  adminforge group add-member sysadmins marina
  adminforge server add web-01 --ip 10.0.0.10
  adminforge server-group create producao
  adminforge server-group add-member producao web-01
  adminforge grant sysadmins producao --nivel sudo
  adminforge preview
  adminforge apply

DOCUMENTACAO
  Modelagem detalhada: docs/modelagem-v1.pdf
  Cookbook por caso de uso: docs/USAGE.md
"""


def _state_dir(args: argparse.Namespace) -> Path:
    return Path(args.state)


def _superadmin() -> str:
    return os.environ.get("ADMINFORGE_SUPERADMIN") or os.environ.get("USER") or "desconhecido"


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
# UC-1: admin
# ---------------------------------------------------------------------------
def cmd_admin_add(args: argparse.Namespace) -> int:
    op = _nucleo(args).cadastrar_admin(args.username, args.nome, args.email)
    return ui.imprimir_resultado(op)


def cmd_admin_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    linhas = [[a.username, a.nome, a.email, a.status.value] for a in nucleo.store.list_admins()]
    ui.tabela(["USERNAME", "NOME", "EMAIL", "STATUS"], linhas)
    return 0


def cmd_admin_show(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    a = nucleo.store.get_admin(args.username)
    if not a:
        ui.fail(f"admin '{args.username}' nao existe")
        return 2
    ui.heading("Admin")
    ui.kv("username", a.username)
    ui.kv("nome", a.nome)
    ui.kv("email", a.email)
    ui.kv("status", a.status.value)
    creds = nucleo.store.list_credenciais(args.username)
    ui.heading(f"Credenciais ({len(creds)})")
    ui.tabela(["FINGERPRINT", "STATUS"], [[c.fingerprint, c.status.value] for c in creds])
    grupos = [g.nome for g in nucleo.store.list_grupos_admin() if args.username in g.membros]
    ui.heading(f"Grupos ({len(grupos)})")
    if grupos:
        ui.echo("  " + ", ".join(grupos))
    else:
        ui.secho("  (nenhum)", dim=True)
    return 0


def cmd_admin_disable(args: argparse.Namespace) -> int:
    if not args.yes and not ui.confirmar(
        f"Desabilitar '{args.username}' e revogar suas chaves? (apply remove dos servidores)"
    ):
        ui.warn("operacao cancelada")
        return 1
    op = _nucleo(args).desabilitar_admin(args.username)
    return ui.imprimir_resultado(op)


# ---------------------------------------------------------------------------
# UC-2: key
# ---------------------------------------------------------------------------
def cmd_key_add(args: argparse.Namespace) -> int:
    if args.file and args.string:
        ui.fail("use --file OU --string, nao ambos")
        return 2
    chave = args.string
    if args.file:
        chave = Path(args.file).read_text(encoding="utf-8")
    if not chave:
        ui.fail("forneca --file ou --string")
        return 2
    op = _nucleo(args).cadastrar_chave(args.username, chave)
    return ui.imprimir_resultado(op)


def cmd_key_revoke(args: argparse.Namespace) -> int:
    op = _nucleo(args).revogar_chave(args.fingerprint)
    return ui.imprimir_resultado(op)


def cmd_key_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    creds = nucleo.store.list_credenciais(args.username)
    ui.tabela(["FINGERPRINT", "STATUS"], [[c.fingerprint, c.status.value] for c in creds])
    return 0


# ---------------------------------------------------------------------------
# UC-3: group
# ---------------------------------------------------------------------------
def cmd_group_create(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).criar_grupo_admin(args.nome))


def cmd_group_add_member(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).adicionar_membro_grupo_admin(args.grupo, args.username))


def cmd_group_remove_member(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).remover_membro_grupo_admin(args.grupo, args.username))


def cmd_group_delete(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).excluir_grupo_admin(args.nome))


def cmd_group_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    linhas = [[g.nome, ", ".join(g.membros) or "-"] for g in nucleo.store.list_grupos_admin()]
    ui.tabela(["NOME", "MEMBROS"], linhas)
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
            host_key, fp = deployer.capturar_host_key(args.hostname, args.ip, args.porta)
        except Exception as e:
            ui.fail(f"falha ao capturar host_key: {e}")
            return 2
        ui.info(f"host_key capturada: {fp}")
        if not ui.confirmar("Confirma o fingerprint?"):
            ui.warn("cadastro abortado")
            return 1
    if not host_key:
        ui.fail("forneca --host-key ou --auto")
        return 2
    op = _nucleo(args).cadastrar_servidor(args.hostname, args.ip, args.porta, host_key)
    return ui.imprimir_resultado(op)


def cmd_server_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    linhas = [
        [s.hostname, s.ipv4, str(s.porta_ssh), str(len(s.chaves_instaladas))]
        for s in nucleo.store.list_servidores()
    ]
    ui.tabela(["HOSTNAME", "IPV4", "PORTA", "CHAVES"], linhas)
    return 0


def cmd_server_show(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    s = nucleo.store.get_servidor(args.hostname)
    if not s:
        ui.fail(f"servidor '{args.hostname}' nao existe")
        return 2
    ui.heading("Servidor")
    ui.kv("hostname", s.hostname)
    ui.kv("ipv4", s.ipv4)
    ui.kv("porta", str(s.porta_ssh))
    ui.kv("host_key", s.chave_host[:80] + ("..." if len(s.chave_host) > 80 else ""))
    ui.heading(f"Chaves instaladas ({len(s.chaves_instaladas)})")
    linhas = []
    for item in s.chaves_instaladas:
        if isinstance(item, dict):
            linhas.append([item.get("ref", "?"), item.get("nivel", "?")])
        else:
            linhas.append([str(item), "shell"])
    ui.tabela(["REF", "NIVEL"], linhas)
    return 0


def cmd_server_remove(args: argparse.Namespace) -> int:
    if not args.yes and not ui.confirmar(
        f"Remover '{args.hostname}' do AdminForge? (nao limpa chaves no servidor)"
    ):
        ui.warn("operacao cancelada")
        return 1
    return ui.imprimir_resultado(_nucleo(args).excluir_servidor(args.hostname))


# ---------------------------------------------------------------------------
# UC-5: server-group
# ---------------------------------------------------------------------------
def cmd_sg_create(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).criar_grupo_servidor(args.nome))


def cmd_sg_add(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).adicionar_membro_grupo_servidor(args.grupo, args.hostname))


def cmd_sg_rm(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).remover_membro_grupo_servidor(args.grupo, args.hostname))


def cmd_sg_delete(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).excluir_grupo_servidor(args.nome))


def cmd_sg_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    linhas = [[g.nome, ", ".join(g.membros) or "-"] for g in nucleo.store.list_grupos_servidor()]
    ui.tabela(["NOME", "MEMBROS"], linhas)
    return 0


# ---------------------------------------------------------------------------
# UC-6: grant / revoke
# ---------------------------------------------------------------------------
def cmd_grant(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(
        _nucleo(args).conceder(args.grupo_admin, args.grupo_servidor, NivelPermissao(args.nivel))
    )


def cmd_revoke(args: argparse.Namespace) -> int:
    return ui.imprimir_resultado(_nucleo(args).revogar(args.grupo_admin, args.grupo_servidor))


# ---------------------------------------------------------------------------
# UC-7 / UC-8: preview / apply
# ---------------------------------------------------------------------------
def cmd_preview(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    subacoes = nucleo.preview()
    if not subacoes:
        ui.ok("nada a fazer — estado sincronizado")
        return 0
    ui.info(f"{len(subacoes)} subacoes em {len({s.servidor for s in subacoes})} servidores")
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


def cmd_apply(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args, com_ssh=not args.dry_run)
    subacoes = nucleo.preview()
    if not subacoes:
        ui.ok("nada a fazer — estado sincronizado")
        return 0

    ui.info(f"{len(subacoes)} subacoes em {len({s.servidor for s in subacoes})} servidores")
    for hostname in sorted({s.servidor for s in subacoes}):
        ui.secho(f"  {hostname}", bold=True)
        for s in subacoes:
            if s.servidor != hostname:
                continue
            sinal = "+" if s.acao == TipoAcao.ADICIONAR_CHAVE else "-"
            ui.echo(f"    {sinal} {s.acao.value:18} {s.credencial}")

    if not args.yes and not ui.confirmar("Aplicar agora?"):
        ui.warn("apply cancelado")
        return 1

    op = nucleo.aplicar()
    sucessos = sum(1 for s in op.subacoes if s.status == "sucesso")
    falhas = sum(1 for s in op.subacoes if s.status == "falha")
    ui.heading("Resultado")
    for s in op.subacoes:
        if s.status == "sucesso":
            ui.ok(f"{s.servidor:24} {s.acao.value:18} {s.credencial or ''}")
        else:
            ui.fail(f"{s.servidor:24} {s.acao.value:18} {s.credencial or ''} — {s.erro}")
    ui.echo()
    ui.kv("operacao", op.id)
    ui.kv("status", op.status.value.upper())
    ui.kv("sucessos", str(sucessos))
    ui.kv("falhas", str(falhas))
    if falhas:
        ui.echo()
        ui.info("reaplicar com 'adminforge apply' retentativa apenas as subacoes em falha")
        return 1 if sucessos else 2
    return 0


# ---------------------------------------------------------------------------
# UC-9: history
# ---------------------------------------------------------------------------
def cmd_history_list(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    ops = nucleo.auditor.listar(args.limite)
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
    ui.tabela(["ID", "MOMENTO", "SUPERADMIN", "COMANDO", "STATUS"], linhas)
    return 0


def cmd_history_show(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    op = nucleo.auditor.buscar(args.op_id)
    if not op:
        ui.fail(f"operacao '{args.op_id}' nao existe")
        return 2
    ui.heading("Operacao")
    ui.kv("id", op.id)
    ui.kv("momento", op.momento.isoformat())
    ui.kv("superadmin", op.superadmin)
    ui.kv("comando", op.comando)
    ui.kv("status", op.status.value)
    ui.kv("hash", op.hash or "-")
    ui.kv("hash_anterior", op.hash_anterior or "-")
    ui.heading(f"Subacoes ({len(op.subacoes)})")
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
    ui.tabela(["SERVIDOR", "ACAO", "ALVO", "STATUS", "DETALHE"], linhas)
    return 0


def cmd_history_failed(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    ops = nucleo.auditor.listar_falhas(args.limite)
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
    ui.tabela(["ID", "MOMENTO", "SUPERADMIN", "COMANDO", "STATUS"], linhas)
    return 0


def cmd_history_verify(args: argparse.Namespace) -> int:
    nucleo = _nucleo(args)
    try:
        _, ultimo = nucleo.auditor.verificar_cadeia()
    except Exception as e:
        ui.fail(f"cadeia quebrada: {e}")
        return 2
    ui.ok(f"cadeia integra (ultimo hash: {ultimo or '-'})")
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
    servicos = relatorio.get("servicos", [])
    ui.heading(f"Usuarios ({len(usuarios)})")
    for u in usuarios:
        if args.user and args.user in u:
            ui.secho(f"  * {u}", ui._YELLOW, bold=True)
        else:
            ui.echo(f"    {u}")
    ui.heading(f"Servicos ({len(servicos)})")
    for s in servicos:
        if args.service and args.service in s:
            ui.secho(f"  * {s}", ui._YELLOW, bold=True)
        else:
            ui.echo(f"    {s}")
    if args.user:
        encontrou_user = any(args.user in u for u in usuarios)
        encontrou_serv = any(args.user in s for s in servicos)
        if encontrou_user and not encontrou_serv:
            ui.warn(f"usuario '{args.user}' presente sem servico correspondente — possivel sobra")
    ui.kv("operacao", op.id)
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adminforge",
        description="AdminForge - gestao de identidades privilegiadas em frotas Linux.\n\n"
        "Operacoes mudam o estado desejado; 'apply' faz o real convergir para o "
        "desejado via SSH. Cada comando vira uma entrada auditada em history.jsonl.",
        epilog=EPILOG_GERAL,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version=f"adminforge {__version__}")
    parser.add_argument(
        "--state",
        default=os.environ.get("ADMINFORGE_STATE", "./state"),
        help="Diretorio de estado (default: ./state ou $ADMINFORGE_STATE).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="COMANDO")

    # admin
    p_admin = sub.add_parser("admin", help="Cadastro e ciclo de vida de administradores.")
    s_admin = p_admin.add_subparsers(dest="sub", required=True)
    a = s_admin.add_parser("add", help="Cadastra um novo administrador.")
    a.add_argument("username")
    a.add_argument("--nome", required=True)
    a.add_argument("--email", required=True)
    a.set_defaults(func=cmd_admin_add)
    a = s_admin.add_parser("list", help="Lista admins.")
    a.set_defaults(func=cmd_admin_list)
    a = s_admin.add_parser("show", help="Detalha admin.")
    a.add_argument("username")
    a.set_defaults(func=cmd_admin_show)
    a = s_admin.add_parser("disable", help="Desabilita admin.")
    a.add_argument("username")
    a.add_argument("--yes", action="store_true")
    a.set_defaults(func=cmd_admin_disable)

    # key
    p_key = sub.add_parser("key", help="Cadastro e revogacao de chaves SSH.")
    s_key = p_key.add_subparsers(dest="sub", required=True)
    a = s_key.add_parser("add", help="Cadastra chave SSH.")
    a.add_argument("username")
    a.add_argument("--file", help="Caminho de um .pub.")
    a.add_argument("--string", help="Cola a chave inteira.")
    a.set_defaults(func=cmd_key_add)
    a = s_key.add_parser("revoke", help="Revoga chave por fingerprint.")
    a.add_argument("fingerprint")
    a.set_defaults(func=cmd_key_revoke)
    a = s_key.add_parser("list", help="Lista chaves do admin.")
    a.add_argument("username")
    a.set_defaults(func=cmd_key_list)

    # group
    p_group = sub.add_parser("group", help="Grupos de admins.")
    s_group = p_group.add_subparsers(dest="sub", required=True)
    a = s_group.add_parser("create"); a.add_argument("nome"); a.set_defaults(func=cmd_group_create)
    a = s_group.add_parser("add-member"); a.add_argument("grupo"); a.add_argument("username")
    a.set_defaults(func=cmd_group_add_member)
    a = s_group.add_parser("remove-member"); a.add_argument("grupo"); a.add_argument("username")
    a.set_defaults(func=cmd_group_remove_member)
    a = s_group.add_parser("delete"); a.add_argument("nome"); a.set_defaults(func=cmd_group_delete)
    a = s_group.add_parser("list"); a.set_defaults(func=cmd_group_list)

    # server
    p_server = sub.add_parser("server", help="Cadastro de servidores.")
    s_server = p_server.add_subparsers(dest="sub", required=True)
    a = s_server.add_parser("add", help="Cadastra servidor (TOFU host_key).")
    a.add_argument("hostname")
    a.add_argument("--ip", required=True, help="IPv4 do servidor.")
    a.add_argument("--porta", type=int, default=22)
    a.add_argument("--host-key", help="ssh-keyscan: 'ssh-ed25519 AAAA...'")
    a.add_argument("--auto", action="store_true", help="Captura host_key via ssh-keyscan.")
    a.set_defaults(func=cmd_server_add)
    a = s_server.add_parser("list"); a.set_defaults(func=cmd_server_list)
    a = s_server.add_parser("show"); a.add_argument("hostname"); a.set_defaults(func=cmd_server_show)
    a = s_server.add_parser("remove")
    a.add_argument("hostname"); a.add_argument("--yes", action="store_true")
    a.set_defaults(func=cmd_server_remove)

    # server-group
    p_sg = sub.add_parser("server-group", help="Grupos de servidores.")
    s_sg = p_sg.add_subparsers(dest="sub", required=True)
    a = s_sg.add_parser("create"); a.add_argument("nome"); a.set_defaults(func=cmd_sg_create)
    a = s_sg.add_parser("add-member"); a.add_argument("grupo"); a.add_argument("hostname")
    a.set_defaults(func=cmd_sg_add)
    a = s_sg.add_parser("remove-member"); a.add_argument("grupo"); a.add_argument("hostname")
    a.set_defaults(func=cmd_sg_rm)
    a = s_sg.add_parser("delete"); a.add_argument("nome"); a.set_defaults(func=cmd_sg_delete)
    a = s_sg.add_parser("list"); a.set_defaults(func=cmd_sg_list)

    # grant / revoke
    a = sub.add_parser("grant", help="Concede acesso de grupo de admins a grupo de servidores.")
    a.add_argument("grupo_admin"); a.add_argument("grupo_servidor")
    a.add_argument("--nivel", choices=["shell", "sudo"], required=True)
    a.set_defaults(func=cmd_grant)
    a = sub.add_parser("revoke", help="Revoga acesso entre dois grupos.")
    a.add_argument("grupo_admin"); a.add_argument("grupo_servidor")
    a.set_defaults(func=cmd_revoke)

    # preview
    a = sub.add_parser("preview", help="Mostra o delta sem aplicar.")
    a.set_defaults(func=cmd_preview)

    # apply
    a = sub.add_parser("apply", help="Aplica o delta nos servidores via SSH.")
    a.add_argument("--yes", action="store_true", help="Pula confirmacao.")
    a.add_argument("--dry-run", action="store_true", help="Usa Deployer fake.")
    a.set_defaults(func=cmd_apply)

    # history
    p_hist = sub.add_parser("history", help="Consulta de historico operacional.")
    s_hist = p_hist.add_subparsers(dest="sub", required=True)
    a = s_hist.add_parser("list"); a.add_argument("-n", "--limite", type=int, default=50)
    a.set_defaults(func=cmd_history_list)
    a = s_hist.add_parser("show"); a.add_argument("op_id")
    a.set_defaults(func=cmd_history_show)
    a = s_hist.add_parser("failed"); a.add_argument("-n", "--limite", type=int, default=50)
    a.set_defaults(func=cmd_history_failed)
    a = s_hist.add_parser("verify"); a.set_defaults(func=cmd_history_verify)

    # audit
    p_audit = sub.add_parser("audit", help="Auditoria operacional (read-only via SSH).")
    s_audit = p_audit.add_subparsers(dest="sub", required=True)
    a = s_audit.add_parser("server", help="Inspeciona usuarios e servicos do servidor.")
    a.add_argument("hostname")
    a.add_argument("--user", help="Destaca ocorrencias do usuario.")
    a.add_argument("--service", help="Destaca ocorrencias do servico.")
    a.add_argument("--dry-run", action="store_true")
    a.set_defaults(func=cmd_audit_server)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except LockOcupado as e:
        ui.fail(str(e))
        return 3


if __name__ == "__main__":
    sys.exit(main())
