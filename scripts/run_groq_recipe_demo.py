from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('JWT_SECRET', 'local-demo-secret-at-least-32-characters-long')
os.environ.setdefault('ENABLE_AI', 'true')
_stub = ROOT / '.model_stub_demo'
_stub.mkdir(exist_ok=True)
(_stub / 'qwen.gguf').write_bytes(b'x')
(_stub / 'mmproj.gguf').write_bytes(b'x')
os.environ['MODEL_DIR'] = str(_stub)
from scan_upload_helpers import multipart_image_files

def _sse_stream_for_json(payload: dict) -> list[str]:
    body = json.dumps(payload)
    lines = []
    step = 12
    for i in range(0, len(body), step):
        chunk = body[i:i + step]
        lines.append('data: ' + json.dumps({'choices': [{'delta': {'content': chunk}}]}))
    lines.append('data: [DONE]')
    return lines

class FakeStreamResponse:

    def __init__(self, lines: list[str], status_code: int=200):
        self._lines = lines
        self.status_code = status_code
        self.text = ''

    def iter_lines(self, decode_unicode: bool=True):
        for line in self._lines:
            yield (line if decode_unicode else line.encode('utf-8'))

def _read_ndjson_last(resp) -> dict:
    buf = b''
    for chunk in resp.iter_bytes():
        buf += chunk
    text = buf.decode('utf-8')
    lines = [ln for ln in text.strip().split('\n') if ln.strip()]
    return json.loads(lines[-1])

def main() -> int:
    import config
    from groq_client import groq_configured
    from fastapi.testclient import TestClient
    from main import app
    if not groq_configured():
        print('GROQ_API_KEY missing — add it to .env in the repo root.', file=sys.stderr)
        return 1
    scan_payload = {'items': [{'name': 'chicken breast', 'freshness': 6, 'qty': '400', 'unit': 'g', 'confidence': 0.9}, {'name': 'bell pepper', 'freshness': 7, 'qty': '2', 'unit': None, 'confidence': 0.85}, {'name': 'rice', 'freshness': 9, 'qty': '300', 'unit': 'g', 'confidence': 0.8}], 'tip': 'Cook chicken within a day or two.'}
    with patch('ai_routes.requests.post') as mock_post:
        mock_post.return_value = FakeStreamResponse(_sse_stream_for_json(scan_payload))
        client = TestClient(app)
        r = client.post('/auth/signup', json={'email': 'demo-groq@example.com', 'name': 'Groq Demo', 'password': 'DemoPass123'})
        if r.status_code == 409:
            r = client.post('/auth/login', json={'email': 'demo-groq@example.com', 'password': 'DemoPass123'})
        r.raise_for_status()
        token = r.json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}
        files = multipart_image_files(10)
        with client.stream('POST', '/ai/sessions', files=files, headers=headers) as resp:
            resp.raise_for_status()
            session = _read_ndjson_last(resp)
        sid = session['id']
        print('--- Scan (mocked vision, 10 images) ---')
        print(json.dumps({'status_msg': session.get('status_msg'), 'image_count': len(session.get('images') or []), 'items': session.get('items')}, indent=2))
        r = client.post(f'/ai/sessions/{sid}/confirm', headers=headers)
        r.raise_for_status()
        print('\n--- Confirmed session', sid, '---')
        r = client.post(f'/ai/sessions/{sid}/groq-recipes', headers=headers)
        if r.status_code != 200:
            print('Groq recipes error:', r.status_code, r.text[:2000], file=sys.stderr)
            return 1
        body = r.json()
        print('\n--- Groq recipes (live API) ---')
        print(json.dumps(body, indent=2))
    return 0
if __name__ == '__main__':
    raise SystemExit(main())