from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from typing import cast
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from db import get_db
from models import GroupMember, SharePost, SharePostItem, User
from schemas import PantryItemOut, ShareMealRequest, SharePostOut
from security import get_current_user
router = APIRouter(prefix='/share', tags=['share'])

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