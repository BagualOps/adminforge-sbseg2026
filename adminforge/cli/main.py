import click

from adminforge import __version__


@click.group()
@click.version_option(__version__)
def cli() -> None:
    """AdminForge — gestão de identidades privilegiadas em frotas Linux."""


@cli.group()
def admin() -> None:
    """Cadastro de administradores (UC-1)."""


@admin.command("add")
@click.argument("username")
@click.option("--nome", required=True)
@click.option("--email", required=True)
def admin_add(username: str, nome: str, email: str) -> None:
    raise NotImplementedError("UC-1: pendente no M-1")


@cli.group()
def key() -> None:
    """Cadastro e revogação de chaves SSH (UC-2)."""


@key.command("add")
@click.argument("username")
@click.option("--file", "arquivo", type=click.Path(exists=True))
@click.option("--string", "chave")
def key_add(username: str, arquivo: str | None, chave: str | None) -> None:
    raise NotImplementedError("UC-2: pendente no M-1")


@cli.group()
def group() -> None:
    """Grupos de admins (UC-3)."""


@cli.group()
def server() -> None:
    """Cadastro de servidores (UC-4)."""


@cli.group("server-group")
def server_group() -> None:
    """Grupos de servidores (UC-5)."""


@cli.command()
@click.argument("grupo_admin")
@click.argument("grupo_servidor")
@click.option("--nivel", type=click.Choice(["shell", "sudo"]), required=True)
def grant(grupo_admin: str, grupo_servidor: str, nivel: str) -> None:
    """Conceder acesso (UC-6)."""
    raise NotImplementedError("UC-6: pendente no M-1")


@cli.command()
@click.argument("grupo_admin")
@click.argument("grupo_servidor")
def revoke(grupo_admin: str, grupo_servidor: str) -> None:
    """Revogar acesso (UC-6)."""
    raise NotImplementedError("UC-6: pendente no M-1")


@cli.command()
def preview() -> None:
    """Mostrar o que vai mudar em cada servidor (UC-7)."""
    raise NotImplementedError("UC-7: pendente no M-1")


@cli.command()
@click.option("--yes", is_flag=True, help="Pula confirmação.")
def apply(yes: bool) -> None:
    """Aplicar mudanças nos servidores (UC-8)."""
    raise NotImplementedError("UC-8: pendente no M-1")


@cli.group()
def history() -> None:
    """Consulta de histórico (UC-9)."""


@cli.group()
def audit() -> None:
    """Auditoria operacional de servidores (UC-10)."""


if __name__ == "__main__":
    cli()
