import base64
import io
import json
import os
import re
from typing import List

import requests
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from config import LLAMA_MODEL, LLAMA_URL, MODEL_DIR, RECIPE_PROMPT, SCAN_PROMPT
from db import SessionLocal, get_db
from models import PantryItem, Scan, ScanItem, ScanRecipe, User
from schemas import (
    ConfirmResponse,
    RateRequest,
    ScanItemAddRequest,
    ScanItemOut,
    ScanItemUpdateRequest,
    ScanOut,
    ScanRecipeOut,
)
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


def _parse_ai_json(raw: str) -> dict:
    match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    text = match.group(1).strip() if match else raw.strip()
    brace = text.find("{")
    if brace > 0:
        text = text[brace:]
    return json.loads(text)


def _model_ready() -> bool:
    return (
        os.path.exists(f"{MODEL_DIR}/qwen.gguf")
        and os.path.exists(f"{MODEL_DIR}/mmproj.gguf")
    )


def _call_llm_streaming(messages: list[dict]) -> tuple[str, int]:
    payload = {
        "model": LLAMA_MODEL,
        "stream": True,
        "max_tokens": 1024,
        "temperature": 0.2,
        "frequency_penalty": 0.8,
        "messages": messages,
    }
    resp = requests.post(LLAMA_URL, json=payload, timeout=120, stream=True)
    if resp.status_code >= 400:
        raise RuntimeError(f"Model error {resp.status_code}: {resp.text}")
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
        except (json.JSONDecodeError, KeyError, IndexError):
            continue
    return "".join(chunks), token_count


