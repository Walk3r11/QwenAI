"""Standalone accuracy check for Groq vision scan.

Usage:
  python scripts/test_groq_vision.py                 # scans all images in test_images/
  python scripts/test_groq_vision.py path/to/img.jpg # scans one or more specific images
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

from dotenv import load_dotenv
load_dotenv(_root / '.env')

from config import SCAN_PROMPT, GROQ_VISION_MODEL
from groq_client import groq_chat_vision_json, groq_configured


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    fence = re.search(r'```(?:json)?\s*(.*?)```', text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for i, ch in enumerate(text):
            if ch in '{[':
                try:
                    val, _ = json.JSONDecoder().raw_decode(text, i)
                    return val if isinstance(val, dict) else {'items': val}
                except json.JSONDecodeError:
                    continue
    return {}


def _mime(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in ('.jpg', '.jpeg'):
        return 'image/jpeg'
    if ext == '.png':
        return 'image/png'
    if ext == '.webp':
        return 'image/webp'
    return 'image/jpeg'


def _fmt_item(it: dict) -> str:
    name = it.get('name', '?')
    fresh = it.get('freshness', '?')
    qty = it.get('qty', '?')
    unit = it.get('unit') or ''
    conf = it.get('confidence')
    conf_s = f'{conf:.2f}' if isinstance(conf, (int, float)) else '?'
    groups = ','.join(it.get('groups') or [])
    return f'  • {name:<22} fresh={fresh}/5  qty={qty} {unit}  conf={conf_s}  groups=[{groups}]'


def scan_one(path: Path) -> None:
    print(f'\n=== {path.name} ({path.stat().st_size // 1024} KB) ===')
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode('ascii')
    t0 = time.perf_counter()
    try:
        raw = groq_chat_vision_json(
            system=SCAN_PROMPT,
            user_text='Scan this image and return the JSON described in the system prompt.',
            images=[(b64, _mime(path))],
            max_tokens=2560,
            temperature=0.2,
        )
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000
        print(f'  ERROR after {dt:.0f} ms: {e}')
        return
    dt = (time.perf_counter() - t0) * 1000
    print(f'  latency: {dt:.0f} ms   model: {GROQ_VISION_MODEL}')
    parsed = _parse_json(raw)
    items = parsed.get('items') or []
    if not items and isinstance(parsed, list):
        items = parsed
    tip = parsed.get('tip') if isinstance(parsed, dict) else None
    print(f'  items detected: {len(items)}')
    for it in items:
        if isinstance(it, dict):
            print(_fmt_item(it))
    if tip:
        print(f'  tip: {tip}')
    if not items:
        print('  raw response (first 600 chars):')
        print('  ' + raw[:600].replace('\n', '\n  '))


def main() -> int:
    if not groq_configured():
        print('ERROR: GROQ_API_KEY not set.')
        return 1
    args = sys.argv[1:]
    if args:
        paths = [Path(a) for a in args]
    else:
        paths = sorted((_root / 'test_images').glob('*'))
        paths = [p for p in paths if p.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')]
    if not paths:
        print('No images found. Drop some into test_images/ or pass paths as args.')
        return 1
    print(f'Scanning {len(paths)} image(s) with Groq vision model: {GROQ_VISION_MODEL}')
    total_t = time.perf_counter()
    for p in paths:
        if not p.is_file():
            print(f'!! skipped (not a file): {p}')
            continue
        scan_one(p)
    print(f'\nTotal wall time: {(time.perf_counter() - total_t) * 1000:.0f} ms')
    return 0


if __name__ == '__main__':
    sys.exit(main())
