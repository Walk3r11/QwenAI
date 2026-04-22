import json
from unittest.mock import patch
from config import FRESHNESS_MAX
from scan_upload_helpers import multipart_image_files
from test_ai_api import _read_ndjson_last


@patch('ai_routes.groq_chat_json')
@patch('ai_routes.groq_chat_vision_json')
def test_ten_images_full_stack_mocked(mock_vision, mock_groq_chat, client, auth_headers):
    mock_vision.return_value = json.dumps({'items': [{'name': 'salmon', 'freshness': 5, 'qty': '2', 'unit': 'fillets', 'confidence': 0.91, 'groups': ['protein']}, {'name': 'asparagus', 'freshness': 4, 'qty': '1', 'unit': 'bunch', 'confidence': 0.88, 'groups': ['produce']}, {'name': 'lemon', 'freshness': 5, 'qty': '2', 'unit': None, 'confidence': 0.85, 'groups': ['produce']}], 'tip': 'Use salmon within 48h.'})
    mock_groq_chat.return_value = json.dumps({'recipes': [{'name': 'Salmon with asparagus', 'uses': ['salmon', 'asparagus', 'lemon'], 'extra': ['olive oil', 'salt'], 'steps': ['Roast asparagus', 'Pan-sear salmon', 'Finish with lemon'], 'minutes': 35}]})
    files = multipart_image_files(10)
    with client.stream('POST', '/ai/sessions', files=files, headers=auth_headers) as resp:
        assert resp.status_code == 200, resp.text
        session = _read_ndjson_last(resp)
    assert session.get('status_msg') == 'done'
    assert len(session['images']) == 10
    assert {i['name'] for i in session['items']} == {'salmon', 'asparagus', 'lemon'}
    sid = session['id']
    detail = client.get(f'/ai/sessions/{sid}', headers=auth_headers)
    assert detail.status_code == 200
    assert len(detail.json()['images']) == 10
    r = client.post(f'/ai/sessions/{sid}/confirm', headers=auth_headers)
    assert r.status_code == 200
    pantry = client.get('/pantry', headers=auth_headers).json()
    assert any((p['name'] == 'salmon' for p in pantry))
    stats = client.get('/ai/training/stats', headers=auth_headers).json()
    assert stats['total_images'] >= 10
    assert stats['unique_products'] >= 1
    r = client.post(f'/ai/sessions/{sid}/groq-recipes', headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body['recipes']) == 1
    assert body['recipes'][0]['name'] == 'Salmon with asparagus'
    sess = client.get(f'/ai/sessions/{sid}', headers=auth_headers).json()
    assert len(sess['recipes']) == 1
    assert len(sess['images']) == 10
    health = client.get('/health').json()
    assert health.get('ok') is True
    assert 'groq_configured' in health
    assert health.get('freshness_max') == FRESHNESS_MAX
