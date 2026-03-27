#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_IMAGES = REPO_ROOT / 'test_images'
DEFAULT_BASE = 'https://qwenai-production.up.railway.app'
EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.JPG', '.JPEG', '.PNG'}

FALLBACK_ITEMS = [
    {'name': 'Cherry tomatoes', 'freshness': 7, 'qty': '200', 'unit': 'g', 'identification_group_codes': ['produce']},
    {'name': 'Chicken thighs', 'freshness': 6, 'qty': '4', 'unit': None, 'identification_group_codes': ['protein']},
    {'name': 'Greek yogurt', 'freshness': 8, 'qty': '500', 'unit': 'g', 'identification_group_codes': ['dairy', 'protein']},
]


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


def get_token(base: str, email: str | None, password: str | None) -> str:
    if email and password:
        r = requests.post(
            f'{base}/auth/login',
            json={'email': email.strip().lower(), 'password': password},
            timeout=60,
        )
        if r.status_code != 200:
            print(f'Login failed {r.status_code}: {r.text[:400]}', file=sys.stderr)
            sys.exit(1)
        return r.json()['access_token']
    suffix = uuid.uuid4().hex[:12]
    em = f'pc_scan_{suffix}@example.com'
    pw = f'Scan_{suffix}9Aa!'
    r = requests.post(
        f'{base}/auth/signup',
        json={'email': em, 'name': 'PC scan', 'password': pw},
        timeout=60,
    )
    if r.status_code in (200, 201):
        print(f'Signed up: {em}', file=sys.stderr)
        return r.json()['access_token']
    if r.status_code == 409:
        print('Signup conflict; set RAILWAY_EMAIL and RAILWAY_PASSWORD.', file=sys.stderr)
        sys.exit(1)
    print(f'Signup failed {r.status_code}: {r.text[:400]}', file=sys.stderr)
    sys.exit(1)


SCAN_TIMEOUT = (60, int(os.environ.get('RAILWAY_SCAN_READ_TIMEOUT', '86400')))


def stream_scan(base: str, token: str, paths: list[Path], chunked: bool=False) -> dict:
    headers = {'Authorization': f'Bearer {token}'}
    files = []
    for p in paths:
        files.append(
            ('files', (p.name, p.read_bytes(), mime_for(p))),
        )
    if not chunked:
        print('POST /ai/sessions?buffer=true (one JSON when done — avoids Railway cutting chunked streams)…', file=sys.stderr)
        r = requests.post(
            f'{base}/ai/sessions',
            params={'buffer': 'true'},
            headers=headers,
            files=files,
            timeout=SCAN_TIMEOUT,
        )
        if r.status_code != 200:
            print(f'Scan HTTP {r.status_code}: {r.text[:1200]}', file=sys.stderr)
            sys.exit(1)
        try:
            last = r.json()
        except json.JSONDecodeError:
            print(f'Not JSON: {r.text[:800]}', file=sys.stderr)
            sys.exit(1)
    else:
        print('POST /ai/sessions (NDJSON stream; may break behind proxies)…', file=sys.stderr)
        r = requests.post(
            f'{base}/ai/sessions',
            headers=headers,
            files=files,
            stream=True,
            timeout=SCAN_TIMEOUT,
        )
        if r.status_code != 200:
            print(f'Scan HTTP {r.status_code}: {r.text[:800]}', file=sys.stderr)
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
            print(f'Chunked stream cut off (proxy timeout?): {e}', file=sys.stderr)
            print('Retry without --chunked-stream (default uses ?buffer=true).', file=sys.stderr)
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
        print(f'  • Food: {name!r} | freshness {fr}/10 | qty {qty} {unit or ""}'.strip(), file=sys.stderr)
        print(f'    Categories: {cats}', file=sys.stderr)


def add_fallback_items(base: str, token: str, sid: int) -> None:
    h = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    print('\nVision returned no items — adding manual items to test categories + recipes…', file=sys.stderr)
    for row in FALLBACK_ITEMS:
        r = requests.post(f'{base}/ai/sessions/{sid}/items', headers=h, json=row, timeout=60)
        if r.status_code != 201:
            print(f'POST item failed {r.status_code}: {r.text[:400]}', file=sys.stderr)
            sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description='Full Railway test: scan → food + categories → confirm → Groq recipes')
    ap.add_argument('--max', type=int, default=10, help='max images (default 10)')
    ap.add_argument('--no-full', action='store_true', help='only run vision scan JSON to stdout')
    ap.add_argument('--strict-vision', action='store_true', help='do not add manual items if vision is empty')
    ap.add_argument('--chunked-stream', action='store_true', help='use NDJSON stream instead of buffer=true (often fails on Railway)')
    args = ap.parse_args()
    full = not args.no_full

    base = os.environ.get('RAILWAY_BASE_URL', DEFAULT_BASE).rstrip('/')
    paths = collect_images(args.max)
    print(f'Base: {base}\nImages ({len(paths)}): ' + ', '.join(p.name for p in paths), file=sys.stderr)

    token = get_token(
        base,
        os.environ.get('RAILWAY_EMAIL'),
        os.environ.get('RAILWAY_PASSWORD'),
    )

    data = stream_scan(base, token, paths, chunked=args.chunked_stream)
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
        if args.strict_vision:
            print('\nStrict mode: no items from vision — skipping confirm / Groq.', file=sys.stderr)
            print(json.dumps(session, indent=2))
            sys.exit(2)
        add_fallback_items(base, token, sid)
        session = fetch_session(base, token, sid)
        print_food_and_categories('After manual fallback items', session)

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
