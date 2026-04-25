import base64
import io
import json
import re
from datetime import datetime, timedelta, timezone
from typing import List, cast
import requests
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload
from config import AI_KILLSWITCH_TOKEN, ENABLE_AI, FRESHNESS_DEFAULT, FRESHNESS_MAX, FRESHNESS_MIN, GROQ_RECIPE_USER_PROMPT, GROQ_SYSTEM_PROMPT, SCAN_PROMPT, VISION_MAX_TOKENS
from identification_data import KNOWN_IDENTIFICATION_CODES
from db import SessionLocal, get_db
from groq_client import groq_chat_json, groq_chat_vision_json, groq_configured
from models import FreshnessRef, Group, GroupMember, IngredientIdentificationGroup, PantryItem, Recipe, ScanImage, ScanItem, ScanItemIdentification, ScanSession, SessionRecipe, User
from schemas import AddItemRequest, CombinedGroupItem, CombinedGroupSuggestionOut, EditItemRequest, GroqRecipesBatchOut, IdentificationGroupOut, RateRequest, RecipeOut, ScanImageOut, ScanItemOut, ScanSessionOut, SessionRecipeOut
from security import get_current_user, get_current_user_id_for_stream

# Real-time runtime toggle ("killswitch") for the /ai API.
# It blocks all /ai endpoints except these two:
#   - GET  /ai/runtime/status
#   - POST /ai/runtime/toggle
_runtime_ai_enabled: bool = bool(ENABLE_AI)


def _ai_runtime_guard(request: Request) -> None:
    path = request.url.path
    if path.endswith('/runtime/status') or path.endswith('/runtime/toggle'):
        return
    if not _runtime_ai_enabled:
        raise HTTPException(status_code=503, detail='AI is OFF (runtime toggle).')


router = APIRouter(prefix='/ai', tags=['ai'], dependencies=[Depends(_ai_runtime_guard)])


class AiRuntimeToggleIn(BaseModel):
    enabled: bool


@router.get('/runtime/status')
def ai_runtime_status():
    return {'enabled': _runtime_ai_enabled, 'model_ready': groq_configured() if ENABLE_AI else False}


@router.post('/runtime/toggle')
def ai_runtime_toggle(body: AiRuntimeToggleIn, x_ai_toggle_token: str | None = Header(default=None, alias='X-AI-Toggle-Token')):
    global _runtime_ai_enabled
    if not AI_KILLSWITCH_TOKEN:
        raise HTTPException(status_code=500, detail='AI_KILLSWITCH_TOKEN is not configured.')
    if x_ai_toggle_token != AI_KILLSWITCH_TOKEN:
        raise HTTPException(status_code=403, detail='Invalid X-AI-Toggle-Token.')
    _runtime_ai_enabled = bool(body.enabled)
    return {'enabled': _runtime_ai_enabled}

THUMB_MAX = 1080
_SESSION_EAGER = (selectinload(ScanSession.images), selectinload(ScanSession.items).selectinload(ScanItem.identification_links).selectinload(ScanItemIdentification.group), selectinload(ScanSession.recipes))


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

def _model_ready() -> bool:
    return groq_configured()

def _estimate_expires(name: str) -> datetime | None:
    lowered = name.lower()
    for key, days in _EXPIRY_HINTS_DAYS.items():
        if key in lowered:
            return datetime.now(timezone.utc) + timedelta(days=days)
    return None

def _freshness_norm(score: float) -> float:
    span = FRESHNESS_MAX - FRESHNESS_MIN
    if span <= 0:
        return 1.0
    return (score - FRESHNESS_MIN) / span

def _freshness_alert(score: int) -> str | None:
    if score <= FRESHNESS_MIN:
        return 'SPOILED — do NOT consume, discard immediately'
    n = _freshness_norm(score)
    if n <= 0.25:
        return 'WARNING — about to expire, use today or discard'
    if n < 1.0:
        return 'Use soon — quality is declining'
    return None

def _freshness_label(score: float) -> str:
    score = max(float(FRESHNESS_MIN), min(float(FRESHNESS_MAX), float(score)))
    n = _freshness_norm(score)
    if n >= 0.8:
        return 'fresh'
    if n >= 0.55:
        return 'good'
    if n >= 0.35:
        return 'use-soon'
    if n >= 0.15:
        return 'expiring'
    return 'spoiled'

