from __future__ import annotations
import json
import re

import requests
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import ENABLE_AI, LLAMA_MODEL, LLAMA_URL
from db import get_db
from models import GroupMember, PantryItem, Recipe, RecipeFavorite, User
from schemas import RecipeOut, RecipeSuggestRequest
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
    prompt = (
        'These ingredients are everything the group has on hand (no shopping). '
        'One new leftover-friendly meal using ONLY this list; combine creatively. '
        'Return strict JSON only: {"title":string,"description":string|null,"ingredients":[string],"steps":[string]}. '
        'Ingredients must be from the given list only. Title under 90 chars, ingredients max 20, steps max 10.'
    )
    payload = {'model': LLAMA_MODEL, 'stream': False, 'messages': [{'role': 'user', 'content': f'{prompt}\nIngredients: {", ".join(items)}'}], 'temperature': 0.2, 'response_format': {'type': 'json_object'}}
    r = requests.post(LLAMA_URL, json=payload, timeout=120)
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail={'model_status': r.status_code, 'body': r.text})
    model_json = r.json()
    content = model_json['choices'][0]['message']['content']
    if not isinstance(content, str):
        content = json.dumps(content)
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
    if ENABLE_AI:
        try:
            title, description, ingredients, steps = _call_recipe_model(items)
        except requests.RequestException as e:
            raise HTTPException(status_code=502, detail=f'Failed to reach model server: {e}') from e
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            raise HTTPException(status_code=502, detail=f'Failed to parse model recipe output: {e}') from e
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
