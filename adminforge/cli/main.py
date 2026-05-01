from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from adminforge import __version__, ssh_keys
from adminforge.cli import ui
from adminforge.core.nucleo import Nucleo
from adminforge.domain import (
    NivelPermissao,
    StatusAdmin,
    StatusCredencial,
    TipoAcao,
)
from adminforge.exceptions import LockOcupado

EPILOG_GERAL = """\
\b
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

\b
DOCUMENTACAO
  Modelagem detalhada: docs/modelagem-v1.pdf
  Cookbook por caso de uso: docs/USAGE.md
"""


def _state_dir(ctx: click.Context) -> Path:
    return Path(ctx.obj["state"])


def _superadmin() -> str:
    return os.environ.get("ADMINFORGE_SUPERADMIN") or os.environ.get("USER") or "desconhecido"


def _nucleo(ctx: click.Context, com_ssh: bool = False) -> Nucleo:
    deployer = None
    if com_ssh:
        from adminforge.deployer.ssh_deployer import SSHDeployer

        chave = os.environ.get("ADMINFORGE_SSH_KEY") or str(Path.home() / ".ssh" / "adminforge_id")
        usuario = os.environ.get("ADMINFORGE_SSH_USER", "adminforge")
        criar_conta = os.environ.get("ADMINFORGE_CREATE_UNIX_USER", "true").lower() != "false"
        deployer = SSHDeployer(
            chave_privada_path=Path(chave),
            usuario_servico=usuario,
            criar_conta_unix=criar_conta,
        )
    return Nucleo.montar(_state_dir(ctx), deployer=deployer, superadmin=_superadmin())


@click.group(
    epilog=EPILOG_GERAL,
    context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 110},
)
@click.option(
    "--state",
    type=click.Path(file_okay=False, path_type=str),
    default=lambda: os.environ.get("ADMINFORGE_STATE", "./state"),
    show_default="./state ou $ADMINFORGE_STATE",
    help="Diretorio de estado (YAMLs e history.jsonl).",
)
@click.version_option(__version__, "-V", "--version")
@click.pass_context
def cli(ctx: click.Context, state: str) -> None:
    """\b
    AdminForge - gestao de identidades privilegiadas em frotas Linux.

    Operacoes mudam o estado desejado; 'apply' faz o real convergir para o
    desejado via SSH. Cada comando vira uma entrada auditada em history.jsonl.
    """
    ctx.ensure_object(dict)
    ctx.obj["state"] = state


# ---------------------------------------------------------------------------
# UC-1: admin add / list / show / disable
# ---------------------------------------------------------------------------
@cli.group()
def admin() -> None:
    """Cadastro e ciclo de vida de administradores."""


@admin.command("add", short_help="Cadastra um novo administrador.")
@click.argument("username")
@click.option("--nome", required=True, help="Nome completo.")
@click.option("--email", required=True, help="E-mail corporativo.")
@click.pass_context
def admin_add(ctx: click.Context, username: str, nome: str, email: str) -> None:
    """\b
    Cadastra um administrador novo. Sem grupo e sem acesso ate ser adicionado
    a um grupo e haver permissao concedida.

    \b
    EXEMPLO
      adminforge admin add marina --nome "Marina Silva" --email marina@empresa.com
    """
    op = _nucleo(ctx).cadastrar_admin(username, nome, email)
    ui.exit_se_falha(op)


@admin.command("list", short_help="Lista admins cadastrados.")
@click.pass_context
def admin_list(ctx: click.Context) -> None:
    nucleo = _nucleo(ctx)
    linhas = [
        [a.username, a.nome, a.email, a.status.value] for a in nucleo.store.list_admins()
    ]
    ui.tabela(["USERNAME", "NOME", "EMAIL", "STATUS"], linhas)


@admin.command("show", short_help="Detalha um admin com suas chaves.")
@click.argument("username")
@click.pass_context
def admin_show(ctx: click.Context, username: str) -> None:
    nucleo = _nucleo(ctx)
    a = nucleo.store.get_admin(username)
    if not a:
        ui.fail(f"admin '{username}' nao existe")
        sys.exit(2)
    ui.heading("Admin")
    ui.kv("username", a.username)
    ui.kv("nome", a.nome)
    ui.kv("email", a.email)
    ui.kv("status", a.status.value)
    creds = nucleo.store.list_credenciais(username)
    ui.heading(f"Credenciais ({len(creds)})")
    ui.tabela(
        ["FINGERPRINT", "STATUS"],
        [[c.fingerprint, c.status.value] for c in creds],
    )
    grupos = [g.nome for g in nucleo.store.list_grupos_admin() if username in g.membros]
    ui.heading(f"Grupos ({len(grupos)})")
    if grupos:
        click.echo("  " + ", ".join(grupos))
    else:
        click.secho("  (nenhum)", dim=True)


