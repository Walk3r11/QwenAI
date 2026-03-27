import json
import os
import pytest
pytestmark = pytest.mark.skipif(not (os.getenv('GROQ_API_KEY') or '').strip(), reason='Set GROQ_API_KEY in the environment to run live Groq tests')

def test_groq_chat_json_minimal():
    from groq_client import groq_chat_json
    raw = groq_chat_json('You output only valid JSON objects, no markdown.', 'Return exactly: {"ping":"pong"}', temperature=0, max_tokens=64)
    data = json.loads(raw)
    assert data.get('ping') == 'pong'