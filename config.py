import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))

ENABLE_AI = os.getenv("ENABLE_AI", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

LLAMA_URL = os.getenv("LLAMA_URL", "http://127.0.0.1:8081/v1/chat/completions")
LLAMA_MODEL = os.getenv("LLAMA_MODEL", "qwen2.5-vl")
MODEL_DIR = os.getenv("MODEL_DIR", "/models")

SCAN_PROMPT = os.getenv(
    "SCAN_PROMPT",
    "You are a food freshness inspector. Carefully examine EVERY part of the image(s) — "
    "foreground, background, plates, containers, shelves, fridge. "
    "Identify ALL visible food items: meat, fish, dairy, bread, grains, pasta, noodles, "
    "fruits, vegetables, sauces, drinks, spices, garnishes, leftovers, condiments. "
    "List each unique item ONCE. "
    "For each item, estimate freshness by comparing its visual appearance (color, texture, "
    "wilting, mold, browning, dryness) against what the same product looks like when perfectly fresh. "
    "Assign a confidence score 0.0-1.0 for how certain you are the item is present. "
    "Return ONLY valid JSON: "
    '{"items": [{"name": str, "freshness": "fresh"|"use-soon"|"expiring", "qty": str, "confidence": float}]}',
)

RECIPE_PROMPT = os.getenv(
    "RECIPE_PROMPT",
    "You are a zero-waste kitchen assistant. Given the following pantry items with freshness levels, "
    "suggest 2-3 recipes that use as many items as possible, prioritizing items that are expiring. "
    "Be practical and concise. "
    "Return ONLY valid JSON: "
    '{"recipes": [{"name": str, "uses": [str], "extra": [str], '
    '"steps": [str], "minutes": int}], '
    '"tip": str}',
)
