from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


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


class FoodItem(BaseModel):
    name: str
    freshness: str
    qty: str


class ScanRecipeOut(BaseModel):
    id: int
    scan_id: int
    name: str
    uses: list[str]
    extra: list[str]
    steps: list[str]
    minutes: Optional[int] = None
    rating: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ScanOut(BaseModel):
    id: int
    items: list[FoodItem]
    recipes: list[ScanRecipeOut]
    tip: Optional[str] = None
    has_image: bool
    created_at: datetime

    class Config:
        from_attributes = True


class RateRequest(BaseModel):
    rating: int = Field(ge=1, le=5)


class ScanItemOut(BaseModel):
    name: str
    quantity: float | None = None
    unit: str | None = None
    confidence: float | None = None
    expires_at: datetime | None = None


class ImageScanResponse(BaseModel):
    items: list[ScanItemOut] = []
    raw: str | None = None


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
    quantity: int = Field(default=1, ge=1, le=10_000)
    unit: str | None = Field(default=None, max_length=32)
    expires_at: datetime | None = None


class PantryItemOut(BaseModel):
    id: int
    name: str
    quantity: int
    unit: str | None
    source: str
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
