from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import get_db
from models import PantryItem, User
from schemas import PantryItemCreateRequest, PantryItemOut
from security import get_current_user

router = APIRouter(prefix="/pantry", tags=["pantry"])


@router.get("", response_model=list[PantryItemOut])
def list_items(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = select(PantryItem).where(PantryItem.user_id == current_user.id).order_by(PantryItem.created_at.desc())
    return list(db.scalars(q).all())


@router.post("", response_model=PantryItemOut, status_code=status.HTTP_201_CREATED)
def add_item(
    payload: PantryItemCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = PantryItem(
        user_id=current_user.id,
        name=payload.name.strip(),
        quantity=payload.quantity,
        unit=payload.unit.strip() if payload.unit else None,
        expires_at=payload.expires_at,
        source="manual",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.get(PantryItem, item_id)
    if not item or item.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Item not found.")
    db.delete(item)
    db.commit()
    return None
