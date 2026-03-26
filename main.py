import base64
import os

import requests
from fastapi import FastAPI, File, HTTPException, UploadFile

app = FastAPI(title="SnapChef Backend", version="1.0.0")

LLAMA_URL = os.getenv("LLAMA_URL", "http://127.0.0.1:8080/v1/chat/completions")
MODEL = os.getenv("LLAMA_MODEL", "qwen2.5-vl")
PROMPT = os.getenv(
    "ANALYZE_PROMPT",
    "Identify the food in this image. Be specific (dish name). Return JSON: {\"dish\": string, \"confidence\": 0-1, \"notes\": string}.",
)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Upload an image file.")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file.")

    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{file.content_type};base64,{image_b64}"

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0.2,
    }

    try:
        r = requests.post(LLAMA_URL, json=payload, timeout=120)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach model server: {e}") from e

    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail={"model_status": r.status_code, "body": r.text})

    return r.json()
