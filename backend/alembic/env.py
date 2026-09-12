from sqlalchemy import create_engine, pool

from alembic import context
from app.config import get_settings
from app.db.models import Base

config = context.config
# CLI environment is authoritative; never place real database credentials in alembic.ini.
url = str(get_settings().database_url).replace("postgresql://", "postgresql+psycopg://", 1)
target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"}
    )
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get("connection") is not None:
    connection = config.attributes["connection"]
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url, poolclass=pool.NullPool).connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
