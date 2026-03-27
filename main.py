import os
from fastapi import FastAPI
from sqlalchemy import text
from auth_routes import router as auth_router
from config import DATABASE_URL, ENABLE_AI, JWT_SECRET, MODEL_DIR
from db import Base, SessionLocal, engine
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
if ENABLE_AI:
    from ai_routes import router as ai_router
    app.include_router(ai_router)

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
    model_present = os.path.exists(f'{MODEL_DIR}/qwen.gguf')
    mmproj_present = os.path.exists(f'{MODEL_DIR}/mmproj.gguf')
    return {'ok': True, 'db_connected': db_ok, 'using_neon': 'neon.tech' in DATABASE_URL, 'jwt_configured': bool(JWT_SECRET), 'ai_enabled': ENABLE_AI, 'model_file_present': model_present if ENABLE_AI else None, 'mmproj_file_present': mmproj_present if ENABLE_AI else None, 'groq_configured': groq_configured()}
if __name__ == '__main__':
    import uvicorn
    uvicorn.run('main:app', host='0.0.0.0', port=int(os.getenv('PORT', '8000')))