@admin.command("disable", short_help="Desabilita admin e revoga chaves ativas.")
@click.argument("username")
@click.option("--yes", is_flag=True, help="Pula confirmacao.")
@click.pass_context
def admin_disable(ctx: click.Context, username: str, yes: bool) -> None:
    if not yes and not ui.confirmar(
        f"Desabilitar '{username}' e revogar suas chaves? (apply remove dos servidores)",
        default=False,
    ):
        ui.warn("operacao cancelada")
        sys.exit(1)
    op = _nucleo(ctx).desabilitar_admin(username)
    ui.exit_se_falha(op)


# ---------------------------------------------------------------------------
# UC-2: key add / revoke / list
# ---------------------------------------------------------------------------
@cli.group()
def key() -> None:
    """Cadastro e revogacao de chaves SSH."""


@key.command("add", short_help="Cadastra chave SSH para um admin.")
@click.argument("username")
@click.option(
    "--file",
    "arquivo",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Caminho de um .pub.",
)
@click.option("--string", "chave", help="Cola a chave inteira.")
@click.pass_context
def key_add(ctx: click.Context, username: str, arquivo: Path | None, chave: str | None) -> None:
    """\b
    Cadastra a chave publica SSH de um admin. Aceita ssh-ed25519, ssh-rsa
    e ecdsa-sha2-*. A chave so vai pros servidores no proximo apply.

    \b
    EXEMPLOS
      adminforge key add marina --file ~/.ssh/marina.pub
      adminforge key add marina --string "ssh-ed25519 AAAA... marina@laptop"
    """
    if arquivo and chave:
        ui.fail("use --file OU --string, nao ambos")
        sys.exit(2)
    if arquivo:
        chave = arquivo.read_text(encoding="utf-8")
    if not chave:
        ui.fail("forneca --file ou --string")
        sys.exit(2)
    op = _nucleo(ctx).cadastrar_chave(username, chave)
    ui.exit_se_falha(op)


@key.command("revoke", short_help="Revoga chave por fingerprint.")
@click.argument("fingerprint")
@click.pass_context
def key_revoke(ctx: click.Context, fingerprint: str) -> None:
    op = _nucleo(ctx).revogar_chave(fingerprint)
    ui.exit_se_falha(op)


@key.command("list", short_help="Lista chaves de um admin.")
@click.argument("username")
@click.pass_context
def key_list(ctx: click.Context, username: str) -> None:
    nucleo = _nucleo(ctx)
    creds = nucleo.store.list_credenciais(username)
    ui.tabela(
        ["FINGERPRINT", "STATUS"],
        [[c.fingerprint, c.status.value] for c in creds],
    )


# ---------------------------------------------------------------------------
# UC-3: group ...
# ---------------------------------------------------------------------------
@cli.group()
def group() -> None:
    """Grupos de admins."""


@group.command("create")
@click.argument("nome")
@click.pass_context
def group_create(ctx: click.Context, nome: str) -> None:
    op = _nucleo(ctx).criar_grupo_admin(nome)
    ui.exit_se_falha(op)


@group.command("add-member")
@click.argument("grupo")
@click.argument("username")
@click.pass_context
def group_add_member(ctx: click.Context, grupo: str, username: str) -> None:
    op = _nucleo(ctx).adicionar_membro_grupo_admin(grupo, username)
    ui.exit_se_falha(op)


@group.command("remove-member")
@click.argument("grupo")
@click.argument("username")
@click.pass_context
def group_remove_member(ctx: click.Context, grupo: str, username: str) -> None:
    op = _nucleo(ctx).remover_membro_grupo_admin(grupo, username)
    ui.exit_se_falha(op)


@group.command("delete")
@click.argument("nome")
@click.pass_context
def group_delete(ctx: click.Context, nome: str) -> None:
    op = _nucleo(ctx).excluir_grupo_admin(nome)
    ui.exit_se_falha(op)


@group.command("list")
@click.pass_context
def group_list(ctx: click.Context) -> None:
    nucleo = _nucleo(ctx)
    linhas = [[g.nome, ", ".join(g.membros) or "-"] for g in nucleo.store.list_grupos_admin()]
    ui.tabela(["NOME", "MEMBROS"], linhas)