def _build_freshness_context(db: Session, user_id: int) -> str:
    refs = db.scalars(select(FreshnessRef).order_by(FreshnessRef.observations.desc()).limit(30)).all()
    if not refs:
        return ''
    lines = []
    for r in refs:
        label = _freshness_label(r.avg_freshness)
        lines.append(f'  {r.product_name}: avg {r.avg_freshness:.1f}/{FRESHNESS_MAX} ({label}), seen {r.observations}x, last scored {r.last_freshness}/{FRESHNESS_MAX}')
    return '\n\nYou have learned from previous scans. Use this data to improve accuracy:\n' + '\n'.join(lines) + "\nBe more precise for products you've seen many times.\n"

def _clamp_freshness(val) -> int:
    try:
        v = int(val)
    except (TypeError, ValueError):
        return FRESHNESS_DEFAULT
    return max(FRESHNESS_MIN, min(FRESHNESS_MAX, v))

def _update_freshness_refs(db: Session, items: list[dict]):
    for item in items:
        name = item.get('name', '').strip().lower()
        freshness = _clamp_freshness(item.get('freshness', FRESHNESS_DEFAULT))
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

def _session_recipe_to_out(r: SessionRecipe) -> SessionRecipeOut:
    return SessionRecipeOut(id=r.id, session_id=r.session_id, name=r.name, uses=json.loads(r.uses_json), extra=json.loads(r.extra_json), steps=json.loads(r.steps_json), minutes=r.minutes, rating=r.rating, favorited=bool(r.favorited), created_at=cast(datetime, r.created_at))


def _session_to_out(session: ScanSession) -> ScanSessionOut:
    return ScanSessionOut(id=session.id, status=session.status, images=[ScanImageOut(id=img.id, mime=img.mime) for img in session.images], items=[_item_to_out(item) for item in session.items], recipes=[_session_recipe_to_out(r) for r in session.recipes], tip=session.tip, created_at=cast(datetime, session.created_at))
MAX_SCAN_UPLOADS = 50

@router.post('/sessions')
async def create_session(files: List[UploadFile]=File(...), user_id: int=Depends(get_current_user_id_for_stream)):
    if not _model_ready():
        raise HTTPException(status_code=503, detail='Vision model not configured. Set GROQ_API_KEY.')
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

    def _stream():
        yield (json.dumps({'status': 'processing', 'images': len(image_data)}) + '\n')
        thumbnails: list[tuple[str, str]] = []
        vision_images: list[tuple[str, str]] = []
        ref_db = SessionLocal()
        try:
            freshness_ctx = _build_freshness_context(ref_db, user_id)
        finally:
            ref_db.close()
        prompt_text = SCAN_PROMPT
        if freshness_ctx:
            prompt_text += freshness_ctx
        n_img = len(image_data)
        for idx, (raw_bytes, mime) in enumerate(image_data):
            try:
                thumb = _make_thumbnail(raw_bytes, mime)
                thumbnails.append((thumb, mime))
            except Exception:
                thumbnails.append(('', mime))
            b64 = base64.b64encode(raw_bytes).decode('ascii')
            vision_images.append((b64, mime))
            yield (json.dumps({'status': 'generating', 'phase': 'image', 'index': idx + 1, 'total': n_img}) + '\n')
        yield (json.dumps({'status': 'generating', 'phase': 'groq_vision'}) + '\n')
        try:
            raw_text = groq_chat_vision_json(
                system=prompt_text,
                user_text='Scan these images and return the JSON described in the system prompt.',
                images=vision_images,
                max_tokens=VISION_MAX_TOKENS,
                temperature=0.2,
            )
        except RuntimeError as e:
            yield (json.dumps({'status': 'error', 'detail': str(e)}) + '\n')
            return
        except requests.RequestException as e:
            yield (json.dumps({'status': 'error', 'detail': f'Groq request failed: {e}'}) + '\n')
            return
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
        yield (json.dumps({'status': 'generating', 'phase': 'saving'}) + '\n')
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
                item = ScanItem(session_id=session.id, name=name, freshness=_clamp_freshness(item_data.get('freshness', FRESHNESS_DEFAULT)), qty=str(item_data.get('qty', '')), unit=item_data.get('unit'), confidence=item_data.get('confidence'), source='ai')
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
    _update_freshness_refs(db, [{'name': item.name, 'freshness': item.freshness} for item in session.items])
    session.status = 'confirmed'
    db.commit()
    db.refresh(session)
    row = db.scalar(select(ScanSession).where(ScanSession.id == session.id).options(*_SESSION_EAGER))
    if not row:
        raise HTTPException(status_code=404, detail='Session not found.')
    return _session_to_out(row)

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
    items_text = ', '.join((f'{i.name} (freshness {i.freshness}/{FRESHNESS_MAX}, qty: {i.qty})' for i in session.items))
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
    return GroqRecipesBatchOut(recipes=[_session_recipe_to_out(rec) for rec in db_recipes])

