from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    scans: Mapped[list["Scan"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    image_thumbnail: Mapped[str] = mapped_column(Text, nullable=True)
    image_mime: Mapped[str] = mapped_column(String(50), nullable=True)
    items_json: Mapped[str] = mapped_column(Text, nullable=False)
    tip: Mapped[str] = mapped_column(Text, nullable=True)
    raw_response: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="scans")
    recipes: Mapped[list["Recipe"]] = relationship(back_populates="scan", cascade="all, delete-orphan")


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    scan_id: Mapped[int] = mapped_column(Integer, ForeignKey("scans.id"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    uses_json: Mapped[str] = mapped_column(Text, nullable=False)
    extra_json: Mapped[str] = mapped_column(Text, nullable=False)
    steps_json: Mapped[str] = mapped_column(Text, nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    scan: Mapped["Scan"] = relationship(back_populates="recipes")
