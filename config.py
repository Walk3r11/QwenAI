import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))

LLAMA_URL = os.getenv("LLAMA_URL", "http://127.0.0.1:8080/v1/chat/completions")
LLAMA_MODEL = os.getenv("LLAMA_MODEL", "qwen2.5-vl")
ANALYZE_PROMPT = os.getenv(
    "ANALYZE_PROMPT",
    "Identify the food in this image. Be specific (dish name). Return JSON: {\"dish\": string, \"confidence\": 0-1, \"notes\": string}.",
)
