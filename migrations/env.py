from logging.config import fileConfig

from alembic import context

from app.db.database import engine
from app.db.models import Base

fileConfig(context.config.config_file_name)

# the engine comes from app settings so the DB URL is never written into alembic.ini
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
