import base64
import json
import os
import re

import requests
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from config import ANALYZE_PROMPT, LLAMA_MODEL, LLAMA_URL
from models import User
from schemas import ImageScanResponse, ScanItemOut
from security import get_current_user

router = APIRouter(prefix="/ai", tags=["ai"])


def _extract_json_text(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("{") and raw.endswith("}"):
        return raw
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        return match.group(0)
    raise ValueError("No JSON object found in model output.")


def _coerce_scan_response(raw_text: str) -> ImageScanResponse:
    json_text = _extract_json_text(raw_text)
    payload = json.loads(json_text)
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("Model output does not contain 'items' list.")
    parsed_items: list[ScanItemOut] = []
    for i in items:
        if not isinstance(i, dict):
            continue
        name = str(i.get("name", "")).strip()
        if not name:
            continue
        quantity = i.get("quantity")
        unit = i.get("unit")
        confidence = i.get("confidence")
        parsed_items.append(
            ScanItemOut(
                name=name,
                quantity=float(quantity) if quantity is not None else None,
                unit=(
                    str(unit).strip()
                    if unit is not None and str(unit).strip()
                    else None
                ),
                confidence=float(confidence) if confidence is not None else None,
            )
        )
    return ImageScanResponse(items=parsed_items, raw=raw_text)


@router.post("/analyze")
async def analyze(file: UploadFile = File(...), _: User = Depends(get_current_user)):
    if not os.path.exists("/models/qwen.gguf") or not os.path.exists(
        "/models/mmproj.gguf"
    ):
        raise HTTPException(
            status_code=503,
            detail="Model files not found. Set MODEL_URL and MMPROJ_URL in Railway variables and redeploy.",
        )

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Upload an image file.")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file.")

    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{file.content_type};base64,{image_b64}"
    payload = {
        "model": LLAMA_MODEL,
        "stream": True,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": ANALYZE_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0.2,
    }

    try:
        r = requests.post(LLAMA_URL, json=payload, timeout=600, stream=True)
    except requests.RequestException as e:
        raise HTTPException(
            status_code=502, detail=f"Failed to reach model server: {e}"
        ) from e

    if r.status_code >= 400:
        raise HTTPException(
            status_code=502, detail={"model_status": r.status_code, "body": r.text}
        )

    return StreamingResponse(
        r.iter_lines(decode_unicode=True), media_type="text/event-stream"
    )


@router.post("/scan", response_model=ImageScanResponse)
async def scan_image(file: UploadFile = File(...), _: User = Depends(get_current_user)):
    if not os.path.exists("/models/qwen.gguf") or not os.path.exists(
        "/models/mmproj.gguf"
    ):
        raise HTTPException(
            status_code=503,
            detail="Model files not found. Set MODEL_URL and MMPROJ_URL in Railway variables and redeploy.",
        )

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Upload an image file.")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file.")

    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{file.content_type};base64,{image_b64}"
    scan_prompt = (
        "Detect visible food ingredients from this image and return strict JSON only. "
        'Output: {"items":[{"name":string,"quantity":number|null,"unit":string|null,"confidence":number|null}]}. '
        "Use lowercase names. If uncertain, still include best guess with lower confidence."
    )
    payload = {
        "model": LLAMA_MODEL,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": scan_prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    try:
        r = requests.post(LLAMA_URL, json=payload, timeout=600)
    except requests.RequestException as e:
        raise HTTPException(
            status_code=502, detail=f"Failed to reach model server: {e}"
        ) from e

    if r.status_code >= 400:
        raise HTTPException(
            status_code=502, detail={"model_status": r.status_code, "body": r.text}
        )

    try:
        model_json = r.json()
        content = model_json["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            content = json.dumps(content)
        return _coerce_scan_response(content)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"Failed to parse model output: {e}",
                "raw_model_response": r.text,
            },
        ) from e
