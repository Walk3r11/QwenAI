import os
from fastapi import FastAPI
from sqlalchemy import text
from auth_routes import router as auth_router
from config import ALLOW_PC_SCRIPT_SIGNUP, DATABASE_URL, ENABLE_AI, FRESHNESS_DEFAULT, FRESHNESS_MAX, FRESHNESS_MIN, JWT_SECRET
from db import Base, SessionLocal, engine
from email_service import is_email_configured
from groq_client import groq_configured
import models
from groups_routes import router as groups_router
from pantry_routes import router as pantry_router
from recipes_routes import router as recipes_router
from share_routes import router as share_router
app = FastAPI(title='SnapChef Backend', version='1.0.0')
app.include_router(auth_router)
app.include_router(groups_router)
app.include_router(pantry_router)
app.include_router(recipes_router)
app.include_router(share_router)
from ai_routes import router as ai_router
app.include_router(ai_router)


def _pg_table_columns(conn, table: str) -> set[str]:
    rows = conn.execute(
        text(
            'SELECT column_name FROM information_schema.columns '
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {'t': table},
    ).fetchall()
    return {r[0] for r in rows}


def _upgrade_pantry_items_postgres(conn) -> None:
    if not conn.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'pantry_items'")
    ).first():
        return
    cols = _pg_table_columns(conn, 'pantry_items')
    if 'session_id' not in cols:
        conn.execute(text('ALTER TABLE pantry_items ADD COLUMN session_id INTEGER'))
    if 'freshness' not in cols:
        conn.execute(text('ALTER TABLE pantry_items ADD COLUMN freshness INTEGER'))
        conn.execute(text(f'UPDATE pantry_items SET freshness = {FRESHNESS_DEFAULT} WHERE freshness IS NULL'))
        conn.execute(text(f'ALTER TABLE pantry_items ALTER COLUMN freshness SET DEFAULT {FRESHNESS_DEFAULT}'))
        conn.execute(text('ALTER TABLE pantry_items ALTER COLUMN freshness SET NOT NULL'))
    if 'expires_at' not in cols:
        conn.execute(text('ALTER TABLE pantry_items ADD COLUMN expires_at TIMESTAMP WITH TIME ZONE'))
    if 'image_id' not in cols:
        conn.execute(text('ALTER TABLE pantry_items ADD COLUMN image_id VARCHAR(64)'))
    conn.commit()
    fk = conn.execute(
        text(
            "SELECT 1 FROM information_schema.table_constraints WHERE table_schema = 'public' "
            "AND table_name = 'pantry_items' AND constraint_type = 'FOREIGN KEY' "
            "AND constraint_name = 'pantry_items_session_id_fkey'"
        )
    ).first()
    if not fk:
        try:
            conn.execute(
                text(
                    'ALTER TABLE pantry_items ADD CONSTRAINT pantry_items_session_id_fkey '
                    'FOREIGN KEY (session_id) REFERENCES scan_sessions(id) ON DELETE SET NULL'
                )
            )
            conn.commit()
        except Exception:
            conn.rollback()


def _upgrade_users_verification_postgres(conn) -> None:
    if not conn.execute(text("SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'users'")).first():
        return
    cols = _pg_table_columns(conn, 'users')
    if 'is_verified' not in cols:
        conn.execute(text('ALTER TABLE users ADD COLUMN is_verified BOOLEAN NOT NULL DEFAULT true'))
        conn.commit()
    if 'verification_code' not in cols:
        conn.execute(text('ALTER TABLE users ADD COLUMN verification_code VARCHAR(6)'))
        conn.commit()


def _upgrade_users_verification_sqlite(conn) -> None:
    rows = conn.execute(text("PRAGMA table_info(users)")).fetchall()
    cols = {r[1] for r in rows}
    if 'is_verified' not in cols:
        conn.execute(text('ALTER TABLE users ADD COLUMN is_verified BOOLEAN DEFAULT 1 NOT NULL'))
        conn.commit()
    if 'verification_code' not in cols:
        conn.execute(text('ALTER TABLE users ADD COLUMN verification_code VARCHAR(6)'))
        conn.commit()


@app.on_event('startup')
def on_startup():
    if engine.dialect.name == 'postgresql':
        with engine.connect() as conn:
            has_new_schema = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_name='scan_sessions'")).first()
            if not has_new_schema:
                for old_table in ('scan_recipes', 'scans', 'scan_items', 'scan_images', 'session_recipes', 'freshness_refs'):
                    conn.execute(text(f'DROP TABLE IF EXISTS {old_table}'))
                conn.commit()
            else:
                has_int_freshness = conn.execute(text("SELECT data_type FROM information_schema.columns WHERE table_name='scan_items' AND column_name='freshness' AND data_type='integer'")).first()
                if not has_int_freshness:
                    for tbl in ('session_recipes', 'scan_items', 'scan_images', 'scan_sessions', 'freshness_refs'):
                        conn.execute(text(f'DROP TABLE IF EXISTS {tbl} CASCADE'))
                    conn.commit()
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == 'postgresql':
        with engine.connect() as conn:
            _upgrade_users_verification_postgres(conn)
            _upgrade_pantry_items_postgres(conn)
    elif engine.dialect.name == 'sqlite':
        with engine.connect() as conn:
            _upgrade_users_verification_sqlite(conn)
    with SessionLocal() as db:
        from identification_seed import ensure_identification_groups
        try:
            ensure_identification_groups(db)
        except Exception:
            db.rollback()
            raise

@app.get('/health')
def health():
    db_ok = False
    try:
        with SessionLocal() as db:
            db.execute(text('SELECT 1'))
            db_ok = True
    except Exception:
        db_ok = False
    groq_ok = groq_configured()
    return {'ok': True, 'db_connected': db_ok, 'using_neon': 'neon.tech' in DATABASE_URL, 'jwt_configured': bool(JWT_SECRET), 'email_configured': is_email_configured(), 'ai_enabled': ENABLE_AI, 'vision_ready': groq_ok if ENABLE_AI else None, 'groq_configured': groq_ok, 'freshness_min': FRESHNESS_MIN, 'freshness_max': FRESHNESS_MAX, 'freshness_default': FRESHNESS_DEFAULT, 'allow_pc_script_signup': ALLOW_PC_SCRIPT_SIGNUP}
if __name__ == '__main__':
    import uvicorn
    uvicorn.run('main:app', host='0.0.0.0', port=int(os.getenv('PORT', '8000')))
