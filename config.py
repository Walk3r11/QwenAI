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
QWENAI_TESTING = os.getenv('QWENAI_TESTING', '').strip().lower() in {'1', 'true', 'yes', 'on'}
AUTH_SIGNUP_IMMEDIATE_TOKEN = QWENAI_TESTING
PC_SCAN_SHARED_SECRET = os.getenv('PC_SCAN_SHARED_SECRET', '').strip()
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
SCAN_STREAM_HEARTBEAT_SEC = float(os.getenv('SCAN_STREAM_HEARTBEAT_SEC', '4'))
FRESHNESS_MIN = max(1, int(os.getenv('FRESHNESS_MIN', '1')))
FRESHNESS_MAX = int(os.getenv('FRESHNESS_MAX', '5'))
if FRESHNESS_MAX < FRESHNESS_MIN:
    FRESHNESS_MAX = FRESHNESS_MIN
if FRESHNESS_MAX > 100:
    FRESHNESS_MAX = 100
_mid = (FRESHNESS_MIN + FRESHNESS_MAX + 1) // 2
FRESHNESS_DEFAULT = int(os.getenv('FRESHNESS_DEFAULT', str(_mid)))
FRESHNESS_DEFAULT = max(FRESHNESS_MIN, min(FRESHNESS_MAX, FRESHNESS_DEFAULT))
_groq_prio_default = max(FRESHNESS_MIN, min(FRESHNESS_MAX, int(round(0.6 * FRESHNESS_MAX))))
GROQ_RECIPE_PRIORITIZE_BELOW = int(os.getenv('GROQ_RECIPE_PRIORITIZE_BELOW', str(_groq_prio_default)))
GROQ_RECIPE_PRIORITIZE_BELOW = max(FRESHNESS_MIN, min(FRESHNESS_MAX, GROQ_RECIPE_PRIORITIZE_BELOW))

def _default_scan_prompt() -> str:
    mn, mx = FRESHNESS_MIN, FRESHNESS_MAX
    return (
        'You are a zero-waste kitchen assistant with expert knowledge of food freshness. Carefully scan EVERY part of ALL images — foreground, background, plates, containers, shelves, fridge. For EACH visible food item: identify it, estimate its quantity, and critically assess its freshness by comparing color, texture, and appearance to what a perfectly fresh version would look like. '
        f'Rate "freshness" as an integer from {mn} to {mx} only: {mx} = perfectly fresh, lower numbers mean worse condition, {mn} = spoiled or inedible. Use the full range when appropriate. '
        'Give a confidence score 0.0-1.0 for each detection. List each unique item ONCE even if seen across multiple images. For EACH item also assign "groups": an array of category codes (all that apply). Use ONLY these exact codes, no others: '
        + ALLOWED_GROUP_CODES_PROMPT
        + '. Meaning: dairy = milk, cheese, yogurt, cream; protein = meat, fish, eggs, tofu, beans/lentils as protein; produce = fresh fruits, vegetables, fresh herbs; pantry = packaged, canned, dried, boxed, bottled shelf-stable goods; all = mixed or applies broadly / unclear. Examples: milk → dairy; salmon → protein; apple → produce; dry pasta bag → pantry; grab-bag snacks → all. If you see any food, drink, or edible ingredient, you MUST list it in "items" with at least name, freshness, qty, and groups — do not return an empty "items" array when food is visible. '
        + f'Return ONLY valid JSON: {{"items": [{{"name": str, "freshness": int ({mn}-{mx}), "qty": str, "unit": str|null, "confidence": float, "groups": [str]}}], "tip": str}}'
    )

SCAN_PROMPT = os.getenv('SCAN_PROMPT') or _default_scan_prompt()
RECIPE_PROMPT = os.getenv('RECIPE_PROMPT', 'You are a zero-waste recipe generator. Given these pantry items, suggest 2-3 recipes that maximize usage of available ingredients, prioritizing items marked as \'use-soon\' or \'expiring\'. Each recipe should be practical and quick. Return ONLY valid JSON: {"recipes": [{"name": str, "uses": [str], "extra": [str], "steps": [str], "minutes": int}]}')
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '').strip()
GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
GROQ_CHAT_URL = os.getenv('GROQ_CHAT_URL', 'https://api.groq.com/openai/v1/chat/completions')
GROQ_SYSTEM_PROMPT = os.getenv('GROQ_SYSTEM_PROMPT', 'You are an expert home cook and recipe writer. You give practical, safe cooking advice. Use well-known techniques and flavor pairings from general culinary knowledge. You do not browse the web; rely on established cooking knowledge only. Always respond with a single valid JSON object, no markdown.')
def _default_groq_recipe_user_prompt() -> str:
    mn, mx = FRESHNESS_MIN, FRESHNESS_MAX
    p = GROQ_RECIPE_PRIORITIZE_BELOW
    return (
        f'Given these ingredients from a user\'s kitchen scan (name, freshness {mn}-{mx} where lower means use urgently, qty):\n{{items}}\n\n'
        f'Suggest 3 to 4 creative but realistic recipes that use as many of these ingredients as possible. Prioritize ingredients with freshness {p} or below. '
        'For each recipe include: name, uses (ingredients from their list that the recipe uses), extra (other ingredients they may need to buy), steps (short numbered-style strings), minutes (total time int). '
        'Return JSON exactly in this shape: {"recipes": [{"name": "string", "uses": ["string"], "extra": ["string"], "steps": ["string"], "minutes": 30}]}'
    )

GROQ_RECIPE_USER_PROMPT = os.getenv('GROQ_RECIPE_USER_PROMPT') or _default_groq_recipe_user_prompt()