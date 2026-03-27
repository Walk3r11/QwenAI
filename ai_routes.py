import asyncio
import base64
import io
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import List, cast
import requests
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from PIL import Image
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload
from config import GROQ_RECIPE_USER_PROMPT, GROQ_SYSTEM_PROMPT, LLAMA_HTTP_TIMEOUT, LLAMA_MODEL, LLAMA_URL, MODEL_DIR, RECIPE_PROMPT, SCAN_PROMPT, VISION_MAX_TOKENS
from identification_data import KNOWN_IDENTIFICATION_CODES
from db import SessionLocal, get_db
from groq_client import groq_chat_json, groq_configured
from models import FreshnessRef, IngredientIdentificationGroup, PantryItem, ScanImage, ScanItem, ScanItemIdentification, ScanSession, SessionRecipe, TrainingImage, User
from schemas import AddItemRequest, EditItemRequest, GroqRecipesBatchOut, IdentificationGroupOut, RateRequest, ScanImageOut, ScanItemOut, ScanSessionOut, SessionRecipeOut, TrainingImageOut, TrainingStatsOut
from security import get_current_user
router = APIRouter(prefix='/ai', tags=['ai'])
THUMB_MAX = 1080
_SESSION_EAGER = (selectinload(ScanSession.images), selectinload(ScanSession.items).selectinload(ScanItem.identification_links).selectinload(ScanItemIdentification.group), selectinload(ScanSession.recipes))
LLAMA_503_MAX_RETRIES = int(os.getenv('LLAMA_503_MAX_RETRIES', '36'))
LLAMA_503_SLEEP_SEC = float(os.getenv('LLAMA_503_SLEEP_SEC', '5'))

def _request_llama_stream(payload: dict):
    last_body = ''
    for _ in range(LLAMA_503_MAX_RETRIES):
        try:
            resp = requests.post(LLAMA_URL, json=payload, timeout=LLAMA_HTTP_TIMEOUT, stream=True)
        except requests.RequestException as e:
            return None, e
        if resp.status_code == 503:
            last_body = resp.text or ''
            resp.close()
            if any(x in last_body.lower() for x in ('loading', 'load', 'unavailable', 'not ready')):
                time.sleep(LLAMA_503_SLEEP_SEC)
                continue
            return resp, None
        return resp, None
    return None, RuntimeError(f'Llama stayed busy (503) after {LLAMA_503_MAX_RETRIES} retries: {last_body[:800]}')

def _normalize_identification_codes(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    for x in raw:
        c = str(x).strip().lower().replace('-', '_')[:64]
        if c in KNOWN_IDENTIFICATION_CODES and c not in out:
            out.append(c)
    return out

def _sync_scan_item_identifications(db: Session, scan_item_id: int, codes: list[str]) -> None:
    db.execute(delete(ScanItemIdentification).where(ScanItemIdentification.scan_item_id == scan_item_id))
    for code in codes:
        gid = db.scalar(select(IngredientIdentificationGroup.id).where(IngredientIdentificationGroup.code == code))
        if gid is not None:
            db.add(ScanItemIdentification(scan_item_id=scan_item_id, group_id=gid))

def _load_scan_item_with_groups(db: Session, item_id: int) -> ScanItem | None:
    return db.scalar(select(ScanItem).where(ScanItem.id == item_id).options(selectinload(ScanItem.identification_links).selectinload(ScanItemIdentification.group)))
_EXPIRY_HINTS_DAYS = {'milk': 5, 'yogurt': 7, 'cream': 5, 'cheese': 10, 'egg': 14, 'chicken': 2, 'beef': 3, 'pork': 3, 'fish': 2, 'salmon': 2, 'shrimp': 2, 'turkey': 2, 'spinach': 4, 'lettuce': 5, 'tomato': 6, 'cucumber': 6, 'broccoli': 5, 'carrot': 12, 'potato': 21, 'onion': 21, 'apple': 14, 'banana': 4, 'strawberry': 3, 'bread': 4, 'rice': 180, 'pasta': 180}

def _make_thumbnail(image_bytes: bytes, mime: str) -> str:
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((THUMB_MAX, THUMB_MAX))
    buf = io.BytesIO()
    fmt = 'PNG' if 'png' in mime else 'JPEG'
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode('ascii')

def _pantry_quantity_from_qty(qty: str | None) -> int:
    raw = (qty or '').strip() or '1'
    raw = raw.replace(',', '.').split()[0]
    try:
        return max(1, int(float(raw)))
    except (TypeError, ValueError):
        return 1

def _training_thumbnail_b64(scan_thumb_b64: str, max_side: int = 384) -> str:
    if not scan_thumb_b64:
        return scan_thumb_b64
    try:
        raw = base64.b64decode(scan_thumb_b64, validate=True)
    except Exception:
        return scan_thumb_b64
    try:
        img = Image.open(io.BytesIO(raw))
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=82)
        return base64.b64encode(buf.getvalue()).decode('ascii')
    except Exception:
        return scan_thumb_b64

