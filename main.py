import os

from fastapi import FastAPI
from sqlalchemy import text

from ai_routes import router as ai_router
from auth_routes import router as auth_router
from config import DATABASE_URL, JWT_SECRET, MODEL_DIR
from db import Base, SessionLocal, engine
import models

app = FastAPI(title="SnapChef Backend", version="1.0.0")

app.include_router(auth_router)
app.include_router(ai_router)


@app.on_event("startup")
def on_startup():
    with engine.connect() as conn:
        has_scan_id = conn.execute(
            text("SELECT column_name FROM information_schema.columns "
                 "WHERE table_name='recipes' AND column_name='scan_id'")
        ).first()
        if not has_scan_id:
            conn.execute(text("DROP TABLE IF EXISTS recipes"))
            conn.execute(text("DROP TABLE IF EXISTS scans"))
            conn.commit()
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    db_ok = False
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        db_ok = False

    return {
        "ok": True,
        "db_connected": db_ok,
        "using_neon": "neon.tech" in DATABASE_URL,
        "jwt_configured": bool(JWT_SECRET),
        "model_file_present": os.path.exists(f"{MODEL_DIR}/qwen.gguf"),
        "mmproj_file_present": os.path.exists(f"{MODEL_DIR}/mmproj.gguf"),
    }
