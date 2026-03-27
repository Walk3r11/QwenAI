import requests
from config import GROQ_API_KEY, GROQ_CHAT_URL, GROQ_MODEL

def groq_configured() -> bool:
    return bool(GROQ_API_KEY)

def groq_chat_json(system: str, user: str, *, temperature: float=0.35, max_tokens: int=4096) -> str:
    if not GROQ_API_KEY:
        raise RuntimeError('GROQ_API_KEY is not set')
    headers = {'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'}
    payload = {'model': GROQ_MODEL, 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}], 'temperature': temperature, 'max_tokens': max_tokens, 'response_format': {'type': 'json_object'}}
    r = requests.post(GROQ_CHAT_URL, headers=headers, json=payload, timeout=120)
    if r.status_code == 400 and 'response_format' in payload:
        del payload['response_format']
        r = requests.post(GROQ_CHAT_URL, headers=headers, json=payload, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f'Groq HTTP {r.status_code}: {r.text[:800]}')
    data = r.json()
    content = data['choices'][0]['message']['content']
    if not isinstance(content, str):
        raise RuntimeError('Groq returned non-string content')
    return content