@router.patch('/recipes/{recipe_id}', response_model=SessionRecipeOut)
def rate_recipe(recipe_id: int, body: RateRequest, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    recipe = db.scalar(select(SessionRecipe).where(SessionRecipe.id == recipe_id, SessionRecipe.user_id == user.id))
    if not recipe:
        raise HTTPException(status_code=404, detail='Recipe not found.')
    recipe.rating = body.rating
    db.commit()
    db.refresh(recipe)
    return _session_recipe_to_out(recipe)

@router.get('/sessions/{session_id}/images/{image_id}')
def get_image(session_id: int, image_id: int, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    session = db.scalar(select(ScanSession).where(ScanSession.id == session_id, ScanSession.user_id == user.id))
    if not session:
        raise HTTPException(status_code=404, detail='Session not found.')
    image = db.scalar(select(ScanImage).where(ScanImage.id == image_id, ScanImage.session_id == session_id))
    if not image:
        raise HTTPException(status_code=404, detail='Image not found.')
    return {'image': image.thumbnail, 'mime': image.mime}

@router.post('/recipes/{recipe_id}/favorite', response_model=SessionRecipeOut)
def favorite_session_recipe(recipe_id: int, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    recipe = db.scalar(select(SessionRecipe).where(SessionRecipe.id == recipe_id, SessionRecipe.user_id == user.id))
    if not recipe:
        raise HTTPException(status_code=404, detail='Recipe not found.')
    recipe.favorited = True
    db.commit()
    db.refresh(recipe)
    return _session_recipe_to_out(recipe)


@router.delete('/recipes/{recipe_id}/favorite', response_model=SessionRecipeOut)
def unfavorite_session_recipe(recipe_id: int, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    recipe = db.scalar(select(SessionRecipe).where(SessionRecipe.id == recipe_id, SessionRecipe.user_id == user.id))
    if not recipe:
        raise HTTPException(status_code=404, detail='Recipe not found.')
    recipe.favorited = False
    db.commit()
    db.refresh(recipe)
    return _session_recipe_to_out(recipe)


@router.get('/recipes/favorites', response_model=list[SessionRecipeOut])
def list_favorite_session_recipes(limit: int=Query(50, ge=1, le=200), offset: int=Query(0, ge=0), user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    rows = db.scalars(select(SessionRecipe).where(SessionRecipe.user_id == user.id, SessionRecipe.favorited == True).order_by(SessionRecipe.created_at.desc()).offset(offset).limit(limit)).all()
    return [_session_recipe_to_out(r) for r in rows]


def _collect_user_group_pantry(db: Session, user_id: int) -> tuple[list[int], dict[tuple[str, str | None], dict]]:
    group_ids = list(db.scalars(select(GroupMember.group_id).where(GroupMember.user_id == user_id)).all())
    if not group_ids:
        return [], {}
    member_ids = list(db.scalars(select(GroupMember.user_id).where(GroupMember.group_id.in_(group_ids))).all())
    if not member_ids:
        return group_ids, {}
    pantry_rows = list(db.scalars(select(PantryItem).where(PantryItem.user_id.in_(member_ids)).order_by(PantryItem.created_at.desc()).limit(500)).all())
    user_to_groups: dict[int, list[int]] = {}
    member_links = db.execute(select(GroupMember.user_id, GroupMember.group_id).where(GroupMember.group_id.in_(group_ids))).all()
    for uid, gid in member_links:
        user_to_groups.setdefault(uid, []).append(gid)
    combined: dict[tuple[str, str | None], dict] = {}
    for row in pantry_rows:
        name = (row.name or '').strip().lower()
        if not name:
            continue
        key = (name, row.unit)
        slot = combined.setdefault(key, {'name': name, 'unit': row.unit, 'quantity': 0, 'group_ids': set()})
        slot['quantity'] += int(row.quantity or 1)
        for gid in user_to_groups.get(row.user_id, []):
            slot['group_ids'].add(gid)
    return group_ids, combined


@router.get('/groups/combined-pantry', response_model=CombinedGroupSuggestionOut)
def combined_group_pantry(user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    group_ids, combined = _collect_user_group_pantry(db, user.id)
    items = [CombinedGroupItem(name=v['name'], unit=v['unit'], quantity=v['quantity'], group_ids=sorted(v['group_ids'])) for v in combined.values()]
    items.sort(key=lambda i: (-i.quantity, i.name))
    return CombinedGroupSuggestionOut(group_ids=sorted(group_ids), items=items, recipes=[])


@router.post('/groups/combined-meal', response_model=CombinedGroupSuggestionOut)
def combined_group_meal_suggestions(count: int=Query(3, ge=1, le=6), user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    if not groq_configured():
        raise HTTPException(status_code=503, detail='Groq is not configured. Set GROQ_API_KEY.')
    group_ids, combined = _collect_user_group_pantry(db, user.id)
    items = [CombinedGroupItem(name=v['name'], unit=v['unit'], quantity=v['quantity'], group_ids=sorted(v['group_ids'])) for v in combined.values()]
    items.sort(key=lambda i: (-i.quantity, i.name))
    if not items:
        raise HTTPException(status_code=400, detail='No pantry items found across your groups.')
    items_text = ', '.join(f'{i.name} x{i.quantity}' if i.quantity > 1 else i.name for i in items[:60])
    system = (
        'You are a meal planner that combines pantry inventories from multiple households. '
        'Use ONLY ingredients the user lists; never add anything new. Reply with strict JSON only.'
    )
    user_msg = (
        f'These are the COMBINED pantry items from all the user\'s groups (ingredient + total quantity available). '
        f'Suggest {count} creative shared meals that combine items from across the groups, prioritising perishable use. '
        f'Each recipe must only use names from this list. Return strict JSON: '
        f'{{"recipes":[{{"title":string,"description":string|null,"ingredients":[string],"steps":[string],"minutes":int|null}}]}}.\n'
        f'Inventory: {items_text}'
    )
    try:
        raw = groq_chat_json(system, user_msg, temperature=0.3, max_tokens=1500)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f'Groq request failed: {e}') from e
    try:
        parsed = _parse_ai_json(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=502, detail=f'Invalid JSON from Groq: {e}') from e
    raw_list = parsed.get('recipes') if isinstance(parsed, dict) else parsed
    if not isinstance(raw_list, list):
        raw_list = []
    recipes_out: list[RecipeOut] = []
    for entry in raw_list:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get('title') or entry.get('name') or '').strip()
        if not title:
            continue
        ingredients = [str(x).strip() for x in (entry.get('ingredients') or entry.get('uses') or []) if str(x).strip()][:30]
        steps = [str(x).strip() for x in (entry.get('steps') or []) if str(x).strip()][:20]
        desc = entry.get('description')
        minutes = entry.get('minutes')
        try:
            minutes = int(minutes) if minutes is not None else None
        except (TypeError, ValueError):
            minutes = None
        rec = Recipe(title=title[:200], description=str(desc)[:2000] if isinstance(desc, str) else None, ingredients_json=json.dumps(ingredients), steps_json=json.dumps(steps))
        db.add(rec)
        db.flush()
        recipes_out.append(RecipeOut(id=rec.id, title=rec.title, description=rec.description, ingredients=ingredients, steps=steps, starred=False))
    db.commit()
    return CombinedGroupSuggestionOut(group_ids=sorted(group_ids), items=items, recipes=recipes_out)
