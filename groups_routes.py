from __future__ import annotations
import secrets
from datetime import datetime, timezone
from typing import cast
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from db import get_db
from models import Group, GroupJoinCode, GroupMember, User
from schemas import GroupCreateRequest, GroupDetailOut, GroupJoinCodeOut, GroupOut, JoinGroupRequest
from security import get_current_user
router = APIRouter(prefix='/groups', tags=['groups'])

def _as_utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _new_join_code() -> str:
    return secrets.token_urlsafe(6).replace('-', '').replace('_', '')[:10]

def _ensure_member(db: Session, group_id: int, user_id: int) -> GroupMember:
    membership = db.scalar(select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id))
    if not membership:
        raise HTTPException(status_code=403, detail='Not a member of this group.')
    return membership

@router.post('', response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupCreateRequest, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    group = Group(name=payload.name.strip(), created_by_user_id=current_user.id)
    db.add(group)
    db.flush()
    db.add(GroupMember(group_id=group.id, user_id=current_user.id, role='owner'))
    for _ in range(5):
        code = _new_join_code()
        db.add(GroupJoinCode(group_id=group.id, code=code, created_by_user_id=current_user.id))
        try:
            db.commit()
            break
        except Exception:
            db.rollback()
    else:
        raise HTTPException(status_code=500, detail='Failed to create join code.')
    db.refresh(group)
    return group

@router.delete('/{group_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_group(group_id: int, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    membership = _ensure_member(db, group_id, current_user.id)
    if membership.role != 'owner':
        raise HTTPException(status_code=403, detail='Only owners can delete the group.')
    group = db.get(Group, group_id)
    if group:
        db.delete(group)
        db.commit()
    return None

@router.post('/{group_id}/leave', status_code=status.HTTP_204_NO_CONTENT)
def leave_group(group_id: int, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    membership = _ensure_member(db, group_id, current_user.id)
    if membership.role == 'owner':
        raise HTTPException(status_code=400, detail='Owners cannot leave. Delete the group instead.')
    db.delete(membership)
    db.commit()
    return None

@router.get('', response_model=list[GroupOut])
def list_my_groups(db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    q = select(Group).join(GroupMember, GroupMember.group_id == Group.id).where(GroupMember.user_id == current_user.id).order_by(Group.created_at.desc())
    return list(db.scalars(q).all())

@router.get('/{group_id}', response_model=GroupDetailOut)
def get_group(group_id: int, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    _ensure_member(db, group_id, current_user.id)
    group = db.scalar(select(Group).where(Group.id == group_id).options(selectinload(Group.members).selectinload(GroupMember.user)))
    if not group:
        raise HTTPException(status_code=404, detail='Group not found.')
    return group

@router.post('/join', response_model=GroupOut)
def join_group(payload: JoinGroupRequest, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    code = db.scalar(select(GroupJoinCode).where(GroupJoinCode.code == payload.code.strip()))
    if not code or not code.active:
        raise HTTPException(status_code=404, detail='Invalid join code.')
    if code.expires_at is not None and _as_utc_aware(cast(datetime, code.expires_at)) < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail='Join code expired.')
    if code.max_uses is not None and code.uses >= code.max_uses:
        raise HTTPException(status_code=410, detail='Join code max uses reached.')
    existing = db.scalar(select(GroupMember).where(GroupMember.group_id == code.group_id, GroupMember.user_id == current_user.id))
    if not existing:
        db.add(GroupMember(group_id=code.group_id, user_id=current_user.id, role='member'))
        code.uses += 1
        db.commit()
    group = db.get(Group, code.group_id)
    if not group:
        raise HTTPException(status_code=404, detail='Group not found.')
    return group

@router.get('/{group_id}/codes', response_model=list[GroupJoinCodeOut])
def list_join_codes(group_id: int, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    membership = _ensure_member(db, group_id, current_user.id)
    if membership.role != 'owner':
        raise HTTPException(status_code=403, detail='Only owners can view join codes.')
    q = select(GroupJoinCode).where(GroupJoinCode.group_id == group_id).order_by(GroupJoinCode.created_at.desc())
    return list(db.scalars(q).all())

@router.post('/{group_id}/codes', response_model=GroupJoinCodeOut, status_code=status.HTTP_201_CREATED)
def create_join_code(group_id: int, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    membership = _ensure_member(db, group_id, current_user.id)
    if membership.role != 'owner':
        raise HTTPException(status_code=403, detail='Only owners can create join codes.')
    for _ in range(5):
        code = _new_join_code()
        obj = GroupJoinCode(group_id=group_id, code=code, created_by_user_id=current_user.id)
        db.add(obj)
        try:
            db.commit()
            db.refresh(obj)
            return obj
        except Exception:
            db.rollback()
    raise HTTPException(status_code=500, detail='Failed to create join code.')