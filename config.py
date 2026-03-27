import os
from pathlib import Path
from dotenv import load_dotenv
from identification_data import ALLOWED_GROUP_CODES_PROMPT
load_dotenv(Path(__file__).resolve().parent / '.env')
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./app.db')
JWT_SECRET = os.getenv('JWT_SECRET', '')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRE_MINUTES = int(os.getenv('JWT_EXPIRE_MINUTES', '10080'))
ENABLE_AI = os.getenv('ENABLE_AI', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}
LLAMA_URL = os.getenv('LLAMA_URL', 'http://127.0.0.1:8081/v1/chat/completions')
LLAMA_MODEL = os.getenv('LLAMA_MODEL', 'qwen2.5-vl')
_read_raw = os.getenv('LLAMA_HTTP_READ_TIMEOUT', '86400').strip().lower()
if _read_raw in ('none', 'unlimited', '0', 'inf'):
    _llama_read = None
else:
    _llama_read = int(_read_raw)
LLAMA_HTTP_TIMEOUT = (60, _llama_read)
MODEL_DIR = os.getenv('MODEL_DIR', '/models')
VISION_MAX_TOKENS = int(os.getenv('VISION_MAX_TOKENS', '2560'))
SCAN_STREAM_HEARTBEAT_SEC = float(os.getenv('SCAN_STREAM_HEARTBEAT_SEC', '8'))
SCAN_PROMPT = os.getenv('SCAN_PROMPT', 'You are a zero-waste kitchen assistant with expert knowledge of food freshness. Carefully scan EVERY part of ALL images — foreground, background, plates, containers, shelves, fridge. For EACH visible food item: identify it, estimate its quantity, and critically assess its freshness by comparing color, texture, and appearance to what a perfectly fresh version would look like. Rate freshness on a 1-10 scale: 10=perfectly fresh, 7-9=good, 4-6=use soon, 2-3=about to expire, 1=spoiled/rotten. Give a confidence score 0.0-1.0 for each detection. List each unique item ONCE even if seen across multiple images. For EACH item also assign "groups": an array of category codes (all that apply). Use ONLY these exact codes, no others: ' + ALLOWED_GROUP_CODES_PROMPT + '. Meaning: dairy = milk, cheese, yogurt, cream; protein = meat, fish, eggs, tofu, beans/lentils as protein; produce = fresh fruits, vegetables, fresh herbs; pantry = packaged, canned, dried, boxed, bottled shelf-stable goods; all = mixed or applies broadly / unclear. Examples: milk → dairy; salmon → protein; apple → produce; dry pasta bag → pantry; grab-bag snacks → all. If you see any food, drink, or edible ingredient, you MUST list it in "items" with at least name, freshness, qty, and groups — do not return an empty "items" array when food is visible. Return ONLY valid JSON: {"items": [{"name": str, "freshness": int(1-10), "qty": str, "unit": str|null, "confidence": float, "groups": [str]}], "tip": str}')
RECIPE_PROMPT = os.getenv('RECIPE_PROMPT', 'You are a zero-waste recipe generator. Given these pantry items, suggest 2-3 recipes that maximize usage of available ingredients, prioritizing items marked as \'use-soon\' or \'expiring\'. Each recipe should be practical and quick. Return ONLY valid JSON: {"recipes": [{"name": str, "uses": [str], "extra": [str], "steps": [str], "minutes": int}]}')
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '').strip()
GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
GROQ_CHAT_URL = os.getenv('GROQ_CHAT_URL', 'https://api.groq.com/openai/v1/chat/completions')
GROQ_SYSTEM_PROMPT = os.getenv('GROQ_SYSTEM_PROMPT', 'You are an expert home cook and recipe writer. You give practical, safe cooking advice. Use well-known techniques and flavor pairings from general culinary knowledge. You do not browse the web; rely on established cooking knowledge only. Always respond with a single valid JSON object, no markdown.')
GROQ_RECIPE_USER_PROMPT = os.getenv('GROQ_RECIPE_USER_PROMPT', 'Given these ingredients from a user\'s kitchen scan (name, freshness 1-10 where lower means use urgently, qty):\n{items}\n\nSuggest 3 to 4 creative but realistic recipes that use as many of these ingredients as possible. Prioritize ingredients with freshness 6 or below. For each recipe include: name, uses (ingredients from their list that the recipe uses), extra (other ingredients they may need to buy), steps (short numbered-style strings), minutes (total time int). Return JSON exactly in this shape: {"recipes": [{"name": "string", "uses": ["string"], "extra": ["string"], "steps": ["string"], "minutes": 30}]}')