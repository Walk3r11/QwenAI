import json
from io import BytesIO
from unittest.mock import patch
from PIL import Image
from scan_upload_helpers import multipart_image_files


def _tiny_png() -> bytes:
    buf = BytesIO()
    Image.new('RGB', (4, 4), color=(200, 100, 50)).save(buf, format='PNG')
    return buf.getvalue()


def _read_ndjson_last(stream_response) -> dict:
    buf = b''
    for chunk in stream_response.iter_bytes():
        buf += chunk
    text = buf.decode('utf-8')
    last_line = [ln for ln in text.strip().split('\n') if ln.strip()][-1]
    return json.loads(last_line)


def test_sessions_requires_auth(client):
    files = [('files', ('x.png', _tiny_png(), 'image/png'))]
    r = client.post('/ai/sessions', files=files)
    assert r.status_code == 401


def test_identification_groups_catalog(client, auth_headers):
    r = client.get('/ai/identification-groups', headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    codes = {g['code'] for g in data}
    assert {'dairy', 'protein', 'produce', 'pantry', 'all'}.issubset(codes)
    assert all(('label' in g and 'id' in g for g in data))


@patch('ai_routes.groq_chat_vision_json')
def test_create_session_ndjson_done(mock_vision, client, auth_headers):
    payload = {'items': [{'name': 'tomato', 'freshness': 5, 'qty': '3', 'unit': None, 'confidence': 0.88, 'groups': ['produce']}], 'tip': 'use soon'}
    mock_vision.return_value = json.dumps(payload)
    files = [('files', ('shot.png', _tiny_png(), 'image/png'))]
    with client.stream('POST', '/ai/sessions', files=files, headers=auth_headers) as resp:
        assert resp.status_code == 200
        data = _read_ndjson_last(resp)
    assert data.get('status_msg') == 'done'
    assert data['id'] >= 1
    assert len(data['items']) == 1
    assert data['items'][0]['name'] == 'tomato'
    assert data['items'][0]['freshness'] == 5
    assert data['items'][0]['alert'] is None
    codes = {g['code'] for g in data['items'][0].get('identification_groups', [])}
    assert 'produce' in codes


@patch('ai_routes.groq_chat_vision_json')
def test_session_confirm_pantry_and_training(mock_vision, client, auth_headers):
    payload = {'items': [{'name': 'milk', 'freshness': 4, 'qty': '1', 'unit': 'L', 'confidence': 0.9, 'groups': ['dairy', 'protein']}], 'tip': ''}
    mock_vision.return_value = json.dumps(payload)
    files = [('files', ('a.png', _tiny_png(), 'image/png'))]
    with client.stream('POST', '/ai/sessions', files=files, headers=auth_headers) as resp:
        assert resp.status_code == 200
        session = _read_ndjson_last(resp)
    sid = session['id']
    assert session['items'][0]['alert'] is not None
    milk_groups = {g['code'] for g in session['items'][0].get('identification_groups', [])}
    assert milk_groups == {'dairy', 'protein'}
    r = client.post(f'/ai/sessions/{sid}/confirm', headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body['status'] == 'confirmed'
    pantry = client.get('/pantry', headers=auth_headers).json()
    assert len(pantry) >= 1
    assert any((p['name'] == 'milk' for p in pantry))
    stats = client.get('/ai/training/stats', headers=auth_headers).json()
    assert stats['total_images'] >= 1
    assert stats['unique_products'] >= 1


@patch('ai_routes.groq_chat_vision_json')
def test_manual_item_patch_delete(mock_vision, client, auth_headers):
    mock_vision.return_value = json.dumps({'items': [], 'tip': ''})
    files = [('files', ('a.png', _tiny_png(), 'image/png'))]
    with client.stream('POST', '/ai/sessions', files=files, headers=auth_headers) as resp:
        session = _read_ndjson_last(resp)
    sid = session['id']
    r = client.post(f'/ai/sessions/{sid}/items', headers=auth_headers, json={'name': 'rice', 'freshness': 5, 'qty': '500', 'unit': 'g', 'identification_group_codes': ['pantry']})
    assert r.status_code == 201
    body = r.json()
    item_id = body['id']
    assert {g['code'] for g in body.get('identification_groups', [])} == {'pantry'}
    r = client.patch(f'/ai/sessions/{sid}/items/{item_id}', headers=auth_headers, json={'freshness': 3})
    assert r.status_code == 200
    assert r.json()['freshness'] == 3
    assert r.json()['alert'] is not None
    r = client.delete(f'/ai/sessions/{sid}/items/{item_id}', headers=auth_headers)
    assert r.status_code == 204


@patch('ai_routes.groq_configured', return_value=False)
@patch('ai_routes.groq_chat_vision_json')
def test_groq_recipes_503_without_key(mock_vision, _no_groq, client, auth_headers):
    # Vision still mocked so /sessions doesn't try to hit the real API
    mock_vision.return_value = json.dumps({'items': [{'name': 'milk', 'freshness': 4, 'qty': '1', 'unit': 'L', 'confidence': 0.9, 'groups': ['dairy']}], 'tip': ''})
    files = [('files', ('a.png', _tiny_png(), 'image/png'))]
    # _model_ready calls groq_configured() which is patched to False, so /sessions itself 503s.
    with client.stream('POST', '/ai/sessions', files=files, headers=auth_headers) as resp:
        assert resp.status_code == 503


@patch('ai_routes.groq_chat_json')
@patch('ai_routes.groq_chat_vision_json')
def test_groq_recipes_saves_recipes(mock_vision, mock_groq_chat, client, auth_headers):
    mock_vision.return_value = json.dumps({'items': [{'name': 'milk', 'freshness': 4, 'qty': '1', 'unit': 'L', 'confidence': 0.9, 'groups': ['dairy', 'protein']}], 'tip': ''})
    mock_groq_chat.return_value = json.dumps({'recipes': [{'name': 'Creamy soup', 'uses': ['milk'], 'extra': ['salt'], 'steps': ['Simmer'], 'minutes': 20}]})
    files = [('files', ('a.png', _tiny_png(), 'image/png'))]
    with client.stream('POST', '/ai/sessions', files=files, headers=auth_headers) as resp:
        session = _read_ndjson_last(resp)
    sid = session['id']
    r = client.post(f'/ai/sessions/{sid}/confirm', headers=auth_headers)
    assert r.status_code == 200
    r = client.post(f'/ai/sessions/{sid}/groq-recipes', headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body['recipes']) == 1
    assert body['recipes'][0]['name'] == 'Creamy soup'
    assert body['recipes'][0]['uses'] == ['milk']
    sess = client.get(f'/ai/sessions/{sid}', headers=auth_headers).json()
    assert len(sess['recipes']) >= 1


@patch('ai_routes.groq_chat_json')
@patch('ai_routes.groq_chat_vision_json')
def test_full_pipeline_mock_vision_then_groq_recipes(mock_vision, mock_groq_chat, client, auth_headers):
    mock_vision.return_value = json.dumps({'items': [{'name': 'eggs', 'freshness': 4, 'qty': '6', 'unit': None, 'confidence': 0.92, 'groups': ['protein']}, {'name': 'spinach', 'freshness': 3, 'qty': '200', 'unit': 'g', 'confidence': 0.85, 'groups': ['produce']}], 'tip': 'Use spinach soon'})
    mock_groq_chat.return_value = json.dumps({'recipes': [{'name': 'Spinach omelette', 'uses': ['eggs', 'spinach'], 'extra': ['butter', 'salt'], 'steps': ['Whisk eggs', 'Wilt spinach', 'Fold and cook'], 'minutes': 15}, {'name': 'Green scramble', 'uses': ['eggs', 'spinach'], 'extra': [], 'steps': ['Scramble with spinach'], 'minutes': 10}]})
    files = multipart_image_files(10)
    with client.stream('POST', '/ai/sessions', files=files, headers=auth_headers) as resp:
        assert resp.status_code == 200
        session = _read_ndjson_last(resp)
    assert session.get('status_msg') == 'done'
    assert len(session['images']) == 10
    names = {i['name'] for i in session['items']}
    assert names == {'eggs', 'spinach'}
    sid = session['id']
    r = client.post(f'/ai/sessions/{sid}/confirm', headers=auth_headers)
    assert r.status_code == 200
    r = client.post(f'/ai/sessions/{sid}/groq-recipes', headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body['recipes']) == 2
    assert body['recipes'][0]['name'] == 'Spinach omelette'
    sess = client.get(f'/ai/sessions/{sid}', headers=auth_headers).json()
    assert len(sess['recipes']) == 2
