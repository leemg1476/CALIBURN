from alembic import context
from sqlalchemy import create_engine

from caliburn.config import get_settings
from caliburn.tool_factory.schema import metadata


def migrate(connection):
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


provided = context.config.attributes.get("connection")
if provided is not None:
    migrate(provided)
else:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        migrate(connection)
    engine.dispose()
