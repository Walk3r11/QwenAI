import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))

LLAMA_URL = os.getenv("LLAMA_URL", "http://127.0.0.1:8081/v1/chat/completions")
LLAMA_MODEL = os.getenv("LLAMA_MODEL", "qwen2.5-vl")
MODEL_DIR = os.getenv("MODEL_DIR", "/models")
ANALYZE_PROMPT = os.getenv(
    "ANALYZE_PROMPT",
    "You are a zero-waste kitchen assistant. Carefully scan EVERY part of this image — "
    "foreground, background, plates, containers, shelves. "
    "List ALL visible food: meat, fish, dairy, bread, grains, pasta, noodles, fruits, vegetables, "
    "sauces, drinks, spices, garnishes, leftovers, and condiments. "
    "List each item ONCE. Estimate freshness. "
    "Then suggest 1-2 recipes using the most items, prioritizing expiring food. Be concise. "
    "Return ONLY valid JSON: "
    '{\"items\": [{\"name\": str, \"freshness\": \"fresh\"|\"use-soon\"|\"expiring\", \"qty\": str}], '
    '\"recipes\": [{\"name\": str, \"uses\": [str], \"extra\": [str], '
    '\"steps\": [str], \"minutes\": int}], '
    '\"tip\": str}',
)