from __future__ import annotations
import json
from collections import defaultdict
from datetime import datetime
from typing import cast
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from db import get_db
from models import GroupMember, Recipe, SessionRecipe, SharePost, SharePostItem, SharedRecipe, User
from schemas import PantryItemOut, ShareMealRequest, SharePostOut, ShareRecipeRequest, SharedRecipeOut
from security import get_current_user
router = APIRouter(prefix='/share', tags=['share'])


def _shared_recipe_to_out(post: SharedRecipe) -> SharedRecipeOut:
    try:
        ings = json.loads(post.ingredients_json or '[]')
    except Exception:
        ings = []
    try:
        steps = json.loads(post.steps_json or '[]')
    except Exception:
        steps = []
    return SharedRecipeOut(
        id=post.id,
        group_id=post.group_id,
        user_id=post.user_id,
        title=post.title,
        description=post.description,
        ingredients=ings if isinstance(ings, list) else [],
        steps=steps if isinstance(steps, list) else [],
        minutes=post.minutes,
        note=post.note,
        created_at=cast(datetime, post.created_at),
    )

def _ensure_member(db: Session, group_id: int, user_id: int):
    membership = db.scalar(select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id))
    if not membership:
        raise HTTPException(status_code=403, detail='Not a member of this group.')

@router.post('/meal', response_model=SharePostOut, status_code=status.HTTP_201_CREATED)
def share_meal(payload: ShareMealRequest, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    _ensure_member(db, payload.group_id, current_user.id)
    post = SharePost(group_id=payload.group_id, user_id=current_user.id, note=payload.note)
    db.add(post)
    db.flush()
    for item in payload.items:
        db.add(SharePostItem(share_post_id=post.id, name=item.name.strip(), quantity=item.quantity, unit=item.unit.strip() if item.unit else None))
    db.commit()
    db.refresh(post)
    created = cast(datetime, post.created_at)
    return SharePostOut(id=post.id, group_id=post.group_id, user_id=post.user_id, note=post.note, created_at=created, items=[PantryItemOut(id=0, name=i.name, quantity=i.quantity, unit=i.unit, source='shared', image_id=None, created_at=created, expires_at=None) for i in post.items])

@router.get('/group/{group_id}')
def group_feed(group_id: int, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    _ensure_member(db, group_id, current_user.id)
    posts = list(db.scalars(select(SharePost).where(SharePost.group_id == group_id).options(selectinload(SharePost.items)).order_by(SharePost.created_at.desc()).limit(50)).all())
    combined: dict[tuple[str, str | None], int] = defaultdict(int)
    for p in posts:
        for i in p.items:
            combined[i.name.lower().strip(), i.unit] += int(i.quantity or 0)
    combined_items = [{'name': name, 'unit': unit, 'quantity': qty} for (name, unit), qty in sorted(combined.items(), key=lambda kv: (-kv[1], kv[0][0])) if qty > 0]
    return {'group_id': group_id, 'posts': [{'id': p.id, 'user_id': p.user_id, 'note': p.note, 'created_at': p.created_at, 'items': [{'name': i.name, 'quantity': i.quantity, 'unit': i.unit} for i in p.items]} for p in posts], 'combined_items': combined_items}


@router.post('/recipe', response_model=SharedRecipeOut, status_code=status.HTTP_201_CREATED)
def share_recipe(payload: ShareRecipeRequest, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    _ensure_member(db, payload.group_id, current_user.id)
    title = payload.title.strip()
    description = payload.description
    ingredients = [i.strip() for i in payload.ingredients if i.strip()]
    steps = [s.strip() for s in payload.steps if s.strip()]
    minutes = payload.minutes
    if payload.recipe_id is not None:
        rec = db.get(Recipe, payload.recipe_id)
        if not rec:
            raise HTTPException(status_code=404, detail='Recipe not found.')
        title = title or rec.title
        description = description if description is not None else rec.description
        if not ingredients:
            try:
                src_ings = json.loads(rec.ingredients_json or '[]')
                if isinstance(src_ings, list):
                    ingredients = [str(x).strip() for x in src_ings if str(x).strip()]
            except Exception:
                pass
        if not steps:
            try:
                src_steps = json.loads(rec.steps_json or '[]')
                if isinstance(src_steps, list):
                    steps = [str(x).strip() for x in src_steps if str(x).strip()]
            except Exception:
                pass
    if payload.session_recipe_id is not None:
        sr = db.scalar(select(SessionRecipe).where(SessionRecipe.id == payload.session_recipe_id, SessionRecipe.user_id == current_user.id))
        if not sr:
            raise HTTPException(status_code=404, detail='Session recipe not found.')
        title = title or sr.name
        if not ingredients:
            try:
                ingredients = json.loads(sr.uses_json or '[]')
            except Exception:
                ingredients = []
        if not steps:
            try:
                steps = json.loads(sr.steps_json or '[]')
            except Exception:
                steps = []
        minutes = minutes if minutes is not None else sr.minutes
    if not title:
        raise HTTPException(status_code=400, detail='Recipe title is required.')
    post = SharedRecipe(
        group_id=payload.group_id,
        user_id=current_user.id,
        title=title[:200],
        description=description,
        ingredients_json=json.dumps(ingredients),
        steps_json=json.dumps(steps),
        minutes=minutes,
        note=payload.note,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return _shared_recipe_to_out(post)


@router.get('/group/{group_id}/recipes', response_model=list[SharedRecipeOut])
def list_shared_recipes(group_id: int, limit: int=Query(50, ge=1, le=200), offset: int=Query(0, ge=0), db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    _ensure_member(db, group_id, current_user.id)
    posts = list(db.scalars(
        select(SharedRecipe)
        .where(SharedRecipe.group_id == group_id)
        .order_by(SharedRecipe.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all())
    return [_shared_recipe_to_out(p) for p in posts]


@router.delete('/recipe/{shared_recipe_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_shared_recipe(shared_recipe_id: int, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    post = db.get(SharedRecipe, shared_recipe_id)
    if not post:
        raise HTTPException(status_code=404, detail='Shared recipe not found.')
    if post.user_id != current_user.id:
        raise HTTPException(status_code=403, detail='Only the author can delete this shared recipe.')
    db.delete(post)
    db.commit()
    return None