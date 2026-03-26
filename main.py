import os

from fastapi import FastAPI
from sqlalchemy import text

from ai_routes import router as ai_router
from auth_routes import router as auth_router
from config import DATABASE_URL, JWT_SECRET
from db import Base, SessionLocal, engine
import models

app = FastAPI(title="SnapChef Backend", version="1.0.0")

app.include_router(auth_router)
app.include_router(ai_router)


@app.on_event("startup")
def on_startup():
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
        "model_file_present": os.path.exists("/models/qwen.gguf"),
        "mmproj_file_present": os.path.exists("/models/mmproj.gguf"),
    }
