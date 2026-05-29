"""CLI entry point — `cms migrate`, `cms validate`"""

import click


@click.group()
def main():
    """starlette-cms management commands."""
    pass


@main.group()
def migrate():
    """Database and schema migration commands."""
    pass


@migrate.command("status")
def migrate_status():
    """Show pending migrations."""
    click.echo("TODO: implement migrate status")


@migrate.command("run")
@click.option("--dry-run", is_flag=True, help="Show what would be run without applying.")
def migrate_run(dry_run: bool):
    """Apply pending migrations."""
    click.echo(f"TODO: implement migrate run (dry_run={dry_run})")


@main.command()
def validate():
    """Validate stored documents against current block schemas."""
    click.echo("TODO: implement validate")