def _build_scan_out(scan: Scan) -> ScanOut:
    return ScanOut(
        id=scan.id,
        status=scan.status,
        image_count=scan.image_count,
        items=[ScanItemOut.model_validate(i) for i in scan.items],
        recipes=[
            ScanRecipeOut(
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
            for r in scan.recipes
        ],
        created_at=scan.created_at,
    )


def _get_user_scan(db: Session, scan_id: int, user_id: int) -> Scan:
    scan = db.scalar(
        select(Scan)
        .where(Scan.id == scan_id, Scan.user_id == user_id)
        .options(selectinload(Scan.items), selectinload(Scan.recipes))
    )
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found.")
    return scan


@router.post("/scan")
async def scan_images(
    files: List[UploadFile] = File(...),
    user: User = Depends(get_current_user),
):
    if not _model_ready():
        raise HTTPException(status_code=503, detail="Model files not loaded.")

    if len(files) > 4:
        raise HTTPException(status_code=400, detail="Maximum 4 images per scan.")

    images: list[tuple[bytes, str]] = []
    for f in files:
        if not f.content_type or not f.content_type.startswith("image/"):
            raise HTTPException(status_code=415, detail=f"Not an image: {f.filename}")
        data = await f.read()
        if not data:
            raise HTTPException(status_code=400, detail=f"Empty file: {f.filename}")
        images.append((data, f.content_type))

    user_id = user.id
    image_count = len(images)

    def _stream():
        yield json.dumps({"status": "processing", "images": image_count}) + "\n"

        content_parts: list[dict] = [{"type": "text", "text": SCAN_PROMPT}]
        thumbnails: list[str] = []
        for img_bytes, mime in images:
            b64 = base64.b64encode(img_bytes).decode("ascii")
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })
            try:
                thumbnails.append(_make_thumbnail(img_bytes, mime))
            except Exception:
                thumbnails.append("")

        messages = [{"role": "user", "content": content_parts}]

        try:
            raw_text, total_tokens = _call_llm_streaming(messages)
        except Exception as e:
            yield json.dumps({"status": "error", "detail": str(e)}) + "\n"
            return

        yield json.dumps({"status": "generating", "tokens": total_tokens}) + "\n"

        if not raw_text:
            yield json.dumps({"status": "error", "detail": "Empty AI response."}) + "\n"
            return

        try:
            parsed = _parse_ai_json(raw_text)
        except (json.JSONDecodeError, ValueError):
            yield json.dumps({"status": "error", "detail": "Invalid JSON from AI", "raw": raw_text}) + "\n"
            return

        ai_items = parsed.get("items", [])

        db = SessionLocal()
        try:
            scan = Scan(
                user_id=user_id,
                status="draft",
                image_count=image_count,
                thumbnails_json=json.dumps(thumbnails),
                raw_response=raw_text,
            )
            db.add(scan)
            db.flush()

            for item_data in ai_items:
                name = str(item_data.get("name", "")).strip()
                if not name:
                    continue
                si = ScanItem(
                    scan_id=scan.id,
                    name=name,
                    qty=str(item_data.get("qty", "")),
                    freshness=item_data.get("freshness", "fresh"),
                    confidence=item_data.get("confidence"),
                    source="ai",
                )
                db.add(si)

            db.commit()

            scan = db.scalar(
                select(Scan)
                .where(Scan.id == scan.id)
                .options(selectinload(Scan.items), selectinload(Scan.recipes))
            )

            result = _build_scan_out(scan).model_dump(mode="json")
            result["status"] = "done"
            yield json.dumps(result) + "\n"
        except Exception as e:
            db.rollback()
            yield json.dumps({"status": "error", "detail": f"DB error: {e}"}) + "\n"
        finally:
            db.close()

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@router.get("/scans/{scan_id}", response_model=ScanOut)
def get_scan(
    scan_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scan = _get_user_scan(db, scan_id, user.id)
    return _build_scan_out(scan)


@router.post("/scans/{scan_id}/items", response_model=ScanItemOut)
def add_item(
    scan_id: int,
    body: ScanItemAddRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scan = _get_user_scan(db, scan_id, user.id)
    if scan.status != "draft":
        raise HTTPException(status_code=409, detail="Scan already confirmed.")
    item = ScanItem(
        scan_id=scan.id,
        name=body.name,
        qty=body.qty,
        freshness=body.freshness,
        source="manual",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return ScanItemOut.model_validate(item)


@router.patch("/scans/{scan_id}/items/{item_id}", response_model=ScanItemOut)
def update_item(
    scan_id: int,
    item_id: int,
    body: ScanItemUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scan = _get_user_scan(db, scan_id, user.id)
    if scan.status != "draft":
        raise HTTPException(status_code=409, detail="Scan already confirmed.")
    item = db.scalar(select(ScanItem).where(ScanItem.id == item_id, ScanItem.scan_id == scan.id))
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    if body.name is not None:
        item.name = body.name
    if body.qty is not None:
        item.qty = body.qty
    if body.freshness is not None:
        item.freshness = body.freshness
    db.commit()
    db.refresh(item)
    return ScanItemOut.model_validate(item)


@router.delete("/scans/{scan_id}/items/{item_id}", status_code=204)
def delete_item(
    scan_id: int,
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scan = _get_user_scan(db, scan_id, user.id)
    if scan.status != "draft":
        raise HTTPException(status_code=409, detail="Scan already confirmed.")
    item = db.scalar(select(ScanItem).where(ScanItem.id == item_id, ScanItem.scan_id == scan.id))
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    db.delete(item)
    db.commit()


@router.post("/scans/{scan_id}/confirm")
def confirm_scan(
    scan_id: int,
    user: User = Depends(get_current_user),
):
    db_check = SessionLocal()
    try:
        scan = db_check.scalar(
            select(Scan)
            .where(Scan.id == scan_id, Scan.user_id == user.id)
            .options(selectinload(Scan.items))
        )
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found.")
        if scan.status != "draft":
            raise HTTPException(status_code=409, detail="Scan already confirmed.")
        if not scan.items:
            raise HTTPException(status_code=400, detail="No items to confirm.")

        items_snapshot = [
            {"name": i.name, "qty": i.qty, "freshness": i.freshness, "id": i.id}
            for i in scan.items
        ]
        scan_id_val = scan.id
        user_id = user.id
    finally:
        db_check.close()

    def _stream():
        yield json.dumps({"status": "saving_pantry"}) + "\n"

        db = SessionLocal()
        try:
            scan = db.scalar(
                select(Scan)
                .where(Scan.id == scan_id_val)
                .options(selectinload(Scan.items))
            )

            pantry_count = 0
            for si in scan.items:
                pi = PantryItem(
                    user_id=user_id,
                    name=si.name,
                    quantity=1,
                    unit=si.qty if si.qty else None,
                    freshness=si.freshness,
                    source="scan",
                    scan_id=scan.id,
                )
                db.add(pi)
                db.flush()
                si.pantry_item_id = pi.id
                pantry_count += 1

            scan.status = "confirmed"
            db.commit()

            yield json.dumps({"status": "generating_recipes", "pantry_items": pantry_count}) + "\n"

            items_text = ", ".join(
                f"{i['name']} ({i['freshness']}, {i['qty']})" if i['qty'] else f"{i['name']} ({i['freshness']})"
                for i in items_snapshot
            )
            messages = [
                {
                    "role": "user",
                    "content": f"{RECIPE_PROMPT}\n\nPantry items: {items_text}",
                }
            ]

            try:
                raw_text, total_tokens = _call_llm_streaming(messages)
            except Exception as e:
                yield json.dumps({"status": "error", "detail": f"Recipe generation failed: {e}"}) + "\n"
                return

            yield json.dumps({"status": "generating", "tokens": total_tokens}) + "\n"

            if not raw_text:
                yield json.dumps({"status": "done", "scan_id": scan_id_val, "pantry_items_created": pantry_count, "recipes": [], "tip": None}) + "\n"
                return

            try:
                parsed = _parse_ai_json(raw_text)
            except (json.JSONDecodeError, ValueError):
                yield json.dumps({"status": "done", "scan_id": scan_id_val, "pantry_items_created": pantry_count, "recipes": [], "tip": raw_text[:500]}) + "\n"
                return

            recipe_list = parsed.get("recipes", [])
            tip = parsed.get("tip")

            db_recipes = []
            for r_data in recipe_list:
                recipe = ScanRecipe(
                    scan_id=scan_id_val,
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
            for rec in db_recipes:
                db.refresh(rec)

            result = ConfirmResponse(
                scan_id=scan_id_val,
                pantry_items_created=pantry_count,
                recipes=[
                    ScanRecipeOut(
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
            ).model_dump(mode="json")
            result["status"] = "done"
            yield json.dumps(result) + "\n"
        except HTTPException:
            raise
        except Exception as e:
            db.rollback()
            yield json.dumps({"status": "error", "detail": f"DB error: {e}"}) + "\n"
        finally:
            db.close()

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@router.get("/scans/{scan_id}/images")
def get_scan_images(
    scan_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scan = db.scalar(select(Scan).where(Scan.id == scan_id, Scan.user_id == user.id))
    if not scan or not scan.thumbnails_json:
        raise HTTPException(status_code=404, detail="Images not found.")
    return {"thumbnails": json.loads(scan.thumbnails_json)}


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
        .options(selectinload(Scan.items), selectinload(Scan.recipes))
        .order_by(Scan.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    scans = db.scalars(stmt).all()
    return [_build_scan_out(s) for s in scans]


@router.get("/recipes", response_model=list[ScanRecipeOut])
def recipe_list(
    rated_only: bool = Query(False),
    min_rating: int = Query(0, ge=0, le=5),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(ScanRecipe).where(ScanRecipe.user_id == user.id)
    if rated_only:
        stmt = stmt.where(ScanRecipe.rating.isnot(None))
    if min_rating > 0:
        stmt = stmt.where(ScanRecipe.rating >= min_rating)
    stmt = stmt.order_by(ScanRecipe.created_at.desc()).offset(offset).limit(limit)
    recipes = db.scalars(stmt).all()
    return [
        ScanRecipeOut(
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


@router.patch("/recipes/{recipe_id}", response_model=ScanRecipeOut)
def rate_recipe(
    recipe_id: int,
    body: RateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    recipe = db.scalar(
        select(ScanRecipe).where(ScanRecipe.id == recipe_id, ScanRecipe.user_id == user.id)
    )
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found.")
    recipe.rating = body.rating
    db.commit()
    db.refresh(recipe)
    return ScanRecipeOut(
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