def _json_list_is_recipe_shape(val: list) -> bool:
    if not val or not isinstance(val[0], dict):
        return False
    el0 = val[0]
    if not str(el0.get('name') or '').strip():
        return False
    if 'freshness' in el0 or 'groups' in el0 or el0.get('confidence') is not None:
        if 'steps' not in el0 and not (el0.get('uses') and 'minutes' in el0):
            return False
    return 'steps' in el0 or ('uses' in el0 and 'minutes' in el0)

def _parse_ai_json(raw: str) -> dict:
    text = raw.strip()
    fence = re.search('```(?:json)?\\s*(.*?)```', text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    text = text.strip()
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch not in '{[':
            continue
        try:
            val, _ = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            continue
        if isinstance(val, dict):
            return val
        if isinstance(val, list):
            if not val or not isinstance(val[0], dict):
                return {}
            if _json_list_is_recipe_shape(val):
                return {'recipes': val, 'tip': ''}
            return {'items': val, 'tip': ''}
    tail = json.loads(text)
    if isinstance(tail, list) and tail and isinstance(tail[0], dict):
        if _json_list_is_recipe_shape(tail):
            return {'recipes': tail, 'tip': ''}
        return {'items': tail, 'tip': ''}
    if isinstance(tail, dict):
        return tail
    return {}

def _normalize_scan_item_row(d: dict) -> dict | None:
    if not isinstance(d, dict):
        return None
    name = d.get('name') or d.get('item') or d.get('food') or d.get('product') or d.get('label') or d.get('ingredient')
    name = str(name or '').strip()
    if not name:
        return None
    out = dict(d)
    out['name'] = name
    return out

def _scan_item_entries_from_parsed(parsed) -> list[dict]:
    if isinstance(parsed, list):
        rows = [_normalize_scan_item_row(x) for x in parsed if isinstance(x, dict)]
        return [x for x in rows if x]
    if not isinstance(parsed, dict):
        return []
    for key in ('items', 'Items', 'food_items', 'foods', 'detected_items', 'ingredients', 'products', 'inventory', 'pantry_items', 'scanned_items', 'results', 'detections'):
        v = parsed.get(key)
        if isinstance(v, list):
            rows = [_normalize_scan_item_row(x) for x in v if isinstance(x, dict)]
            rows = [x for x in rows if x]
            if rows:
                return rows
    one = parsed.get('item')
    if isinstance(one, dict):
        r = _normalize_scan_item_row(one)
        return [r] if r else []
    for nest in ('data', 'result', 'output', 'response', 'scan', 'content', 'analysis', 'payload'):
        inner = parsed.get(nest)
        if isinstance(inner, dict):
            got = _scan_item_entries_from_parsed(inner)
            if got:
                return got
        if isinstance(inner, list) and inner and isinstance(inner[0], dict):
            rows = [_normalize_scan_item_row(x) for x in inner if isinstance(x, dict)]
            rows = [x for x in rows if x]
            if rows:
                return rows
    recipes = parsed.get('recipes')
    if isinstance(recipes, list) and recipes and isinstance(recipes[0], dict):
        if not _json_list_is_recipe_shape(recipes):
            rows = [_normalize_scan_item_row(x) for x in recipes if isinstance(x, dict)]
            rows = [x for x in rows if x]
            if rows:
                return rows
    return []

def _extract_scan_items_for_session(parsed) -> list[dict]:
    if isinstance(parsed, list):
        if _json_list_is_recipe_shape(parsed):
            return []
        rows = [_normalize_scan_item_row(x) for x in parsed if isinstance(x, dict)]
        return [x for x in rows if x]
    return _scan_item_entries_from_parsed(parsed)

def _recipe_entries_from_parsed(parsed) -> list[dict]:
    if isinstance(parsed, list):
        return [x for x in parsed if isinstance(x, dict)]
    if not isinstance(parsed, dict):
        return []
    for key in ('recipes', 'Recipes', 'recipe_list', 'recipeList', 'suggestions', 'meal_ideas', 'meals'):
        v = parsed.get(key)
        if isinstance(v, list) and v:
            return [x for x in v if isinstance(x, dict)]
        if isinstance(v, dict) and str(v.get('name') or '').strip():
            return [v]
    for sk in ('recipe', 'Recipe'):
        one = parsed.get(sk)
        if isinstance(one, dict) and str(one.get('name') or '').strip():
            return [one]
    for nest_key in ('data', 'result', 'output', 'response', 'content'):
        inner = parsed.get(nest_key)
        if isinstance(inner, dict):
            got = _recipe_entries_from_parsed(inner)
            if got:
                return got
        if isinstance(inner, list) and inner and isinstance(inner[0], dict):
            if nest_key == 'content' and 'name' not in inner[0]:
                continue
            return [x for x in inner if isinstance(x, dict)]
    name = parsed.get('name')
    if isinstance(name, str) and name.strip():
        if any((k in parsed for k in ('steps', 'uses', 'extra', 'minutes'))):
            return [parsed]
    return []

def _normalize_recipe_dict(r: dict) -> dict | None:
    name = str(r.get('name') or '').strip()
    if not name:
        return None

    def _str_list(x) -> list[str]:
        if x is None:
            return []
        if isinstance(x, str):
            return [x.strip()] if x.strip() else []
        if isinstance(x, list):
            return [str(i).strip() for i in x if str(i).strip()]
        return []
    minutes = r.get('minutes')
    if minutes is not None:
        try:
            minutes = int(float(minutes))
        except (TypeError, ValueError):
            minutes = None
    return {'name': name, 'uses': _str_list(r.get('uses')), 'extra': _str_list(r.get('extra')), 'steps': _str_list(r.get('steps')), 'minutes': minutes}

def _collect_streamed(resp: requests.Response) -> tuple[str, int]:
    chunks: list[str] = []
    token_count = 0
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith('data: '):
            continue
        payload = line[6:]
        if payload.strip() == '[DONE]':
            break
        try:
            obj = json.loads(payload)
            delta = obj['choices'][0].get('delta', {})
            content = delta.get('content')
            if content:
                chunks.append(content)
                token_count += 1
        except (json.JSONDecodeError, KeyError, IndexError):
            continue
    return (''.join(chunks), token_count)

def _collect_streamed_with_progress(resp: requests.Response):
    chunks: list[str] = []
    token_count = 0
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith('data: '):
            continue
        payload = line[6:]
        if payload.strip() == '[DONE]':
            break
        try:
            obj = json.loads(payload)
            delta = obj['choices'][0].get('delta', {})
            content = delta.get('content')
            if content:
                chunks.append(content)
                token_count += 1
                if token_count % 20 == 0:
                    yield (token_count, None)
        except (json.JSONDecodeError, KeyError, IndexError):
            continue
    yield (token_count, ''.join(chunks))

def _model_ready() -> bool:
    return os.path.exists(f'{MODEL_DIR}/qwen.gguf') and os.path.exists(f'{MODEL_DIR}/mmproj.gguf')

def _estimate_expires(name: str) -> datetime | None:
    lowered = name.lower()
    for key, days in _EXPIRY_HINTS_DAYS.items():
        if key in lowered:
            return datetime.now(timezone.utc) + timedelta(days=days)
    return None

def _freshness_alert(score: int) -> str | None:
    if score <= 1:
        return 'SPOILED — do NOT consume, discard immediately'
    if score <= 3:
        return 'WARNING — about to expire, use today or discard'
    if score <= 5:
        return 'Use soon — quality is declining'
    return None

def _freshness_label(score: float) -> str:
    if score >= 8:
        return 'fresh'
    if score >= 6:
        return 'good'
    if score >= 4:
        return 'use-soon'
    if score >= 2:
        return 'expiring'
    return 'spoiled'

def _build_freshness_context(db: Session, user_id: int) -> str:
    refs = db.scalars(select(FreshnessRef).order_by(FreshnessRef.observations.desc()).limit(30)).all()
    training_counts = {}
    rows = db.execute(select(TrainingImage.product_name, func.count(TrainingImage.id)).where(TrainingImage.user_id == user_id).group_by(TrainingImage.product_name)).all()
    for name, count in rows:
        training_counts[name] = count
    if not refs and (not training_counts):
        return ''
    lines = []
    for r in refs:
        label = _freshness_label(r.avg_freshness)
        imgs = training_counts.get(r.product_name, 0)
        lines.append(f'  {r.product_name}: avg {r.avg_freshness:.1f}/10 ({label}), seen {r.observations}x, last scored {r.last_freshness}/10, {imgs} training images saved')
    return '\n\nYou have learned from previous scans. Use this data to improve accuracy:\n' + '\n'.join(lines) + "\nBe more precise for products you've seen many times.\n"

def _clamp_freshness(val) -> int:
    try:
        v = int(val)
    except (TypeError, ValueError):
        return 8
    return max(1, min(10, v))

def _update_freshness_refs(db: Session, items: list[dict]):
    for item in items:
        name = item.get('name', '').strip().lower()
        freshness = _clamp_freshness(item.get('freshness', 8))
        if not name:
            continue
        ref = db.scalar(select(FreshnessRef).where(FreshnessRef.product_name == name))
        if ref:
            ref.avg_freshness = (ref.avg_freshness * ref.observations + freshness) / (ref.observations + 1)
            ref.observations += 1
            ref.last_freshness = freshness
        else:
            db.add(FreshnessRef(product_name=name, avg_freshness=float(freshness), last_freshness=freshness, observations=1))

def _item_to_out(item: ScanItem) -> ScanItemOut:
    id_groups: list[IdentificationGroupOut] = []
    links = getattr(item, 'identification_links', None) or []
    if links:
        for L in sorted(links, key=lambda x: (x.group.sort_order, x.group.code)):
            id_groups.append(IdentificationGroupOut(id=L.group.id, code=L.group.code, label=L.group.label))
    return ScanItemOut(id=item.id, name=item.name, freshness=item.freshness, qty=item.qty, unit=item.unit, confidence=item.confidence, source=item.source, alert=_freshness_alert(item.freshness), identification_groups=id_groups)

def _session_to_out(session: ScanSession) -> ScanSessionOut:
    return ScanSessionOut(id=session.id, status=session.status, images=[ScanImageOut(id=img.id, mime=img.mime) for img in session.images], items=[_item_to_out(item) for item in session.items], recipes=[SessionRecipeOut(id=r.id, session_id=r.session_id, name=r.name, uses=json.loads(r.uses_json), extra=json.loads(r.extra_json), steps=json.loads(r.steps_json), minutes=r.minutes, rating=r.rating, created_at=cast(datetime, r.created_at)) for r in session.recipes], tip=session.tip, created_at=cast(datetime, session.created_at))
MAX_SCAN_UPLOADS = 50

@router.post('/sessions')
async def create_session(files: List[UploadFile]=File(...), buffer: bool=Query(False, description='If true, return one JSON when the scan finishes (avoids long-lived chunked streams through proxies).'), user: User=Depends(get_current_user)):
    if not _model_ready():
        raise HTTPException(status_code=503, detail='Model files not ready.')
    if len(files) < 1 or len(files) > MAX_SCAN_UPLOADS:
        raise HTTPException(status_code=400, detail=f'Upload 1 to {MAX_SCAN_UPLOADS} images per session.')
    image_data: list[tuple[bytes, str]] = []
    for f in files:
        if not f.content_type or not f.content_type.startswith('image/'):
            raise HTTPException(status_code=415, detail=f"File '{f.filename}' is not an image.")
        raw = await f.read()
        if not raw:
            raise HTTPException(status_code=400, detail=f"File '{f.filename}' is empty.")
        image_data.append((raw, f.content_type))
    user_id = user.id

    def _stream():
        yield (json.dumps({'status': 'processing', 'images': len(image_data)}) + '\n')
        thumbnails: list[tuple[str, str]] = []
        content_parts: list[dict] = []
        ref_db = SessionLocal()
        try:
            freshness_ctx = _build_freshness_context(ref_db, user_id)
        finally:
            ref_db.close()
        prompt_text = SCAN_PROMPT
        if freshness_ctx:
            prompt_text += freshness_ctx
        content_parts.append({'type': 'text', 'text': prompt_text})
        for raw_bytes, mime in image_data:
            try:
                thumb = _make_thumbnail(raw_bytes, mime)
                thumbnails.append((thumb, mime))
            except Exception:
                thumbnails.append(('', mime))
            b64 = base64.b64encode(raw_bytes).decode('ascii')
            data_url = f'data:{mime};base64,{b64}'
            content_parts.append({'type': 'image_url', 'image_url': {'url': data_url}})
        payload = {'model': LLAMA_MODEL, 'stream': True, 'max_tokens': VISION_MAX_TOKENS, 'temperature': 0.2, 'frequency_penalty': 0.8, 'messages': [{'role': 'user', 'content': content_parts}]}
        resp, err = _request_llama_stream(payload)
        if err is not None:
            yield (json.dumps({'status': 'error', 'detail': str(err)}) + '\n')
            return
        if resp is None:
            yield (json.dumps({'status': 'error', 'detail': 'No response from vision server.'}) + '\n')
            return
        if resp.status_code >= 400:
            yield (json.dumps({'status': 'error', 'detail': resp.text}) + '\n')
            return
        raw_text = None
        for token_count, final_text in _collect_streamed_with_progress(resp):
            if final_text is None:
                yield (json.dumps({'status': 'generating', 'tokens': token_count}) + '\n')
            else:
                raw_text = final_text
        if not raw_text:
            yield (json.dumps({'status': 'error', 'detail': 'Empty response from model.'}) + '\n')
            return
        try:
            parsed = _parse_ai_json(raw_text)
        except (json.JSONDecodeError, ValueError):
            yield (json.dumps({'status': 'error', 'detail': 'Invalid JSON from model', 'raw': raw_text}) + '\n')
            return
        ai_items = _extract_scan_items_for_session(parsed)
        tip = parsed.get('tip')
        db = SessionLocal()
        try:
            session = ScanSession(user_id=user_id, status='pending', raw_response=raw_text, tip=tip)
            db.add(session)
            db.flush()
            for thumb_b64, mime in thumbnails:
                if thumb_b64:
                    db.add(ScanImage(session_id=session.id, thumbnail=thumb_b64, mime=mime))
            for item_data in ai_items:
                name = str(item_data.get('name', '')).strip()
                if not name:
                    continue
                item = ScanItem(session_id=session.id, name=name, freshness=_clamp_freshness(item_data.get('freshness', 8)), qty=str(item_data.get('qty', '')), unit=item_data.get('unit'), confidence=item_data.get('confidence'), source='ai')
                db.add(item)
                db.flush()
                codes = _normalize_identification_codes(item_data.get('groups'))
                _sync_scan_item_identifications(db, item.id, codes)
            _update_freshness_refs(db, ai_items)
            db.commit()
            row = db.scalar(select(ScanSession).where(ScanSession.id == session.id).options(*_SESSION_EAGER))
            if not row:
                yield (json.dumps({'status': 'error', 'detail': 'Session reload failed.'}) + '\n')
                return
            result = _session_to_out(row).model_dump(mode='json')
            result['status_msg'] = 'done'
            yield (json.dumps(result) + '\n')
        except Exception as e:
            db.rollback()
            yield (json.dumps({'status': 'error', 'detail': f'DB error: {e}'}) + '\n')
        finally:
            db.close()
    if buffer:

        def _drain():
            return list(_stream())

        chunks = await asyncio.to_thread(_drain)
        if not chunks:
            raise HTTPException(status_code=502, detail='Scan produced no output.')
        last_raw = chunks[-1].strip()
        try:
            data = json.loads(last_raw)
        except json.JSONDecodeError:
            raise HTTPException(status_code=502, detail=f'Invalid final JSON: {last_raw[:400]}') from None
        if data.get('status') == 'error':
            raise HTTPException(status_code=502, detail=str(data.get('detail', data)))
        if data.get('status_msg') != 'done' or data.get('id') is None:
            raise HTTPException(status_code=502, detail=data)
        return JSONResponse(content=data)
    return StreamingResponse(_stream(), media_type='application/x-ndjson')

@router.get('/sessions', response_model=list[ScanSessionOut])
def list_sessions(limit: int=Query(20, ge=1, le=100), offset: int=Query(0, ge=0), user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    stmt = select(ScanSession).where(ScanSession.user_id == user.id).options(*_SESSION_EAGER).order_by(ScanSession.created_at.desc()).offset(offset).limit(limit)
    sessions = db.scalars(stmt).all()
    return [_session_to_out(s) for s in sessions]

@router.get('/sessions/{session_id}', response_model=ScanSessionOut)
def get_session(session_id: int, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    session = db.scalar(select(ScanSession).where(ScanSession.id == session_id, ScanSession.user_id == user.id).options(*_SESSION_EAGER))
    if not session:
        raise HTTPException(status_code=404, detail='Session not found.')
    return _session_to_out(session)

@router.get('/identification-groups', response_model=list[IdentificationGroupOut])
def list_identification_groups(db: Session=Depends(get_db)):
    rows = db.scalars(select(IngredientIdentificationGroup).order_by(IngredientIdentificationGroup.sort_order, IngredientIdentificationGroup.code)).all()
    return [IdentificationGroupOut(id=r.id, code=r.code, label=r.label) for r in rows]

@router.post('/sessions/{session_id}/items', response_model=ScanItemOut, status_code=201)
def add_item(session_id: int, body: AddItemRequest, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    session = db.scalar(select(ScanSession).where(ScanSession.id == session_id, ScanSession.user_id == user.id))
    if not session:
        raise HTTPException(status_code=404, detail='Session not found.')
    if session.status != 'pending':
        raise HTTPException(status_code=409, detail='Session already confirmed.')
    item = ScanItem(session_id=session.id, name=body.name.strip(), freshness=body.freshness, qty=body.qty, unit=body.unit, source='manual')
    db.add(item)
    db.flush()
    _sync_scan_item_identifications(db, item.id, _normalize_identification_codes(body.identification_group_codes))
    db.commit()
    loaded = _load_scan_item_with_groups(db, item.id)
    if not loaded:
        raise HTTPException(status_code=500, detail='Item save failed.')
    return _item_to_out(loaded)

@router.patch('/sessions/{session_id}/items/{item_id}', response_model=ScanItemOut)
def edit_item(session_id: int, item_id: int, body: EditItemRequest, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    session = db.scalar(select(ScanSession).where(ScanSession.id == session_id, ScanSession.user_id == user.id))
    if not session:
        raise HTTPException(status_code=404, detail='Session not found.')
    if session.status != 'pending':
        raise HTTPException(status_code=409, detail='Session already confirmed.')
    item = db.scalar(select(ScanItem).where(ScanItem.id == item_id, ScanItem.session_id == session_id))
    if not item:
        raise HTTPException(status_code=404, detail='Item not found.')
    if body.name is not None:
        item.name = body.name.strip()
    if body.freshness is not None:
        item.freshness = body.freshness
    if body.qty is not None:
        item.qty = body.qty
    if body.unit is not None:
        item.unit = body.unit
    if body.identification_group_codes is not None:
        _sync_scan_item_identifications(db, item.id, _normalize_identification_codes(body.identification_group_codes))
    db.commit()
    loaded = _load_scan_item_with_groups(db, item.id)
    if not loaded:
        raise HTTPException(status_code=500, detail='Item reload failed.')
    return _item_to_out(loaded)

@router.delete('/sessions/{session_id}/items/{item_id}', status_code=204)
def delete_item(session_id: int, item_id: int, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    session = db.scalar(select(ScanSession).where(ScanSession.id == session_id, ScanSession.user_id == user.id))
    if not session:
        raise HTTPException(status_code=404, detail='Session not found.')
    if session.status != 'pending':
        raise HTTPException(status_code=409, detail='Session already confirmed.')
    item = db.scalar(select(ScanItem).where(ScanItem.id == item_id, ScanItem.session_id == session_id))
    if not item:
        raise HTTPException(status_code=404, detail='Item not found.')
    db.delete(item)
    db.commit()
    return None

@router.post('/sessions/{session_id}/confirm', response_model=ScanSessionOut)
def confirm_session(session_id: int, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    session = db.scalar(select(ScanSession).where(ScanSession.id == session_id, ScanSession.user_id == user.id).options(*_SESSION_EAGER))
    if not session:
        raise HTTPException(status_code=404, detail='Session not found.')
    if session.status == 'confirmed':
        raise HTTPException(status_code=409, detail='Session already confirmed.')
    if not session.items:
        raise HTTPException(status_code=400, detail='No items to confirm.')
    for scan_item in session.items:
        pantry = PantryItem(user_id=user.id, session_id=session.id, name=scan_item.name, freshness=scan_item.freshness, quantity=_pantry_quantity_from_qty(scan_item.qty), unit=scan_item.unit, source='scan', expires_at=_estimate_expires(scan_item.name))
        db.add(pantry)
    for img in session.images:
        if not img.thumbnail:
            continue
        train_b64 = _training_thumbnail_b64(img.thumbnail)
        for scan_item in session.items:
            db.add(TrainingImage(user_id=user.id, session_id=session.id, product_name=scan_item.name.strip().lower(), freshness=scan_item.freshness, image_data=train_b64, mime='image/jpeg', verified=True))
    _update_freshness_refs(db, [{'name': item.name, 'freshness': item.freshness} for item in session.items])
    session.status = 'confirmed'
    db.commit()
    db.refresh(session)
    row = db.scalar(select(ScanSession).where(ScanSession.id == session.id).options(*_SESSION_EAGER))
    if not row:
        raise HTTPException(status_code=404, detail='Session not found.')
    return _session_to_out(row)

@router.post('/sessions/{session_id}/recipes')
def generate_recipes(session_id: int, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    session = db.scalar(select(ScanSession).where(ScanSession.id == session_id, ScanSession.user_id == user.id).options(selectinload(ScanSession.items)))
    if not session:
        raise HTTPException(status_code=404, detail='Session not found.')
    if session.status != 'confirmed':
        raise HTTPException(status_code=409, detail='Confirm the session first.')
    if not session.items:
        raise HTTPException(status_code=400, detail='No items in session.')
    if not _model_ready():
        raise HTTPException(status_code=503, detail='Model files not ready.')
    items_text = ', '.join((f'{i.name} ({i.freshness}, qty: {i.qty})' for i in session.items))
    user_id = user.id
    sess_id = session.id

    def _stream():
        yield (json.dumps({'status': 'generating_recipes'}) + '\n')
        prompt = f'{RECIPE_PROMPT}\n\nAvailable items: {items_text}'
        payload = {'model': LLAMA_MODEL, 'stream': True, 'max_tokens': 1024, 'temperature': 0.3, 'frequency_penalty': 0.6, 'messages': [{'role': 'user', 'content': prompt}]}
        resp, err = _request_llama_stream(payload)
        if err is not None:
            yield (json.dumps({'status': 'error', 'detail': str(err)}) + '\n')
            return
        if resp is None:
            yield (json.dumps({'status': 'error', 'detail': 'No response from model server.'}) + '\n')
            return
        if resp.status_code >= 400:
            yield (json.dumps({'status': 'error', 'detail': resp.text}) + '\n')
            return
        raw_text = None
        for token_count, final_text in _collect_streamed_with_progress(resp):
            if final_text is None:
                yield (json.dumps({'status': 'generating', 'tokens': token_count}) + '\n')
            else:
                raw_text = final_text
        if not raw_text:
            yield (json.dumps({'status': 'error', 'detail': 'Empty response from model.'}) + '\n')
            return
        try:
            parsed = _parse_ai_json(raw_text)
        except (json.JSONDecodeError, ValueError):
            yield (json.dumps({'status': 'error', 'detail': 'Invalid JSON', 'raw': raw_text}) + '\n')
            return
        raw_entries = _recipe_entries_from_parsed(parsed)
        recipe_list = [x for x in (_normalize_recipe_dict(r) for r in raw_entries) if x]
        if not recipe_list:
            yield (json.dumps({'status': 'error', 'detail': 'No recipes generated.'}) + '\n')
            return
        rdb = SessionLocal()
        try:
            db_recipes = []
            for r_data in recipe_list:
                recipe = SessionRecipe(session_id=sess_id, user_id=user_id, name=r_data['name'], uses_json=json.dumps(r_data['uses']), extra_json=json.dumps(r_data['extra']), steps_json=json.dumps(r_data['steps']), minutes=r_data['minutes'])
                rdb.add(recipe)
                db_recipes.append(recipe)
            rdb.commit()
            for rec in db_recipes:
                rdb.refresh(rec)
            result = {'status': 'done', 'recipes': [SessionRecipeOut(id=rec.id, session_id=rec.session_id, name=rec.name, uses=json.loads(rec.uses_json), extra=json.loads(rec.extra_json), steps=json.loads(rec.steps_json), minutes=rec.minutes, rating=rec.rating, created_at=cast(datetime, rec.created_at)).model_dump(mode='json') for rec in db_recipes]}
            yield (json.dumps(result) + '\n')
        except Exception as e:
            rdb.rollback()
            yield (json.dumps({'status': 'error', 'detail': f'DB error: {e}'}) + '\n')
        finally:
            rdb.close()
    return StreamingResponse(_stream(), media_type='application/x-ndjson')

@router.post('/sessions/{session_id}/groq-recipes', response_model=GroqRecipesBatchOut)
def generate_groq_recipes(session_id: int, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    if not groq_configured():
        raise HTTPException(status_code=503, detail='Groq is not configured. Set GROQ_API_KEY.')
    session = db.scalar(select(ScanSession).where(ScanSession.id == session_id, ScanSession.user_id == user.id).options(selectinload(ScanSession.items)))
    if not session:
        raise HTTPException(status_code=404, detail='Session not found.')
    if session.status != 'confirmed':
        raise HTTPException(status_code=409, detail='Confirm the session first.')
    if not session.items:
        raise HTTPException(status_code=400, detail='No items in session.')
    items_text = ', '.join((f'{i.name} (freshness {i.freshness}/10, qty: {i.qty})' for i in session.items))
    user_msg = GROQ_RECIPE_USER_PROMPT.replace('{items}', items_text)
    try:
        raw_text = groq_chat_json(GROQ_SYSTEM_PROMPT, user_msg)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f'Groq request failed: {e}') from e
    try:
        parsed = _parse_ai_json(raw_text)
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=502, detail=f'Invalid JSON from Groq: {e}') from e
    raw_entries = _recipe_entries_from_parsed(parsed)
    recipe_list = [x for x in (_normalize_recipe_dict(r) for r in raw_entries) if x]
    if not recipe_list:
        raise HTTPException(status_code=502, detail='No usable recipes in Groq response (expected a list with name/uses/steps).')
    db_recipes = []
    for r_data in recipe_list:
        recipe = SessionRecipe(session_id=session.id, user_id=user.id, name=r_data['name'], uses_json=json.dumps(r_data['uses']), extra_json=json.dumps(r_data['extra']), steps_json=json.dumps(r_data['steps']), minutes=r_data['minutes'])
        db.add(recipe)
        db_recipes.append(recipe)
    db.commit()
    for rec in db_recipes:
        db.refresh(rec)
    return GroqRecipesBatchOut(recipes=[SessionRecipeOut(id=rec.id, session_id=rec.session_id, name=rec.name, uses=json.loads(rec.uses_json), extra=json.loads(rec.extra_json), steps=json.loads(rec.steps_json), minutes=rec.minutes, rating=rec.rating, created_at=cast(datetime, rec.created_at)) for rec in db_recipes])

@router.patch('/recipes/{recipe_id}', response_model=SessionRecipeOut)
def rate_recipe(recipe_id: int, body: RateRequest, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    recipe = db.scalar(select(SessionRecipe).where(SessionRecipe.id == recipe_id, SessionRecipe.user_id == user.id))
    if not recipe:
        raise HTTPException(status_code=404, detail='Recipe not found.')
    recipe.rating = body.rating
    db.commit()
    db.refresh(recipe)
    return SessionRecipeOut(id=recipe.id, session_id=recipe.session_id, name=recipe.name, uses=json.loads(recipe.uses_json), extra=json.loads(recipe.extra_json), steps=json.loads(recipe.steps_json), minutes=recipe.minutes, rating=recipe.rating, created_at=cast(datetime, recipe.created_at))

@router.get('/sessions/{session_id}/images/{image_id}')
def get_image(session_id: int, image_id: int, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    session = db.scalar(select(ScanSession).where(ScanSession.id == session_id, ScanSession.user_id == user.id))
    if not session:
        raise HTTPException(status_code=404, detail='Session not found.')
    image = db.scalar(select(ScanImage).where(ScanImage.id == image_id, ScanImage.session_id == session_id))
    if not image:
        raise HTTPException(status_code=404, detail='Image not found.')
    return {'image': image.thumbnail, 'mime': image.mime}

@router.get('/training/stats', response_model=TrainingStatsOut)
def training_stats(user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    rows = db.execute(select(TrainingImage.product_name, func.count(TrainingImage.id), func.avg(TrainingImage.freshness), func.min(TrainingImage.freshness), func.max(TrainingImage.freshness)).where(TrainingImage.user_id == user.id).group_by(TrainingImage.product_name).order_by(func.count(TrainingImage.id).desc())).all()
    products = [{'name': name, 'images': count, 'avg_freshness': round(avg, 1) if avg else 0, 'min_freshness': mn, 'max_freshness': mx} for name, count, avg, mn, mx in rows]
    return TrainingStatsOut(total_images=sum((p['images'] for p in products)), unique_products=len(products), products=products)

@router.get('/training/images', response_model=list[TrainingImageOut])
def list_training_images(product: str | None=Query(None), limit: int=Query(50, ge=1, le=200), offset: int=Query(0, ge=0), user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    stmt = select(TrainingImage).where(TrainingImage.user_id == user.id)
    if product:
        stmt = stmt.where(TrainingImage.product_name == product.strip().lower())
    stmt = stmt.order_by(TrainingImage.created_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(stmt).all())

@router.get('/training/images/{image_id}')
def get_training_image(image_id: int, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    img = db.scalar(select(TrainingImage).where(TrainingImage.id == image_id, TrainingImage.user_id == user.id))
    if not img:
        raise HTTPException(status_code=404, detail='Training image not found.')
    return {'image': img.image_data, 'mime': img.mime, 'product': img.product_name, 'freshness': img.freshness}