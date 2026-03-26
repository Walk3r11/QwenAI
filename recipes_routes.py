from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import ENABLE_AI
from db import get_db
from models import Recipe, RecipeFavorite, User
from schemas import RecipeOut, RecipeSuggestRequest
from security import get_current_user

router = APIRouter(prefix="/recipes", tags=["recipes"])


def _recipe_to_out(recipe: Recipe, starred: bool) -> RecipeOut:
    try:
        ingredients = json.loads(recipe.ingredients_json or "[]")
    except Exception:
        ingredients = []
    try:
        steps = json.loads(recipe.steps_json or "[]")
    except Exception:
        steps = []
    return RecipeOut(
        id=recipe.id,
        title=recipe.title,
        description=recipe.description,
        ingredients=ingredients if isinstance(ingredients, list) else [],
        steps=steps if isinstance(steps, list) else [],
        starred=starred,
    )


@router.post("/suggest", response_model=list[RecipeOut])
def suggest_recipes(
    payload: RecipeSuggestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = [i.strip() for i in payload.items if i.strip()][:20]

    title = "Scrap-to-Meal (stub)" if not items else f"Scrap-to-Meal: {', '.join(items[:3])}"
    recipe = db.scalar(select(Recipe).where(Recipe.title == title))
    if not recipe:
        recipe = Recipe(
            title=title,
            description=None if ENABLE_AI else "AI suggestions are not enabled yet; this is a placeholder recipe.",
            ingredients_json=json.dumps(items or ["example ingredient"]),
            steps_json=json.dumps(["Combine ingredients.", "Cook until done.", "Serve."]),
        )
        db.add(recipe)
        db.commit()
        db.refresh(recipe)

    starred = bool(
        db.scalar(select(RecipeFavorite).where(RecipeFavorite.user_id == current_user.id, RecipeFavorite.recipe_id == recipe.id))
    )
    return [_recipe_to_out(recipe, starred=starred)]


@router.post("/{recipe_id}/star", status_code=status.HTTP_204_NO_CONTENT)
def star_recipe(recipe_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    recipe = db.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found.")
    existing = db.scalar(
        select(RecipeFavorite).where(RecipeFavorite.user_id == current_user.id, RecipeFavorite.recipe_id == recipe_id)
    )
    if not existing:
        db.add(RecipeFavorite(user_id=current_user.id, recipe_id=recipe_id))
        db.commit()
    return None


@router.delete("/{recipe_id}/star", status_code=status.HTTP_204_NO_CONTENT)
def unstar_recipe(recipe_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    fav = db.scalar(
        select(RecipeFavorite).where(RecipeFavorite.user_id == current_user.id, RecipeFavorite.recipe_id == recipe_id)
    )
    if fav:
        db.delete(fav)
        db.commit()
    return None


@router.get("/favorites", response_model=list[RecipeOut])
def list_favorites(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = (
        select(Recipe)
        .join(RecipeFavorite, RecipeFavorite.recipe_id == Recipe.id)
        .where(RecipeFavorite.user_id == current_user.id)
        .order_by(RecipeFavorite.created_at.desc())
    )
    recipes = list(db.scalars(q).all())
    return [_recipe_to_out(r, starred=True) for r in recipes]