# ---------------------------------------------------------------------------
# UC-4: server add / list / show / remove
# ---------------------------------------------------------------------------
@cli.group()
def server() -> None:
    """Cadastro de servidores."""


@server.command("add", short_help="Cadastra servidor (TOFU host_key).")
@click.argument("hostname")
@click.option("--ip", "ipv4", required=True, help="IPv4 do servidor.")
@click.option("--porta", default=22, show_default=True)
@click.option("--host-key", help="ssh-keyscan: 'ssh-ed25519 AAAA...'")
@click.option("--auto", is_flag=True, help="Captura host_key via SSH (TOFU).")
@click.pass_context
def server_add(
    ctx: click.Context,
    hostname: str,
    ipv4: str,
    porta: int,
    host_key: str | None,
    auto: bool,
) -> None:
    """\b
    Registra um servidor. A primeira conexao captura a host_key (TOFU);
    nas seguintes, divergencia rejeita conexao.

    \b
    EXEMPLOS
      adminforge server add web-01 --ip 10.0.0.10 \\
          --host-key "ssh-ed25519 AAAAC3..."
      adminforge server add db-03 --ip 10.0.0.30 --auto
    """
    if auto and not host_key:
        from adminforge.deployer.ssh_deployer import SSHDeployer

        deployer = SSHDeployer(chave_privada_path=Path("/dev/null"))
        try:
            host_key, fp = deployer.capturar_host_key(hostname, ipv4, porta)
        except Exception as e:
            ui.fail(f"falha ao capturar host_key: {e}")
            sys.exit(2)
        ui.info(f"host_key capturada: {fp}")
        if not ui.confirmar("Confirma o fingerprint?", default=False):
            ui.warn("cadastro abortado")
            sys.exit(1)

    if not host_key:
        ui.fail("forneca --host-key ou --auto")
        sys.exit(2)

    op = _nucleo(ctx).cadastrar_servidor(hostname, ipv4, porta, host_key)
    ui.exit_se_falha(op)


@server.command("list")
@click.pass_context
def server_list(ctx: click.Context) -> None:
    nucleo = _nucleo(ctx)
    linhas = [
        [s.hostname, s.ipv4, str(s.porta_ssh), str(len(s.chaves_instaladas))]
        for s in nucleo.store.list_servidores()
    ]
    ui.tabela(["HOSTNAME", "IPV4", "PORTA", "CHAVES"], linhas)


@server.command("show")
@click.argument("hostname")
@click.pass_context
def server_show(ctx: click.Context, hostname: str) -> None:
    nucleo = _nucleo(ctx)
    s = nucleo.store.get_servidor(hostname)
    if not s:
        ui.fail(f"servidor '{hostname}' nao existe")
        sys.exit(2)
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


@server.command("remove")
@click.argument("hostname")
@click.option("--yes", is_flag=True)
@click.pass_context
def server_remove(ctx: click.Context, hostname: str, yes: bool) -> None:
    if not yes and not ui.confirmar(
        f"Remover '{hostname}' do AdminForge? (nao limpa chaves no servidor)", default=False
    ):
        ui.warn("operacao cancelada")
        sys.exit(1)
    op = _nucleo(ctx).excluir_servidor(hostname)
    ui.exit_se_falha(op)


# ---------------------------------------------------------------------------
# UC-5: server-group ...
# ---------------------------------------------------------------------------
@cli.group("server-group")
def server_group() -> None:
    """Grupos de servidores."""


@server_group.command("create")
@click.argument("nome")
@click.pass_context
def sg_create(ctx: click.Context, nome: str) -> None:
    op = _nucleo(ctx).criar_grupo_servidor(nome)
    ui.exit_se_falha(op)


@server_group.command("add-member")
@click.argument("grupo")
@click.argument("hostname")
@click.pass_context
def sg_add(ctx: click.Context, grupo: str, hostname: str) -> None:
    op = _nucleo(ctx).adicionar_membro_grupo_servidor(grupo, hostname)
    ui.exit_se_falha(op)


@server_group.command("remove-member")
@click.argument("grupo")
@click.argument("hostname")
@click.pass_context
def sg_rm(ctx: click.Context, grupo: str, hostname: str) -> None:
    op = _nucleo(ctx).remover_membro_grupo_servidor(grupo, hostname)
    ui.exit_se_falha(op)


@server_group.command("delete")
@click.argument("nome")
@click.pass_context
def sg_delete(ctx: click.Context, nome: str) -> None:
    op = _nucleo(ctx).excluir_grupo_servidor(nome)
    ui.exit_se_falha(op)


