import base64
import io
import json
import os
import re

import requests
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from config import ANALYZE_PROMPT, LLAMA_MODEL, LLAMA_URL, MODEL_DIR
from db import SessionLocal, get_db
from models import Recipe, Scan, User
from schemas import FoodItem, RateRequest, RecipeOut, ScanOut
from security import get_current_user

router = APIRouter(prefix="/ai", tags=["ai"])

THUMB_MAX = 1080


def _make_thumbnail(image_bytes: bytes, mime: str) -> str:
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((THUMB_MAX, THUMB_MAX))
    buf = io.BytesIO()
    fmt = "PNG" if "png" in mime else "JPEG"
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _collect_streamed(resp: requests.Response) -> str:
    chunks: list[str] = []
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload.strip() == "[DONE]":
            break
        try:
            obj = json.loads(payload)
            delta = obj["choices"][0].get("delta", {})
            content = delta.get("content")
            if content:
                chunks.append(content)
        except (json.JSONDecodeError, KeyError, IndexError):
            continue
    return "".join(chunks)


def _parse_ai_json(raw: str) -> dict:
    match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    text = match.group(1).strip() if match else raw.strip()
    return json.loads(text)


@router.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    if not os.path.exists(f"{MODEL_DIR}/qwen.gguf") or not os.path.exists(f"{MODEL_DIR}/mmproj.gguf"):
        raise HTTPException(
            status_code=503,
            detail="Model files not found. Set MODEL_URL and MMPROJ_URL in Railway variables and redeploy.",
        )

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Upload an image file.")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file.")

    mime = file.content_type
    user_id = user.id

    def _stream():
        yield json.dumps({"status": "processing"}) + "\n"

        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{mime};base64,{image_b64}"
        payload = {
            "model": LLAMA_MODEL,
            "stream": True,
            "max_tokens": 1024,
            "temperature": 0.2,
            "frequency_penalty": 0.8,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": ANALYZE_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        }

        try:
            resp = requests.post(LLAMA_URL, json=payload, timeout=60, stream=True)
        except requests.RequestException as e:
            yield json.dumps({"status": "error", "detail": str(e)}) + "\n"
            return

        if resp.status_code >= 400:
            yield json.dumps({"status": "error", "detail": resp.text}) + "\n"
            return

        chunks: list[str] = []
        token_count = 0
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            raw_payload = line[6:]
            if raw_payload.strip() == "[DONE]":
                break
            try:
                obj = json.loads(raw_payload)
                delta = obj["choices"][0].get("delta", {})
                content = delta.get("content")
                if content:
                    chunks.append(content)
                    token_count += 1
                    if token_count % 20 == 0:
                        yield json.dumps({"status": "generating", "tokens": token_count}) + "\n"
            except (json.JSONDecodeError, KeyError, IndexError):
                continue

        raw_text = "".join(chunks)
        if not raw_text:
            yield json.dumps({"status": "error", "detail": "Empty response from model."}) + "\n"
            return

        try:
            parsed = _parse_ai_json(raw_text)
        except (json.JSONDecodeError, ValueError):
            yield json.dumps({"status": "error", "detail": "Invalid JSON from model", "raw": raw_text}) + "\n"
            return

        items = parsed.get("items", [])
        tip = parsed.get("tip")
        recipe_list = parsed.get("recipes", [])

        try:
            thumb = _make_thumbnail(image_bytes, mime)
        except Exception:
            thumb = None

        db = SessionLocal()
        try:
            scan = Scan(
                user_id=user_id,
                image_thumbnail=thumb,
                image_mime=mime,
                items_json=json.dumps(items),
                tip=tip,
                raw_response=raw_text,
            )
            db.add(scan)
            db.flush()

            db_recipes = []
            for r_data in recipe_list:
                recipe = Recipe(
                    scan_id=scan.id,
                    user_id=user_id,
                    name=r_data.get("name", "Untitled"),
                    uses_json=json.dumps(r_data.get("uses", [])),
                    extra_json=json.dumps(r_data.get("extra", [])),
                    steps_json=json.dumps(r_data.get("steps", [])),
                    minutes=r_data.get("minutes"),
                )
                db.add(recipe)
                db_recipes.append(recipe)

            db.commit()
            db.refresh(scan)
            for rec in db_recipes:
                db.refresh(rec)

            result = {
                "status": "done",
                "scan_id": scan.id,
                "items": [FoodItem(**i).model_dump() for i in items],
                "recipes": [
                    RecipeOut(
                        id=rec.id,
                        scan_id=rec.scan_id,
                        name=rec.name,
                        uses=json.loads(rec.uses_json),
                        extra=json.loads(rec.extra_json),
                        steps=json.loads(rec.steps_json),
                        minutes=rec.minutes,
                        rating=rec.rating,
                        created_at=rec.created_at,
                    ).model_dump(mode="json")
                    for rec in db_recipes
                ],
                "tip": tip,
            }
            yield json.dumps(result) + "\n"
        except Exception as e:
            db.rollback()
            yield json.dumps({"status": "error", "detail": f"DB error: {e}"}) + "\n"
        finally:
            db.close()

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@router.get("/history", response_model=list[ScanOut])
def history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Scan)
        .where(Scan.user_id == user.id)
        .options(selectinload(Scan.recipes))
        .order_by(Scan.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    scans = db.scalars(stmt).all()
    return [
        ScanOut(
            id=s.id,
            items=json.loads(s.items_json),
            recipes=[
                RecipeOut(
                    id=r.id,
                    scan_id=r.scan_id,
                    name=r.name,
                    uses=json.loads(r.uses_json),
                    extra=json.loads(r.extra_json),
                    steps=json.loads(r.steps_json),
                    minutes=r.minutes,
                    rating=r.rating,
                    created_at=r.created_at,
                )
                for r in s.recipes
            ],
            tip=s.tip,
            has_image=s.image_thumbnail is not None,
            created_at=s.created_at,
        )
        for s in scans
    ]


@router.get("/recipes", response_model=list[RecipeOut])
def recipe_reserve(
    rated_only: bool = Query(False),
    min_rating: int = Query(0, ge=0, le=5),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Recipe).where(Recipe.user_id == user.id)
    if rated_only:
        stmt = stmt.where(Recipe.rating.isnot(None))
    if min_rating > 0:
        stmt = stmt.where(Recipe.rating >= min_rating)
    stmt = stmt.order_by(Recipe.created_at.desc()).offset(offset).limit(limit)
    recipes = db.scalars(stmt).all()
    return [
        RecipeOut(
            id=r.id,
            scan_id=r.scan_id,
            name=r.name,
            uses=json.loads(r.uses_json),
            extra=json.loads(r.extra_json),
            steps=json.loads(r.steps_json),
            minutes=r.minutes,
            rating=r.rating,
            created_at=r.created_at,
        )
        for r in recipes
    ]


@router.patch("/recipes/{recipe_id}", response_model=RecipeOut)
def rate_recipe(
    recipe_id: int,
    body: RateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    recipe = db.scalar(select(Recipe).where(Recipe.id == recipe_id, Recipe.user_id == user.id))
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found.")
    recipe.rating = body.rating
    db.commit()
    db.refresh(recipe)
    return RecipeOut(
        id=recipe.id,
        scan_id=recipe.scan_id,
        name=recipe.name,
        uses=json.loads(recipe.uses_json),
        extra=json.loads(recipe.extra_json),
        steps=json.loads(recipe.steps_json),
        minutes=recipe.minutes,
        rating=recipe.rating,
        created_at=recipe.created_at,
    )


@router.get("/scans/{scan_id}/image")
def get_scan_image(
    scan_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scan = db.scalar(select(Scan).where(Scan.id == scan_id, Scan.user_id == user.id))
    if not scan or not scan.image_thumbnail:
        raise HTTPException(status_code=404, detail="Image not found.")
    return {"image": scan.image_thumbnail, "mime": scan.image_mime}
