import base64
import io
import json
import os
import re

import requests
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from config import ANALYZE_PROMPT, LLAMA_MODEL, LLAMA_URL, MODEL_DIR
from db import get_db
from models import Recipe, Scan, User
from schemas import AnalyzeResponse, FoodItem, RateRequest, RecipeOut, ScanOut
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


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
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

    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{file.content_type};base64,{image_b64}"
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
        r = requests.post(LLAMA_URL, json=payload, timeout=600, stream=True)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach model server: {e}") from e

    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Model error {r.status_code}: {r.text}")

    raw_text = _collect_streamed(r)
    if not raw_text:
        raise HTTPException(status_code=502, detail="Empty response from model.")

    try:
        parsed = _parse_ai_json(raw_text)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=502, detail={"message": "Model returned invalid JSON", "raw": raw_text})

    items = parsed.get("items", [])
    tip = parsed.get("tip")
    recipe_list = parsed.get("recipes", [])

    try:
        thumb = _make_thumbnail(image_bytes, file.content_type)
    except Exception:
        thumb = None

    scan = Scan(
        user_id=user.id,
        image_thumbnail=thumb,
        image_mime=file.content_type,
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
            user_id=user.id,
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

    return AnalyzeResponse(
        scan_id=scan.id,
        items=[FoodItem(**i) for i in items],
        recipes=[
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
            )
            for rec in db_recipes
        ],
        tip=tip,
    )


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
