from __future__ import annotations
from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from config import FRESHNESS_DEFAULT
from db import Base

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    verification_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    scan_sessions: Mapped[list[ScanSession]] = relationship(back_populates='user', cascade='all, delete-orphan')
    memberships: Mapped[list[GroupMember]] = relationship(back_populates='user', cascade='all, delete-orphan')
    pantry_items: Mapped[list[PantryItem]] = relationship(back_populates='user', cascade='all, delete-orphan')
    favorites: Mapped[list[RecipeFavorite]] = relationship(back_populates='user', cascade='all, delete-orphan')
    share_posts: Mapped[list[SharePost]] = relationship(back_populates='user', cascade='all, delete-orphan')

class ScanSession(Base):
    __tablename__ = 'scan_sessions'
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default='pending', nullable=False)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    tip: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user: Mapped[User] = relationship(back_populates='scan_sessions')
    images: Mapped[list[ScanImage]] = relationship(back_populates='session', cascade='all, delete-orphan')
    items: Mapped[list[ScanItem]] = relationship(back_populates='session', cascade='all, delete-orphan')
    recipes: Mapped[list[SessionRecipe]] = relationship(back_populates='session', cascade='all, delete-orphan')
    pantry_items: Mapped[list[PantryItem]] = relationship(back_populates='session')

class ScanImage(Base):
    __tablename__ = 'scan_images'
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('scan_sessions.id', ondelete='CASCADE'), index=True, nullable=False)
    thumbnail: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(String(50), nullable=False)
    session: Mapped[ScanSession] = relationship(back_populates='images')

class ScanItem(Base):
    __tablename__ = 'scan_items'
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('scan_sessions.id', ondelete='CASCADE'), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    freshness: Mapped[int] = mapped_column(Integer, default=FRESHNESS_DEFAULT, nullable=False)
    qty: Mapped[str] = mapped_column(String(50), default='', nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default='ai', nullable=False)
    session: Mapped[ScanSession] = relationship(back_populates='items')
    identification_links: Mapped[list['ScanItemIdentification']] = relationship(back_populates='scan_item', cascade='all, delete-orphan')

class IngredientIdentificationGroup(Base):
    __tablename__ = 'ingredient_identification_groups'
    __table_args__ = (UniqueConstraint('code', name='uq_ingredient_ident_group_code'),)
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    item_links: Mapped[list['ScanItemIdentification']] = relationship(back_populates='group', cascade='all, delete-orphan')

class ScanItemIdentification(Base):
    __tablename__ = 'scan_item_identification'
    __table_args__ = (UniqueConstraint('scan_item_id', 'group_id', name='uq_scan_item_ident_group'),)
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    scan_item_id: Mapped[int] = mapped_column(ForeignKey('scan_items.id', ondelete='CASCADE'), index=True, nullable=False)
    group_id: Mapped[int] = mapped_column(ForeignKey('ingredient_identification_groups.id', ondelete='CASCADE'), index=True, nullable=False)
    scan_item: Mapped['ScanItem'] = relationship(back_populates='identification_links')
    group: Mapped['IngredientIdentificationGroup'] = relationship(back_populates='item_links')

class SessionRecipe(Base):
    __tablename__ = 'session_recipes'
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('scan_sessions.id', ondelete='CASCADE'), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    uses_json: Mapped[str] = mapped_column(Text, nullable=False)
    extra_json: Mapped[str] = mapped_column(Text, nullable=False)
    steps_json: Mapped[str] = mapped_column(Text, nullable=False)
    minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    session: Mapped[ScanSession] = relationship(back_populates='recipes')

class FreshnessRef(Base):
    __tablename__ = 'freshness_refs'
    __table_args__ = (UniqueConstraint('product_name', name='uq_freshness_product'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    product_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    avg_freshness: Mapped[float] = mapped_column(Float, default=float(FRESHNESS_DEFAULT), nullable=False)
    observations: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_freshness: Mapped[int] = mapped_column(Integer, default=FRESHNESS_DEFAULT, nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class TrainingImage(Base):
    __tablename__ = 'training_images'
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    session_id: Mapped[int] = mapped_column(ForeignKey('scan_sessions.id', ondelete='CASCADE'), index=True, nullable=False)
    product_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    freshness: Mapped[int] = mapped_column(Integer, nullable=False)
    image_data: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(String(50), nullable=False)
    verified: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Group(Base):
    __tablename__ = 'groups'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    members: Mapped[list[GroupMember]] = relationship(back_populates='group', cascade='all, delete-orphan')
    join_codes: Mapped[list[GroupJoinCode]] = relationship(back_populates='group', cascade='all, delete-orphan')
    share_posts: Mapped[list[SharePost]] = relationship(back_populates='group', cascade='all, delete-orphan')

class GroupMember(Base):
    __tablename__ = 'group_members'
    __table_args__ = (UniqueConstraint('group_id', 'user_id', name='uq_group_membership'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('groups.id', ondelete='CASCADE'), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), default='member', nullable=False)
    joined_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    group: Mapped[Group] = relationship(back_populates='members')
    user: Mapped[User] = relationship(back_populates='memberships')

class GroupJoinCode(Base):
    __tablename__ = 'group_join_codes'
    __table_args__ = (UniqueConstraint('code', name='uq_group_join_code'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('groups.id', ondelete='CASCADE'), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    group: Mapped[Group] = relationship(back_populates='join_codes')

class PantryItem(Base):
    __tablename__ = 'pantry_items'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    session_id: Mapped[int | None] = mapped_column(ForeignKey('scan_sessions.id', ondelete='SET NULL'), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    freshness: Mapped[int] = mapped_column(Integer, default=FRESHNESS_DEFAULT, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default='manual', nullable=False)
    image_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user: Mapped[User] = relationship(back_populates='pantry_items')
    session: Mapped[ScanSession | None] = relationship(back_populates='pantry_items')

class Recipe(Base):
    __tablename__ = 'recipes'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingredients_json: Mapped[str] = mapped_column(Text, default='[]', nullable=False)
    steps_json: Mapped[str] = mapped_column(Text, default='[]', nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    favorites: Mapped[list[RecipeFavorite]] = relationship(back_populates='recipe', cascade='all, delete-orphan')

class RecipeFavorite(Base):
    __tablename__ = 'recipe_favorites'
    __table_args__ = (UniqueConstraint('user_id', 'recipe_id', name='uq_recipe_favorite'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    recipe_id: Mapped[int] = mapped_column(ForeignKey('recipes.id', ondelete='CASCADE'), index=True, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user: Mapped[User] = relationship(back_populates='favorites')
    recipe: Mapped[Recipe] = relationship(back_populates='favorites')

class SharePost(Base):
    __tablename__ = 'share_posts'
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('groups.id', ondelete='CASCADE'), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    group: Mapped[Group] = relationship(back_populates='share_posts')
    user: Mapped[User] = relationship(back_populates='share_posts')
    items: Mapped[list[SharePostItem]] = relationship(back_populates='share_post', cascade='all, delete-orphan')

class SharePostItem(Base):
    __tablename__ = 'share_post_items'
    id: Mapped[int] = mapped_column(primary_key=True)
    share_post_id: Mapped[int] = mapped_column(ForeignKey('share_posts.id', ondelete='CASCADE'), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    share_post: Mapped[SharePost] = relationship(back_populates='items')