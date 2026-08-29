# path: app/llm/list_models.py
from __future__ import annotations

import sys
import httpx

from app.config import get_settings


def list_models() -> int:
    settings = get_settings()
    if not settings.api_key:
        sys.stderr.write("Error: GEMINI_API_KEY (or RG_API_KEY) is not set.\n")
        return 1

    url = "https://generativelanguage.googleapis.com/v1beta/models"
    headers = {
        "x-goog-api-key": settings.api_key,
    }

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers=headers)
    except Exception as exc:
        sanitized_msg = str(exc).replace(settings.api_key, "[REDACTED]")
        sys.stderr.write(f"Error connecting to Google Gemini API: {sanitized_msg}\n")
        return 1

    if response.status_code != 200:
        sanitized_body = response.text.replace(settings.api_key, "[REDACTED]")[:200]
        sys.stderr.write(f"Error: API returned status {response.status_code}: {sanitized_body}\n")
        return 1

    try:
        data = response.json()
        models = data.get("models", [])
    except Exception:
        sys.stderr.write("Error: Failed to parse models response JSON.\n")
        return 1

    header_fmt = "{:<32} {:<28} {:<18} {:<18} {}"
    print(header_fmt.format("Name", "Display Name", "Input Limit", "Output Limit", "Supported Methods"))
    print("-" * 120)

    for m in models:
        name = m.get("name", "")
        display_name = m.get("displayName", "")
        input_limit = str(m.get("inputTokenLimit", ""))
        output_limit = str(m.get("outputTokenLimit", ""))
        methods = ", ".join(m.get("supportedGenerationMethods", []))
        print(header_fmt.format(name, display_name, input_limit, output_limit, methods))

    return 0


if __name__ == "__main__":
    sys.exit(list_models())
