import requests
from config import GROQ_API_KEY, GROQ_CHAT_URL, GROQ_MODEL, GROQ_VISION_MODEL

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


def groq_chat_vision_json(
    system: str,
    user_text: str,
    images: list[tuple[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2560,
) -> str:
    """Multi-image vision call to Groq.

    `images` is a list of (base64_data, mime) tuples (JPEG/PNG).
    System prompt is sent as a separate message; some Groq vision models
    reject system roles, so we fall back to prepending it to the user text.
    """
    if not GROQ_API_KEY:
        raise RuntimeError('GROQ_API_KEY is not set')
    chosen_model = model or GROQ_VISION_MODEL
    headers = {'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'}
    content_parts: list[dict] = [{'type': 'text', 'text': user_text}]
    for b64, mime in images:
        content_parts.append({
            'type': 'image_url',
            'image_url': {'url': f'data:{mime or "image/jpeg"};base64,{b64}'},
        })

    def _post(messages: list[dict], use_json_format: bool) -> requests.Response:
        body: dict = {
            'model': chosen_model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
        }
        if use_json_format:
            body['response_format'] = {'type': 'json_object'}
        return requests.post(GROQ_CHAT_URL, headers=headers, json=body, timeout=180)

    msgs_with_system = [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': content_parts},
    ]
    msgs_no_system = [
        {'role': 'user', 'content': [
            {'type': 'text', 'text': f'{system}\n\n{user_text}'},
            *content_parts[1:],
        ]},
    ]

    r = _post(msgs_with_system, use_json_format=True)
    if r.status_code == 400:
        r = _post(msgs_no_system, use_json_format=True)
    if r.status_code == 400:
        r = _post(msgs_no_system, use_json_format=False)
    if r.status_code >= 400:
        raise RuntimeError(f'Groq vision HTTP {r.status_code}: {r.text[:800]}')
    data = r.json()
    content = data['choices'][0]['message']['content']
    if isinstance(content, list):
        content = ''.join(part.get('text', '') for part in content if isinstance(part, dict))
    if not isinstance(content, str):
        raise RuntimeError('Groq vision returned non-string content')
    return content
