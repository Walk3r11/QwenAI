import base64
import os

import requests
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from config import ANALYZE_PROMPT, LLAMA_MODEL, LLAMA_URL
from models import User
from security import get_current_user

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/analyze")
async def analyze(file: UploadFile = File(...), _: User = Depends(get_current_user)):
    if not os.path.exists("/models/qwen.gguf") or not os.path.exists("/models/mmproj.gguf"):
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
        r = requests.post(LLAMA_URL, json=payload, timeout=180)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach model server: {e}") from e

    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail={"model_status": r.status_code, "body": r.text})
    return r.json()