@server_group.command("list")
@click.pass_context
def sg_list(ctx: click.Context) -> None:
    nucleo = _nucleo(ctx)
    linhas = [[g.nome, ", ".join(g.membros) or "-"] for g in nucleo.store.list_grupos_servidor()]
    ui.tabela(["NOME", "MEMBROS"], linhas)


# ---------------------------------------------------------------------------
# UC-6: grant / revoke
# ---------------------------------------------------------------------------
@cli.command(short_help="Concede acesso de grupo de admins a grupo de servidores.")
@click.argument("grupo_admin")
@click.argument("grupo_servidor")
@click.option(
    "--nivel",
    type=click.Choice(["shell", "sudo"], case_sensitive=False),
    required=True,
)
@click.pass_context
def grant(ctx: click.Context, grupo_admin: str, grupo_servidor: str, nivel: str) -> None:
    """\b
    EXEMPLO
      adminforge grant sysadmins producao --nivel sudo
    """
    op = _nucleo(ctx).conceder(grupo_admin, grupo_servidor, NivelPermissao(nivel.lower()))
    ui.exit_se_falha(op)


@cli.command(short_help="Revoga acesso entre dois grupos.")
@click.argument("grupo_admin")
@click.argument("grupo_servidor")
@click.pass_context
def revoke(ctx: click.Context, grupo_admin: str, grupo_servidor: str) -> None:
    op = _nucleo(ctx).revogar(grupo_admin, grupo_servidor)
    ui.exit_se_falha(op)


# ---------------------------------------------------------------------------
# UC-7: preview
# ---------------------------------------------------------------------------
@cli.command(short_help="Mostra o delta sem aplicar nada.")
@click.pass_context
def preview(ctx: click.Context) -> None:
    """\b
    Lista as subacoes que 'apply' executaria, agrupadas por servidor.
    Read-only: nao mexe em servidor algum nem registra mutacao no historico.

    \b
    EXEMPLO
      adminforge preview
    """
    nucleo = _nucleo(ctx)
    subacoes = nucleo.preview()
    if not subacoes:
        ui.ok("nada a fazer — estado sincronizado")
        return
    ui.info(f"{len(subacoes)} subacoes em {len({s.servidor for s in subacoes})} servidores")
    for hostname in sorted({s.servidor for s in subacoes}):
        ui.heading(hostname)
        for s in subacoes:
            if s.servidor != hostname:
                continue
            cor = "green" if s.acao == TipoAcao.ADICIONAR_CHAVE else "red"
            sinal = "+" if s.acao == TipoAcao.ADICIONAR_CHAVE else "-"
            click.secho(
                f"  {sinal} {s.acao.value:18} {s.credencial:50} {(s.nivel.value if s.nivel else '-')}",
                fg=cor,
            )


# ---------------------------------------------------------------------------
# UC-8: apply
# ---------------------------------------------------------------------------
@cli.command(short_help="Aplica o delta nos servidores via SSH.")
@click.option("--yes", is_flag=True, help="Pula a confirmacao.")
@click.option("--dry-run", is_flag=True, help="Usa Deployer fake (nao toca servidores).")
@click.pass_context
def apply(ctx: click.Context, yes: bool, dry_run: bool) -> None:
    """\b
    Calcula o delta, mostra as subacoes, pede confirmacao e executa via SSH.

    \b
    EXEMPLOS
      adminforge apply
      adminforge apply --yes
      adminforge apply --dry-run
    """
    nucleo = _nucleo(ctx, com_ssh=not dry_run)
    subacoes = nucleo.preview()
    if not subacoes:
        ui.ok("nada a fazer — estado sincronizado")
        return

    ui.info(f"{len(subacoes)} subacoes em {len({s.servidor for s in subacoes})} servidores")
    for hostname in sorted({s.servidor for s in subacoes}):
        click.secho(f"  {hostname}", bold=True)
        for s in subacoes:
            if s.servidor != hostname:
                continue
            sinal = "+" if s.acao == TipoAcao.ADICIONAR_CHAVE else "-"
            click.echo(f"    {sinal} {s.acao.value:18} {s.credencial}")

    if not yes and not ui.confirmar("Aplicar agora?", default=False):
        ui.warn("apply cancelado")
        sys.exit(1)

    op = nucleo.aplicar()
    sucessos = sum(1 for s in op.subacoes if s.status == "sucesso")
    falhas = sum(1 for s in op.subacoes if s.status == "falha")
    ui.heading("Resultado")
    for s in op.subacoes:
        if s.status == "sucesso":
            ui.ok(f"{s.servidor:24} {s.acao.value:18} {s.credencial or ''}")
        else:
            ui.fail(f"{s.servidor:24} {s.acao.value:18} {s.credencial or ''} — {s.erro}")
    click.echo()
    ui.kv("operacao", op.id)
    ui.kv("status", op.status.value.upper())
    ui.kv("sucessos", str(sucessos))
    ui.kv("falhas", str(falhas))
    if falhas:
        click.echo()
        ui.info(f"reaplicar com 'adminforge apply' retentativa apenas as subacoes em falha")
        sys.exit(1 if sucessos else 2)


