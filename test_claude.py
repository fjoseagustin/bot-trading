"""Test directo de la API de Claude con override=True."""
import os
import sys

bot_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, bot_dir)

from dotenv import load_dotenv
load_dotenv(os.path.join(bot_dir, ".env"), override=True)

key = os.getenv("ANTHROPIC_API_KEY", "")
print(f"Longitud key: {len(key)}")
print(f"Empieza con sk-ant-api03-: {key.startswith('sk-ant-api03-')}")
print(f"Primeros 20 chars: {key[:20]}")
print(f"Ultimos 5 chars (repr): {repr(key[-5:])}")
print()

import anthropic

client = anthropic.Anthropic(api_key=key)
try:
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=20,
        messages=[{"role": "user", "content": "Responde solo: OK"}]
    )
    print(f"EXITO: {resp.content[0].text}")
except anthropic.AuthenticationError as e:
    print(f"AUTH ERROR 401: {e}")
except anthropic.APIStatusError as e:
    print(f"API STATUS {e.status_code}: {e.message}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
