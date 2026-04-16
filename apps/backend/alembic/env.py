import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from db.base import Base
# Import all models so Base.metadata is populated
from db.models import audit_logs, feature_flags  # noqa: F401

config = context.config

# Remplace l'URL synchrone par celle de l'env si présente (avec driver sync pour Alembic)
database_url = os.getenv("DATABASE_URL", "postgresql://archiclaude:archiclaude@localhost:5432/archiclaude")
# Alembic utilise le driver sync, pas asyncpg
sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
config.set_main_option("sqlalchemy.url", sync_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