# ---------------------------------------------------------------------------
# UC-9: history list / show / failed / verify
# ---------------------------------------------------------------------------
@cli.group()
def history() -> None:
    """Consulta de historico operacional."""


@history.command("list")
@click.option("-n", "--limite", default=50, show_default=True)
@click.pass_context
def history_list(ctx: click.Context, limite: int) -> None:
    nucleo = _nucleo(ctx)
    ops = nucleo.auditor.listar(limite)
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


@history.command("show")
@click.argument("op_id")
@click.pass_context
def history_show(ctx: click.Context, op_id: str) -> None:
    nucleo = _nucleo(ctx)
    op = nucleo.auditor.buscar(op_id)
    if not op:
        ui.fail(f"operacao '{op_id}' nao existe")
        sys.exit(2)
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


@history.command("failed")
@click.option("-n", "--limite", default=50, show_default=True)
@click.pass_context
def history_failed(ctx: click.Context, limite: int) -> None:
    nucleo = _nucleo(ctx)
    ops = nucleo.auditor.listar_falhas(limite)
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


@history.command("verify")
@click.pass_context
def history_verify(ctx: click.Context) -> None:
    nucleo = _nucleo(ctx)
    try:
        ok, ultimo = nucleo.auditor.verificar_cadeia()
    except Exception as e:
        ui.fail(f"cadeia quebrada: {e}")
        sys.exit(2)
    ui.ok(f"cadeia integra (ultimo hash: {ultimo or '-'})")


# ---------------------------------------------------------------------------
# UC-10: audit server
# ---------------------------------------------------------------------------
@cli.group()
def audit() -> None:
    """Auditoria operacional (read-only via SSH)."""


@audit.command("server", short_help="Inspeciona usuarios e servicos do servidor.")
@click.argument("hostname")
@click.option("--user", help="Destaca ocorrencias do usuario.")
@click.option("--service", help="Destaca ocorrencias do servico.")
@click.option("--dry-run", is_flag=True, help="Usa Deployer fake.")
@click.pass_context
def audit_server(
    ctx: click.Context,
    hostname: str,
    user: str | None,
    service: str | None,
    dry_run: bool,
) -> None:
    """\b
    Conecta via SSH (read-only) e lista usuarios locais e servicos em execucao.

    \b
    EXEMPLOS
      adminforge audit server web-01
      adminforge audit server web-01 --user tomcat
      adminforge audit server web-01 --service nginx
    """
    nucleo = _nucleo(ctx, com_ssh=not dry_run)
    op, relatorio = nucleo.auditar_servidor(hostname)
    if "erro" in relatorio:
        ui.fail(relatorio["erro"])
        sys.exit(2)
    usuarios = relatorio.get("usuarios", [])
    servicos = relatorio.get("servicos", [])
    ui.heading(f"Usuarios ({len(usuarios)})")
    for u in usuarios:
        if user and user in u:
            click.secho(f"  * {u}", fg="yellow", bold=True)
        else:
            click.echo(f"    {u}")
    ui.heading(f"Servicos ({len(servicos)})")
    for s in servicos:
        if service and service in s:
            click.secho(f"  * {s}", fg="yellow", bold=True)
        else:
            click.echo(f"    {s}")
    if user:
        encontrou_user = any(user in u for u in usuarios)
        encontrou_serv = any(user in s for s in servicos)
        if encontrou_user and not encontrou_serv:
            ui.warn(
                f"usuario '{user}' presente sem servico correspondente — possivel sobra"
            )
    ui.kv("operacao", op.id)


# ---------------------------------------------------------------------------
def main() -> None:
    try:
        cli(standalone_mode=True)
    except LockOcupado as e:
        ui.fail(str(e))
        sys.exit(3)


if __name__ == "__main__":
    main()
