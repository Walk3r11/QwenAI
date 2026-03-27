from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from config import FRESHNESS_DEFAULT, FRESHNESS_MAX, FRESHNESS_MIN

class SignupRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str

    class Config:
        from_attributes = True

class AuthResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserOut

class IdentificationGroupOut(BaseModel):
    id: int
    code: str
    label: str

    class Config:
        from_attributes = True

class ScanItemOut(BaseModel):
    id: int
    name: str
    freshness: int = FRESHNESS_DEFAULT
    qty: str = ''
    unit: str | None = None
    confidence: float | None = None
    source: str = 'ai'
    alert: str | None = None
    identification_groups: list[IdentificationGroupOut] = []

    class Config:
        from_attributes = True

class ScanImageOut(BaseModel):
    id: int
    mime: str
    has_thumbnail: bool = True

    class Config:
        from_attributes = True

class SessionRecipeOut(BaseModel):
    id: int
    session_id: int
    name: str
    uses: list[str]
    extra: list[str]
    steps: list[str]
    minutes: int | None = None
    rating: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True

class GroqRecipesBatchOut(BaseModel):
    status: str = 'done'
    recipes: list[SessionRecipeOut]

class ScanSessionOut(BaseModel):
    id: int
    status: str
    images: list[ScanImageOut] = []
    items: list[ScanItemOut] = []
    recipes: list[SessionRecipeOut] = []
    tip: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True

class AddItemRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    freshness: int = Field(default=FRESHNESS_DEFAULT, ge=FRESHNESS_MIN, le=FRESHNESS_MAX)
    qty: str = Field(default='1', max_length=50)
    unit: str | None = Field(default=None, max_length=32)
    identification_group_codes: list[str] = Field(default_factory=list, max_length=24)

class EditItemRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    freshness: int | None = Field(default=None, ge=FRESHNESS_MIN, le=FRESHNESS_MAX)
    qty: str | None = Field(default=None, max_length=50)
    unit: str | None = None
    identification_group_codes: list[str] | None = None

class RateRequest(BaseModel):
    rating: int = Field(ge=1, le=5)

class TrainingImageOut(BaseModel):
    id: int
    product_name: str
    freshness: int
    mime: str
    verified: bool
    created_at: datetime

    class Config:
        from_attributes = True

class TrainingStatsOut(BaseModel):
    total_images: int
    unique_products: int
    products: list[dict]

class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)

class GroupOut(BaseModel):
    id: int
    name: str
    created_by_user_id: int
    created_at: datetime

    class Config:
        from_attributes = True

class GroupJoinCodeOut(BaseModel):
    code: str
    expires_at: datetime | None
    max_uses: int | None
    uses: int
    active: bool

    class Config:
        from_attributes = True

class GroupMemberOut(BaseModel):
    user: UserOut
    role: str
    joined_at: datetime

    class Config:
        from_attributes = True

class GroupDetailOut(GroupOut):
    members: list[GroupMemberOut] = []

class JoinGroupRequest(BaseModel):
    code: str = Field(min_length=4, max_length=32)

class PantryItemCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    quantity: int = Field(default=1, ge=1, le=10000)
    unit: str | None = Field(default=None, max_length=32)
    expires_at: datetime | None = None

class PantryItemOut(BaseModel):
    id: int
    name: str
    freshness: int = FRESHNESS_DEFAULT
    quantity: int
    unit: str | None
    source: str
    session_id: int | None = None
    image_id: str | None
    created_at: datetime
    expires_at: datetime | None

    class Config:
        from_attributes = True

class RecipeOut(BaseModel):
    id: int
    title: str
    description: str | None
    ingredients: list[str] = []
    steps: list[str] = []
    starred: bool = False

class RecipeSuggestRequest(BaseModel):
    items: list[str] = Field(default_factory=list, max_length=50)

class ShareMealRequest(BaseModel):
    group_id: int
    note: str | None = Field(default=None, max_length=500)
    items: list[PantryItemCreateRequest] = Field(default_factory=list, max_length=100)

class SharePostOut(BaseModel):
    id: int
    group_id: int
    user_id: int
    note: str | None
    created_at: datetime
    items: list[PantryItemOut] = []