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


class RecipeOut(BaseModel):
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
    recipes: list[RecipeOut]
    tip: Optional[str] = None
    has_image: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AnalyzeResponse(BaseModel):
    scan_id: int
    items: list[FoodItem]
    recipes: list[RecipeOut]
    tip: Optional[str] = None


class RateRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
