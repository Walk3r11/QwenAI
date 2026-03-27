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


def _noop_send_verification_email(*args, **kwargs):
    pass


import email_service

email_service.send_verification_email = _noop_send_verification_email

import pytest
from sqlalchemy import select
from db import SessionLocal
from fastapi.testclient import TestClient
from models import User
from main import app

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture
def auth_headers(client):
    email = 'test-ai@example.com'
    password = 'Testpass123'
    r = client.post('/auth/signup', json={'email': email, 'name': 'AI Tester', 'password': password})
    if r.status_code == 409:
        with SessionLocal() as db:
            u = db.scalar(select(User).where(User.email == email))
            if u and not u.is_verified and u.verification_code:
                client.post('/auth/verify', json={'email': email, 'code': u.verification_code})
        r = client.post('/auth/login', json={'email': email, 'password': password})
    else:
        assert r.status_code == 201, r.text
        with SessionLocal() as db:
            u = db.scalar(select(User).where(User.email == email))
            assert u and u.verification_code
            code = u.verification_code
        r = client.post('/auth/verify', json={'email': email, 'code': code})
        assert r.status_code == 200, r.text
    if r.status_code != 200:
        r = client.post('/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200, r.text
    token = r.json()['access_token']
    return {'Authorization': f'Bearer {token}'}