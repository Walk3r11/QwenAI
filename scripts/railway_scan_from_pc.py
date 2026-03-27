#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import uuid
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from config import FRESHNESS_MAX

TEST_IMAGES = REPO_ROOT / 'test_images'
DEFAULT_BASE = 'https://qwenai-production.up.railway.app'
EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.JPG', '.JPEG', '.PNG'}

def _auth_timeout() -> tuple[float, float]:
    c = float(os.environ.get('RAILWAY_CONNECT_TIMEOUT', '20'))
    r = float(os.environ.get('RAILWAY_AUTH_READ_TIMEOUT', '180'))
    return (c, r)


def _health_timeout() -> tuple[float, float]:
    return (float(os.environ.get('RAILWAY_CONNECT_TIMEOUT', '20')), float(os.environ.get('RAILWAY_HEALTH_READ_TIMEOUT', '45')))


def collect_images(max_n: int) -> list[Path]:
    if not TEST_IMAGES.is_dir():
        print(f'Missing folder: {TEST_IMAGES}', file=sys.stderr)
        sys.exit(1)
    files = sorted(
        (p for p in TEST_IMAGES.iterdir() if p.is_file() and p.suffix in EXTS),
        key=lambda p: p.name.lower(),
    )
    if not files:
        print(f'No images in {TEST_IMAGES} (add .jpg / .png).', file=sys.stderr)
        sys.exit(1)
    return files[:max_n]


def mime_for(p: Path) -> str:
    s = p.suffix.lower()
    if s in ('.jpg', '.jpeg'):
        return 'image/jpeg'
    if s == '.png':
        return 'image/png'
    if s == '.webp':
        return 'image/webp'
    if s == '.gif':
        return 'image/gif'
    return 'application/octet-stream'


