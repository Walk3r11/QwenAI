import os

from fastapi import FastAPI
from sqlalchemy import text

from auth_routes import router as auth_router
from config import DATABASE_URL, ENABLE_AI, JWT_SECRET, MODEL_DIR
from db import Base, SessionLocal, engine
import models
from groups_routes import router as groups_router
from pantry_routes import router as pantry_router
from recipes_routes import router as recipes_router
from share_routes import router as share_router

app = FastAPI(title="SnapChef Backend", version="1.0.0")

app.include_router(auth_router)
app.include_router(groups_router)
app.include_router(pantry_router)
app.include_router(recipes_router)
app.include_router(share_router)
if ENABLE_AI:
    from ai_routes import router as ai_router

    app.include_router(ai_router)


@app.on_event("startup")
def on_startup():
    with engine.connect() as conn:
        has_scan_items = conn.execute(
            text("SELECT table_name FROM information_schema.tables "
                 "WHERE table_name='scan_items'")
        ).first()
        if not has_scan_items:
            conn.execute(text("DROP TABLE IF EXISTS scan_recipes"))
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

    model_present = os.path.exists(f"{MODEL_DIR}/qwen.gguf")
    mmproj_present = os.path.exists(f"{MODEL_DIR}/mmproj.gguf")

    return {
        "ok": True,
        "db_connected": db_ok,
        "using_neon": "neon.tech" in DATABASE_URL,
        "jwt_configured": bool(JWT_SECRET),
        "ai_enabled": ENABLE_AI,
        "model_file_present": model_present if ENABLE_AI else None,
        "mmproj_file_present": mmproj_present if ENABLE_AI else None,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
