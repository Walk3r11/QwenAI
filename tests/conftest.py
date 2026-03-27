import json
import os
import sys
import tempfile
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('JWT_SECRET', 'test-secret-key-at-least-32-characters-long')
os.environ.setdefault('ENABLE_AI', 'true')
_tmp = tempfile.mkdtemp()
Path(_tmp, 'qwen.gguf').write_bytes(b'stub')
Path(_tmp, 'mmproj.gguf').write_bytes(b'stub')
os.environ.setdefault('MODEL_DIR', _tmp)
import pytest
from fastapi.testclient import TestClient
from main import app

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture
def auth_headers(client):
    r = client.post('/auth/signup', json={'email': 'test-ai@example.com', 'name': 'AI Tester', 'password': 'Testpass123'})
    if r.status_code == 409:
        r = client.post('/auth/login', json={'email': 'test-ai@example.com', 'password': 'Testpass123'})
    assert r.status_code in (200, 201), r.text
    token = r.json()['access_token']
    return {'Authorization': f'Bearer {token}'}