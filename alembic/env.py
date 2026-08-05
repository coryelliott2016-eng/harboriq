"""Alembic env — runs migrations against the app DATABASE_URL (service role)."""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Migrations run as the SERVICE role (BYPASSRLS) so they can create RLS
# policies and grant privileges. Application requests use the app role.
# Prefer SERVICE_DATABASE_URL so migrations always run as the service role even
# when DATABASE_URL (the app role) is set in the environment.
db_url = os.getenv("SERVICE_DATABASE_URL") or os.getenv("DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # One transaction per migration file, not one for the whole
        # `upgrade head` run. Required since migration 0015/0016 (Phase 15)
        # splits "ALTER TYPE ... ADD VALUE" from the DDL that uses the new
        # value across two files specifically so they land in separate
        # transactions -- Postgres forbids using a brand-new enum value in
        # the same transaction it was added in ("unsafe use of new value"),
        # and that restriction is enforced per-*transaction*, not per-file,
        # so without this flag the whole multi-revision run (0001..head)
        # shares one transaction and the restriction still applies across
        # files. Every migration's SQL is independently idempotent
        # (verbatim, IF EXISTS/IF NOT EXISTS-guarded where re-runnable) and
        # already tracked one-row-per-revision in alembic_version, so
        # committing each migration individually changes no other
        # migration's behavior.
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"), poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
