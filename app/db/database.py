from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

# pre_ping because the Supabase pooler drops idle connections between long worker jobs
engine = create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