def ping_health(base: str) -> dict:
    url = f'{base}/health'
    t = _health_timeout()
    print(f'GET {url} (connect≤{t[0]:.0f}s read≤{t[1]:.0f}s)…', file=sys.stderr)
    try:
        r = requests.get(url, timeout=t)
    except requests.exceptions.ConnectTimeout as e:
        print(f'Connect timeout — check URL/VPN/firewall: {e}', file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.ConnectionError as e:
        print(f'Connection error — host unreachable or TLS failure: {e}', file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.ReadTimeout as e:
        print(f'Health read timeout (server accepted connection but did not respond in time): {e}', file=sys.stderr)
        print('Try RAILWAY_HEALTH_READ_TIMEOUT=120 or redeploy; Neon/Railway cold start can exceed 45s.', file=sys.stderr)
        sys.exit(1)
    if r.status_code != 200:
        print(f'Health HTTP {r.status_code}: {r.text[:500]}', file=sys.stderr)
        sys.exit(1)
    data = r.json()
    print(f'  ok: db_connected={data.get("db_connected")} ai_enabled={data.get("ai_enabled")} allow_pc_script_signup={data.get("allow_pc_script_signup")}', file=sys.stderr)
    return data


def get_token(base: str, email: str | None, password: str | None, health: dict) -> str:
    raw = os.environ.get('RAILWAY_BEARER_TOKEN', '').strip()
    if raw:
        print('Using RAILWAY_BEARER_TOKEN (no login request).', file=sys.stderr)
        return raw.removeprefix('Bearer ').strip()

    t = _auth_timeout()
    pc = os.environ.get('RAILWAY_PC_SCAN_SECRET', '').strip()
    if pc:
        print(f'POST {base}/auth/pc-scan-token…', file=sys.stderr)
        try:
            pr = requests.post(f'{base}/auth/pc-scan-token', headers={'Authorization': f'Bearer {pc}'}, timeout=t)
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            print(f'{e}', file=sys.stderr)
            sys.exit(1)
        if pr.status_code == 200:
            return pr.json()['access_token']
        if pr.status_code == 404:
            print('Server has no PC_SCAN_SHARED_SECRET set (Railway Variables). Match RAILWAY_PC_SCAN_SECRET to the same value.', file=sys.stderr)
            sys.exit(1)
        print(f'pc-scan-token {pr.status_code}: {pr.text[:400]}', file=sys.stderr)
        sys.exit(1)

    if email and password:
        print(f'POST {base}/auth/login (connect≤{t[0]:.0f}s read≤{t[1]:.0f}s)…', file=sys.stderr)
        try:
            r = requests.post(
                f'{base}/auth/login',
                json={'email': email.strip().lower(), 'password': password},
                timeout=t,
            )
        except requests.exceptions.ConnectTimeout as e:
            print(f'Login connect timeout: {e}', file=sys.stderr)
            sys.exit(1)
        except requests.exceptions.ReadTimeout as e:
            print(
                f'Login read timeout after {t[1]:.0f}s — the server did connect; DB or app is slow (cold start).\n'
                'Raise RAILWAY_AUTH_READ_TIMEOUT (e.g. 300) or hit /health in a browser once to wake the service.',
                file=sys.stderr,
            )
            sys.exit(1)
        if r.status_code != 200:
            print(f'Login failed {r.status_code}: {r.text[:400]}', file=sys.stderr)
            if r.status_code == 401:
                print('Use your real registered email and password for this deployment (not example placeholders).', file=sys.stderr)
            if r.status_code == 403 and 'verified' in (r.text or '').lower():
                print('Complete email verification for this account, then retry.', file=sys.stderr)
            sys.exit(1)
        return r.json()['access_token']

    if not health.get('allow_pc_script_signup'):
        print(
            'Set ALLOW_PC_SCRIPT_SIGNUP=true on Railway (Variables) and redeploy so /auth/signup accepts pc_<hex>@example.com with a JWT, '
            'or set RAILWAY_PC_SCAN_SECRET / RAILWAY_EMAIL+PASSWORD / RAILWAY_BEARER_TOKEN.',
            file=sys.stderr,
        )
        sys.exit(1)

    for _ in range(8):
        em = f'pc_{uuid.uuid4().hex}@example.com'
        pw = f'Pc_{secrets.token_urlsafe(24)}1aA'
        print(f'POST {base}/auth/signup ({em})…', file=sys.stderr)
        try:
            sr = requests.post(f'{base}/auth/signup', json={'email': em, 'name': 'PC scan', 'password': pw}, timeout=t)
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            print(f'{e}', file=sys.stderr)
            sys.exit(1)
        if sr.status_code == 201:
            data = sr.json()
            if data.get('access_token'):
                return data['access_token']
            print('Signup returned no JWT. Set ALLOW_PC_SCRIPT_SIGNUP=true on the API and redeploy.', file=sys.stderr)
            sys.exit(1)
        if sr.status_code != 409:
            print(f'Signup failed {sr.status_code}: {sr.text[:400]}', file=sys.stderr)
            sys.exit(1)
    print('Signup kept returning 409.', file=sys.stderr)
    sys.exit(1)


SCAN_TIMEOUT = (60, int(os.environ.get('RAILWAY_SCAN_READ_TIMEOUT', '86400')))


def stream_scan(base: str, token: str, paths: list[Path]) -> dict:
    headers = {'Authorization': f'Bearer {token}'}
    files = []
    for p in paths:
        files.append(
            ('files', (p.name, p.read_bytes(), mime_for(p))),
        )
    print('POST /ai/sessions (NDJSON stream; first bytes immediate — use long RAILWAY_SCAN_READ_TIMEOUT if needed)…', file=sys.stderr)
    r = requests.post(
        f'{base}/ai/sessions',
        headers=headers,
        files=files,
        stream=True,
        timeout=SCAN_TIMEOUT,
    )
    if r.status_code != 200:
        print(f'Scan HTTP {r.status_code}: {r.text[:1200]}', file=sys.stderr)
        sys.exit(1)
    buf = []
    got = 0
    try:
        for chunk in r.iter_content(chunk_size=65536):
            if chunk:
                got += len(chunk)
                if got <= 65536:
                    print(f'  stream… {got} bytes', file=sys.stderr)
                buf.append(chunk.decode('utf-8', errors='replace'))
    except requests.exceptions.ChunkedEncodingError as e:
        print(f'Chunked stream cut off (proxy idle/total timeout?): {e}', file=sys.stderr)
        print('Try raising RAILWAY_SCAN_READ_TIMEOUT or reduce image count/size.', file=sys.stderr)
        sys.exit(1)
    text = ''.join(buf)
    lines = [ln for ln in text.split('\n') if ln.strip()]
    if not lines:
        print('Empty stream from /ai/sessions', file=sys.stderr)
        sys.exit(1)
    for ln in lines[:-1]:
        try:
            o = json.loads(ln)
            if o.get('status') == 'error':
                print(f'  NDJSON error line: {o}', file=sys.stderr)
        except json.JSONDecodeError:
            pass
    last = json.loads(lines[-1])
    if last.get('status') == 'error' or last.get('status_msg') not in (None, 'done'):
        print(f'Vision pipeline did not finish OK: {last}', file=sys.stderr)
        sys.exit(1)
    if last.get('status_msg') != 'done' and last.get('id') is None:
        print(f'Unexpected response: {last}', file=sys.stderr)
        sys.exit(1)
    return last


def fetch_session(base: str, token: str, sid: int) -> dict:
    h = {'Authorization': f'Bearer {token}'}
    r = requests.get(f'{base}/ai/sessions/{sid}', headers=h, timeout=60)
    if r.status_code != 200:
        print(f'GET session {r.status_code}: {r.text[:400]}', file=sys.stderr)
        sys.exit(1)
    return r.json()


def print_food_and_categories(label: str, session: dict) -> None:
    print(f'\n=== {label} ===', file=sys.stderr)
    items = session.get('items') or []
    if not items:
        print('  (no items)', file=sys.stderr)
        return
    for it in items:
        name = it.get('name', '?')
        fr = it.get('freshness')
        qty = it.get('qty')
        unit = it.get('unit')
        groups = it.get('identification_groups') or []
        cats = ', '.join((f"{g.get('code')} ({g.get('label', '')})" for g in groups)) or '(no categories)'
        print(f'  • Food: {name!r} | freshness {fr}/{FRESHNESS_MAX} | qty {qty} {unit or ""}'.strip(), file=sys.stderr)
        print(f'    Categories: {cats}', file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description='Full Railway test: scan → food + categories → confirm → Groq recipes')
    ap.add_argument('--max', type=int, default=10, help='max images (default 10)')
    ap.add_argument('--no-full', action='store_true', help='only run vision scan JSON to stdout')
    ap.add_argument('--email', default=None)
    ap.add_argument('--password', default=None)
    args = ap.parse_args()
    full = not args.no_full

    base = os.environ.get('RAILWAY_BASE_URL', DEFAULT_BASE).rstrip('/')
    paths = collect_images(args.max)
    print(f'Base: {base}\nImages ({len(paths)}): ' + ', '.join(p.name for p in paths), file=sys.stderr)

    health = ping_health(base)

    email = args.email if args.email is not None else os.environ.get('RAILWAY_EMAIL')
    password = args.password if args.password is not None else os.environ.get('RAILWAY_PASSWORD')
    token = get_token(base, email, password, health)

    data = stream_scan(base, token, paths)
    sid = data.get('id')
    if not sid:
        print(json.dumps(data, indent=2))
        sys.exit(1)

    if not full:
        print(json.dumps(data, indent=2))
        return

    session = fetch_session(base, token, sid)
    print_food_and_categories('After vision scan', session)

    if not session.get('items'):
        print('\nERROR: Vision returned zero items — scan pipeline is not OK; refusing to confirm or call Groq.', file=sys.stderr)
        print(json.dumps(session, indent=2))
        sys.exit(2)

    h = {'Authorization': f'Bearer {token}'}
    cr = requests.post(f'{base}/ai/sessions/{sid}/confirm', headers=h, timeout=(60, 300))
    print('\n--- POST /ai/sessions/…/confirm ---', file=sys.stderr)
    print(f'{cr.status_code}', file=sys.stderr)
    if cr.status_code != 200:
        print(cr.text[:800], file=sys.stderr)
        sys.exit(1)

    gr = requests.post(f'{base}/ai/sessions/{sid}/groq-recipes', headers=h, timeout=(60, 300))
    print('\n--- POST /ai/sessions/…/groq-recipes (recipes) ---', file=sys.stderr)
    print(f'{gr.status_code}', file=sys.stderr)
    if gr.status_code != 200:
        print(gr.text[:1200], file=sys.stderr)
        sys.exit(1)
    body = gr.json()
    recipes = body.get('recipes') or []
    print(f'\n=== Groq recipes ({len(recipes)}) ===', file=sys.stderr)
    for i, rec in enumerate(recipes, 1):
        print(f'  {i}. {rec.get("name")} — {rec.get("minutes")} min', file=sys.stderr)
        print(f'     uses: {rec.get("uses")}', file=sys.stderr)
        print(f'     extra: {rec.get("extra")}', file=sys.stderr)
        st = rec.get('steps')
        if isinstance(st, list) and st:
            preview = st[:2] if len(st) > 2 else st
            print(f'     steps (preview): {preview}', file=sys.stderr)
        else:
            print(f'     steps: {st}', file=sys.stderr)
    print('\n--- Full JSON (recipes response) ---')
    print(json.dumps(body, indent=2))


if __name__ == '__main__':
    main()
