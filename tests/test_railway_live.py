import json
import os
import uuid
from io import BytesIO
from pathlib import Path
from typing import Tuple
import httpx
import pytest
from PIL import Image
BASE = os.environ.get('RAILWAY_BASE_URL', '').rstrip('/')

def _is_placeholder_railway_url(url: str) -> bool:
    if not url:
        return True
    host = url.lower().replace('https://', '').replace('http://', '').split('/')[0]
    return host in ('your-app.up.railway.app', 'your-service.up.railway.app') or 'your-app' in host
pytestmark = pytest.mark.skipif(not BASE or _is_placeholder_railway_url(BASE), reason='Set RAILWAY_BASE_URL to your real public URL from Railway (service → Settings → Networking), e.g. https://qwenai-production.up.railway.app — not the docs placeholder your-app.up.railway.app')

def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new('RGB', (64, 64), color=(180, 120, 60)).save(buf, format='PNG')
    return buf.getvalue()

def _test_image_file() -> Tuple[bytes, str]:
    path = os.environ.get('RAILWAY_TEST_IMAGE')
    if path and Path(path).is_file():
        p = Path(path)
        data = p.read_bytes()
        mime = 'image/jpeg' if p.suffix.lower() in ('.jpg', '.jpeg') else 'image/png'
        return (data, mime)
    repo = Path(__file__).resolve().parent.parent / 'test.jpg'
    if repo.is_file():
        return (repo.read_bytes(), 'image/jpeg')
    return (_png_bytes(), 'image/png')

@pytest.fixture(scope='module')
def bearer_token():
    if (t := os.environ.get('RAILWAY_BEARER_TOKEN')):
        return t.strip()
    suffix = uuid.uuid4().hex[:14]
    email = f'snapchef_live_{suffix}@example.com'
    password = f'RwTest_{suffix}9Aa!'
    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        r = client.post('/auth/signup', json={'email': email, 'name': 'Railway Live Test', 'password': password})
        if r.status_code not in (200, 201):
            pytest.fail(f'Signup failed: {r.status_code} {r.text[:500]}')
        return r.json()['access_token']

def test_railway_health():
    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        r = client.get('/health')
    if r.status_code == 404:
        pytest.fail(f'Got 404 from {BASE}/health — wrong URL or app not deployed. Use the exact URL from Railway (no trailing path). Body: {r.text[:300]}')
    assert r.status_code == 200
    data = r.json()
    assert data.get('ok') is True
    assert data.get('db_connected') is True
    if not data.get('ai_enabled'):
        pytest.fail('AI is disabled on the server. Set ENABLE_AI=true in Railway and redeploy.')
    if not data.get('model_file_present') or not data.get('mmproj_file_present'):
        pytest.fail('Model files missing on the server. Check MODEL_URL / MMPROJ_URL and logs.')

@pytest.mark.live_railway
def test_railway_ai_session_stream(bearer_token):
    headers = {'Authorization': f'Bearer {bearer_token}'}
    img, mime = _test_image_file()
    ext = 'jpg' if 'jpeg' in mime else 'png'
    files = {'files': (f'scan.{ext}', img, mime)}
    timeout = httpx.Timeout(300.0, connect=30.0)
    lines: list[str] = []
    with httpx.Client(base_url=BASE, timeout=timeout) as client:
        with client.stream('POST', '/ai/sessions', headers=headers, files=files) as resp:
            assert resp.status_code == 200, f'HTTP {resp.status_code} {resp.text[:500]}'
            for chunk in resp.iter_bytes():
                lines.append(chunk.decode('utf-8', errors='replace'))
    text = ''.join(lines)
    parsed_lines = [ln for ln in text.split('\n') if ln.strip()]
    assert parsed_lines, 'No NDJSON lines from /ai/sessions'
    last = json.loads(parsed_lines[-1])
    if last.get('status') == 'error':
        pytest.fail(f"AI endpoint error: {last.get('detail', last)}")
    assert last.get('status_msg') == 'done', f'Unexpected final payload: {last!r}'
    assert 'id' in last
    assert 'items' in last

@pytest.mark.live_railway
def test_railway_food_categories_then_groq_recipes(bearer_token):
    headers = {'Authorization': f'Bearer {bearer_token}'}
    img, mime = _test_image_file()
    ext = 'jpg' if 'jpeg' in mime else 'png'
    files = {'files': (f'scan.{ext}', img, mime)}
    timeout = httpx.Timeout(600.0, connect=30.0)
    lines: list[str] = []
    with httpx.Client(base_url=BASE, timeout=timeout) as client:
        with client.stream('POST', '/ai/sessions', headers=headers, files=files) as resp:
            assert resp.status_code == 200, f'HTTP {resp.status_code} {resp.text[:500]}'
            for chunk in resp.iter_bytes():
                lines.append(chunk.decode('utf-8', errors='replace'))
    text = ''.join(lines)
    parsed_lines = [ln for ln in text.split('\n') if ln.strip()]
    last = json.loads(parsed_lines[-1])
    assert last.get('status_msg') == 'done', last
    sid = last['id']

    with httpx.Client(base_url=BASE, timeout=timeout) as client:
        r = client.get(f'/ai/sessions/{sid}', headers=headers)
        assert r.status_code == 200
        sess = r.json()
        if not sess.get('items'):
            body = {'name': 'Test tomato', 'freshness': 4, 'qty': '3', 'unit': None, 'identification_group_codes': ['produce']}
            r2 = client.post(f'/ai/sessions/{sid}/items', headers=headers, json=body)
            assert r2.status_code == 201, r2.text
            r = client.get(f'/ai/sessions/{sid}', headers=headers)
            sess = r.json()
        assert sess.get('items'), 'Expected at least one item after vision or fallback'
        for it in sess['items']:
            assert 'name' in it
            assert 'identification_groups' in it
            for g in it['identification_groups']:
                assert g.get('code') in {'dairy', 'protein', 'produce', 'pantry', 'all'}

        r3 = client.post(f'/ai/sessions/{sid}/confirm', headers=headers)
        assert r3.status_code == 200, r3.text

        r4 = client.post(f'/ai/sessions/{sid}/groq-recipes', headers=headers)
        assert r4.status_code == 200, r4.text
        out = r4.json()
        assert out.get('recipes'), out
        assert all((rec.get('name') for rec in out['recipes']))