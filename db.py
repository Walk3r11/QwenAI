from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool
from config import DATABASE_URL

class Base(DeclarativeBase):
    pass
connect_args = {'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {}
engine_kwargs = {'future': True, 'pool_pre_ping': True, 'connect_args': connect_args}
if DATABASE_URL.startswith('sqlite') and ':memory:' in DATABASE_URL:
    engine_kwargs['poolclass'] = StaticPool
engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()