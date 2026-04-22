import json
import os
import pytest
from scan_upload_helpers import multipart_image_files
RUN_LIVE = os.getenv('RUN_LIVE_AI_E2E', '').strip().lower() in ('1', 'true', 'yes')
HAS_GROQ = bool((os.getenv('GROQ_API_KEY') or '').strip())
pytestmark = [pytest.mark.live_ai_e2e, pytest.mark.skipif(not RUN_LIVE or not HAS_GROQ, reason='Set RUN_LIVE_AI_E2E=1 and GROQ_API_KEY to run live Groq vision + recipes E2E')]


def _read_ndjson_last(stream_response) -> dict:
    buf = b''
    for chunk in stream_response.iter_bytes():
        buf += chunk
    text = buf.decode('utf-8')
    lines = [ln for ln in text.strip().split('\n') if ln.strip()]
    assert lines, 'No NDJSON lines from stream'
    return json.loads(lines[-1])


def test_live_vision_scan_then_groq_recipes(client, auth_headers):
    files = multipart_image_files(10)
    with client.stream('POST', '/ai/sessions', files=files, headers=auth_headers) as resp:
        assert resp.status_code == 200, resp.text
        data = _read_ndjson_last(resp)
    if data.get('status') == 'error' or data.get('status_msg') != 'done':
        pytest.fail(f'Vision pipeline failed: {data!r}')
    assert len(data.get('images') or []) == 10, f'Expected 10 images on session: {data!r}'
    assert data.get('items'), f'Expected at least one detected item, got: {data!r}'
    sid = data['id']
    r = client.post(f'/ai/sessions/{sid}/confirm', headers=auth_headers)
    assert r.status_code == 200, r.text
    r = client.post(f'/ai/sessions/{sid}/groq-recipes', headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body['recipes']) >= 1
    for rec in body['recipes']:
        assert rec.get('name')
        assert isinstance(rec.get('uses'), list)
    sess = client.get(f'/ai/sessions/{sid}', headers=auth_headers).json()
    assert len(sess['recipes']) >= 1