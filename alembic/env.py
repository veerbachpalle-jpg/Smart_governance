import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.modules.activity.models.activity  # noqa: F401
import app.modules.ai_assist.models.ai_interpretation  # noqa: F401
import app.modules.audit.models.audit  # noqa: F401
import app.modules.cases.models.case  # noqa: F401
import app.modules.challenges.models.challenge  # noqa: F401
import app.modules.complaints.models.complaint  # noqa: F401
import app.modules.duplicates.models.duplicate  # noqa: F401
import app.modules.evaluation.models.evaluation  # noqa: F401
import app.modules.identity.models.user  # noqa: F401  # noqa: F401
import app.modules.notifications.models.notification  # noqa: F401
import app.modules.priority.models.priority  # noqa: F401
import app.modules.routing.models.routing  # noqa: F401
from alembic import context
from app.config import settings
from app.core import idempotency, outbox  # noqa: F401
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = settings.DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True if "sqlite" in settings.DATABASE_URL else False,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async connection."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = settings.DATABASE_URL
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
