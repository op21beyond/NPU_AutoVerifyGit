"""OpenAI Chat Completions JSON-object helper (shared by Stage2-style stages)."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional


def openai_chat_json_object(
    *,
    system_prompt: str,
    user_message: str,
    model: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout_s: float = 120.0,
) -> Dict[str, Any]:
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Export it or pass api_key= for OpenAI extraction mode."
        )
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("The 'openai' package is required. Install: pip install openai") from e

    client_kwargs: Dict[str, Any] = {"api_key": key, "timeout": timeout_s}
    if base_url:
        client_kwargs["base_url"] = base_url.rstrip("/")

    client = OpenAI(**client_kwargs)
    completion = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    text = completion.choices[0].message.content or "{}"
    text = re.sub(r"^\s*```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```\s*$", "", text.strip())
    payload = json.loads(text)
    if not isinstance(payload, dict):
        return {}
    return payload
