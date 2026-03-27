import os
from pathlib import Path
from dotenv import load_dotenv
from identification_data import ALLOWED_GROUP_CODES_PROMPT
load_dotenv(Path(__file__).resolve().parent / '.env')
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./app.db')
GOOGLE_WEB_CLIENT_ID = os.getenv('GOOGLE_WEB_CLIENT_ID', '')
JWT_SECRET = os.getenv('JWT_SECRET', '')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRE_MINUTES = int(os.getenv('JWT_EXPIRE_MINUTES', '10080'))
ENABLE_AI = os.getenv('ENABLE_AI', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}
QWENAI_TESTING = os.getenv('QWENAI_TESTING', '').strip().lower() in {'1', 'true', 'yes', 'on'}
AUTH_SIGNUP_IMMEDIATE_TOKEN = QWENAI_TESTING
PC_SCAN_SHARED_SECRET = os.getenv('PC_SCAN_SHARED_SECRET', '').strip()
_allow_pc_raw = os.getenv('ALLOW_PC_SCRIPT_SIGNUP', 'true').strip().lower()
ALLOW_PC_SCRIPT_SIGNUP = _allow_pc_raw not in {'0', 'false', 'no', 'off'}
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
RECIPE_PROMPT = os.getenv('RECIPE_PROMPT', 'You turn ONLY what the user already has (this exact list from their scan photos — leftovers and odds and ends) into NEW dishes. Do not assume they can shop. Every ingredient in the dish must be drawn from the list; "uses" must name items from that list only. Set "extra" to [] (empty). Prefer combining leftovers creatively (bowls, hashes, soups, wraps, fried rice-style mixes, salads) using solely these foods. Prioritize lower freshness numbers first. Return ONLY valid JSON: {"recipes": [{"name": str, "uses": [str], "extra": [str], "steps": [str], "minutes": int}]}')
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '').strip()
GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
GROQ_CHAT_URL = os.getenv('GROQ_CHAT_URL', 'https://api.groq.com/openai/v1/chat/completions')
GROQ_SYSTEM_PROMPT = os.getenv('GROQ_SYSTEM_PROMPT', 'You are an expert home cook. The user lists ONLY foods detected from their fridge/pantry photos — that is their entire inventory. You invent new meals and leftover makeovers using those ingredients alone. Never assume they can buy anything. "extra" in each recipe must always be []. "uses" must only reference names from their list. Safe techniques only. Respond with one valid JSON object, no markdown.')
def _default_groq_recipe_user_prompt() -> str:
    mn, mx = FRESHNESS_MIN, FRESHNESS_MAX
    p = GROQ_RECIPE_PRIORITIZE_BELOW
    return (
        f'These are the ONLY foods the user has right now (from photos they scanned; name, freshness {mn}-{mx} lower = use first, qty):\n{{items}}\n\n'
        f'Propose 3 or 4 NEW dishes made strictly from this list — leftover-friendly (recombine, repurpose, one-pan, bowl, soup, wrap, hash, salad). '
        f'Use up items with freshness {p} or below first. '
        'Each recipe: "name", "uses" (subset of the listed food names only), "extra" must be [] always, "steps" (short strings), "minutes" (int). '
        'Do not add ingredients they do not have. Return JSON: {"recipes": [{"name": "string", "uses": ["string"], "extra": [], "steps": ["string"], "minutes": 30}]}'
    )

GROQ_RECIPE_USER_PROMPT = os.getenv('GROQ_RECIPE_USER_PROMPT') or _default_groq_recipe_user_prompt()