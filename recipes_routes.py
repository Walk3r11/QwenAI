from __future__ import annotations
import json
import re

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import ENABLE_AI
from db import get_db
from groq_client import groq_chat_json, groq_configured
from models import GroupMember, PantryItem, Recipe, RecipeFavorite, SessionRecipe, User
from schemas import RecipeOut, RecipeSuggestRequest, RecommendedRecipesOut
from security import get_current_user

router = APIRouter(prefix='/recipes', tags=['recipes'])


def _recipe_to_out(recipe: Recipe, starred: bool) -> RecipeOut:
    try:
        ingredients = json.loads(recipe.ingredients_json or '[]')
    except Exception:
        ingredients = []
    try:
        steps = json.loads(recipe.steps_json or '[]')
    except Exception:
        steps = []
    return RecipeOut(id=recipe.id, title=recipe.title, description=recipe.description, ingredients=ingredients if isinstance(ingredients, list) else [], steps=steps if isinstance(steps, list) else [], starred=starred)


def _extract_json_text(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith('{') and raw.endswith('}'):
        return raw
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        return match.group(0)
    raise ValueError('No JSON object found in model output.')


def _call_recipe_model(items: list[str]) -> tuple[str, str | None, list[str], list[str]]:
    system = (
        'You are a kitchen assistant. Use only ingredients the user lists; never invent additions. '
        'Return strict JSON only.'
    )
    user_msg = (
        'These ingredients are everything the group has on hand (no shopping). '
        'One new leftover-friendly meal using ONLY this list; combine creatively. '
        'Return strict JSON only: {"title":string,"description":string|null,"ingredients":[string],"steps":[string]}. '
        'Ingredients must be from the given list only. Title under 90 chars, ingredients max 20, steps max 10.\n'
        f'Ingredients: {", ".join(items)}'
    )
    content = groq_chat_json(system, user_msg, temperature=0.2, max_tokens=1024)
    parsed = json.loads(_extract_json_text(content))
    title = str(parsed.get('title', '')).strip() or 'Group Meal Suggestion'
    description = parsed.get('description')
    ingredients = parsed.get('ingredients', [])
    steps = parsed.get('steps', [])
    if not isinstance(ingredients, list):
        ingredients = []
    if not isinstance(steps, list):
        steps = []
    ingredients = [str(i).strip() for i in ingredients if str(i).strip()][:20]
    steps = [str(s).strip() for s in steps if str(s).strip()][:10]
    desc_out = str(description).strip() if isinstance(description, str) else None
    return title, desc_out, ingredients, steps


@router.post('/suggest', response_model=list[RecipeOut])
def suggest_recipes(payload: RecipeSuggestRequest, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    items = [i.strip() for i in payload.items if i.strip()][:20]
    title = 'Scrap-to-Meal (stub)' if not items else f"Scrap-to-Meal: {', '.join(items[:3])}"
    recipe = db.scalar(select(Recipe).where(Recipe.title == title))
    if not recipe:
        recipe = Recipe(title=title, description=None if ENABLE_AI else 'AI suggestions are not enabled yet; this is a placeholder recipe.', ingredients_json=json.dumps(items or ['example ingredient']), steps_json=json.dumps(['Combine ingredients.', 'Cook until done.', 'Serve.']))
        db.add(recipe)
        db.commit()
        db.refresh(recipe)
    starred = bool(db.scalar(select(RecipeFavorite).where(RecipeFavorite.user_id == current_user.id, RecipeFavorite.recipe_id == recipe.id)))
    return [_recipe_to_out(recipe, starred=starred)]


@router.post('/suggest/group/{group_id}', response_model=list[RecipeOut])
def suggest_group_recipe(group_id: int, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    membership = db.scalar(select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == current_user.id))
    if not membership:
        raise HTTPException(status_code=403, detail='Not a member of this group.')
    member_ids = list(db.scalars(select(GroupMember.user_id).where(GroupMember.group_id == group_id)).all())
    if not member_ids:
        raise HTTPException(status_code=404, detail='Group has no members.')
    pantry_rows = list(db.scalars(select(PantryItem).where(PantryItem.user_id.in_(member_ids)).order_by(PantryItem.created_at.desc()).limit(300)).all())
    if not pantry_rows:
        raise HTTPException(status_code=400, detail='No pantry items found for this group.')
    grouped: dict[str, int] = {}
    for row in pantry_rows:
        name = row.name.strip().lower()
        if not name:
            continue
        grouped[name] = grouped.get(name, 0) + int(row.quantity or 1)
    items = [f'{name} x{qty}' if qty > 1 else name for name, qty in sorted(grouped.items(), key=lambda kv: (-kv[1], kv[0]))][:40]
    if not items:
        raise HTTPException(status_code=400, detail='No valid pantry items found for this group.')
    if ENABLE_AI and groq_configured():
        try:
            title, description, ingredients, steps = _call_recipe_model(items)
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=f'Groq error: {e}') from e
        except requests.RequestException as e:
            raise HTTPException(status_code=502, detail=f'Failed to reach Groq: {e}') from e
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            raise HTTPException(status_code=502, detail=f'Failed to parse Groq recipe output: {e}') from e
    else:
        title = f"Group Meal: {', '.join([i.split(' x')[0] for i in items[:3]])}"
        description = 'AI is disabled; this is a generated placeholder from combined group pantry.'
        ingredients = items[:12]
        steps = ['Pick the most perishable items first.', 'Cook ingredients into a single meal.', 'Serve to the group.']
    recipe = Recipe(title=title, description=description, ingredients_json=json.dumps(ingredients), steps_json=json.dumps(steps))
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    starred = bool(db.scalar(select(RecipeFavorite).where(RecipeFavorite.user_id == current_user.id, RecipeFavorite.recipe_id == recipe.id)))
    return [_recipe_to_out(recipe, starred=starred)]


@router.post('/{recipe_id}/star', status_code=status.HTTP_204_NO_CONTENT)
def star_recipe(recipe_id: int, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    recipe = db.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail='Recipe not found.')
    existing = db.scalar(select(RecipeFavorite).where(RecipeFavorite.user_id == current_user.id, RecipeFavorite.recipe_id == recipe_id))
    if not existing:
        db.add(RecipeFavorite(user_id=current_user.id, recipe_id=recipe_id))
        db.commit()
    return None


@router.delete('/{recipe_id}/star', status_code=status.HTTP_204_NO_CONTENT)
def unstar_recipe(recipe_id: int, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    fav = db.scalar(select(RecipeFavorite).where(RecipeFavorite.user_id == current_user.id, RecipeFavorite.recipe_id == recipe_id))
    if fav:
        db.delete(fav)
        db.commit()
    return None


@router.get('/favorites', response_model=list[RecipeOut])
def list_favorites(db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    q = select(Recipe).join(RecipeFavorite, RecipeFavorite.recipe_id == Recipe.id).where(RecipeFavorite.user_id == current_user.id).order_by(RecipeFavorite.created_at.desc())
    recipes = list(db.scalars(q).all())
    return [_recipe_to_out(r, starred=True) for r in recipes]


def _user_top_products(db: Session, user_id: int, limit: int = 20) -> list[str]:
    rows = db.execute(
        select(PantryItem.name, func.count(PantryItem.id).label('c'))
        .where(PantryItem.user_id == user_id)
        .group_by(PantryItem.name)
        .order_by(func.count(PantryItem.id).desc())
        .limit(limit)
    ).all()
    seen: set[str] = set()
    out: list[str] = []
    for name, _ in rows:
        key = (name or '').strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(name.strip())
    return out


def _generate_recommended(db: Session, user_id: int, products: list[str], count: int) -> list[Recipe]:
    if not (ENABLE_AI and groq_configured() and products):
        title = 'Quick Pantry Bowl'
        rec = Recipe(
            title=title,
            description='Toss together what you have on hand for a quick, filling meal.',
            ingredients_json=json.dumps(products[:8] or ['rice', 'vegetables', 'sauce']),
            steps_json=json.dumps(['Cook a base (rice or pasta).', 'Add chopped pantry vegetables.', 'Season and serve warm.']),
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return [rec]
    system = (
        'You are a creative home chef. Recommend recipes the user would enjoy based on their pantry history. '
        'You may suggest a small number of common store-cupboard staples beyond the listed items, but keep it realistic.'
        ' Reply with strict JSON only.'
    )
    user_msg = (
        f'The user often cooks with these ingredients (most-used first): {", ".join(products)}.\n'
        f'Suggest {count} appealing recipes mixing some of these items with a couple of nice new ideas. '
        'Each recipe object: {"title":string,"description":string|null,"ingredients":[string],"steps":[string]}. '
        'Return strict JSON only: {"recipes":[...]}'
    )
    try:
        raw = groq_chat_json(system, user_msg, temperature=0.4, max_tokens=1500)
        parsed = json.loads(_extract_json_text(raw))
    except (RuntimeError, requests.RequestException, ValueError, json.JSONDecodeError):
        return []
    raw_list = parsed.get('recipes', []) if isinstance(parsed, dict) else []
    out: list[Recipe] = []
    for entry in raw_list[:count]:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get('title') or '').strip()
        if not title:
            continue
        ingredients = [str(x).strip() for x in (entry.get('ingredients') or []) if str(x).strip()][:30]
        steps = [str(x).strip() for x in (entry.get('steps') or []) if str(x).strip()][:20]
        desc = entry.get('description')
        rec = Recipe(
            title=title[:200],
            description=str(desc)[:2000] if isinstance(desc, str) else None,
            ingredients_json=json.dumps(ingredients),
            steps_json=json.dumps(steps),
        )
        db.add(rec)
        out.append(rec)
    if out:
        db.commit()
        for r in out:
            db.refresh(r)
    return out


@router.get('/recommended', response_model=RecommendedRecipesOut)
def recommended_recipes(count: int=Query(4, ge=1, le=8), db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    products = _user_top_products(db, current_user.id)
    fav_recipe_ids = set(db.scalars(select(RecipeFavorite.recipe_id).where(RecipeFavorite.user_id == current_user.id)).all())
    recipes = _generate_recommended(db, current_user.id, products, count)
    return RecommendedRecipesOut(
        based_on=products[:8],
        recipes=[_recipe_to_out(r, starred=r.id in fav_recipe_ids) for r in recipes],
    )
