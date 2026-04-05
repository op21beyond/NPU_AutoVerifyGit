"""OpenAI-compatible Chat Completions for company LLM profiles (env-based)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class LLMProfile:
    id: str
    label: str
    base_url_env: str
    api_key_env: str
    model_env: str
    default_model: str


DEFAULT_PROFILES: Tuple[LLMProfile, ...] = (
    LLMProfile(
        "llm1",
        "LLM 서비스 1",
        "COMPANY_LLM_1_BASE_URL",
        "COMPANY_LLM_1_API_KEY",
        "COMPANY_LLM_1_MODEL",
        "gpt-4o",
    ),
    LLMProfile(
        "llm2",
        "LLM 서비스 2",
        "COMPANY_LLM_2_BASE_URL",
        "COMPANY_LLM_2_API_KEY",
        "COMPANY_LLM_2_MODEL",
        "gpt-4o",
    ),
    LLMProfile(
        "llm3",
        "LLM 서비스 3",
        "COMPANY_LLM_3_BASE_URL",
        "COMPANY_LLM_3_API_KEY",
        "COMPANY_LLM_3_MODEL",
        "gpt-4o",
    ),
    LLMProfile(
        "llm4",
        "LLM 서비스 4",
        "COMPANY_LLM_4_BASE_URL",
        "COMPANY_LLM_4_API_KEY",
        "COMPANY_LLM_4_MODEL",
        "gpt-4o",
    ),
    LLMProfile(
        "llm5",
        "LLM 서비스 5",
        "COMPANY_LLM_5_BASE_URL",
        "COMPANY_LLM_5_API_KEY",
        "COMPANY_LLM_5_MODEL",
        "gpt-4o",
    ),
)


def resolve_profile(profile: LLMProfile) -> Tuple[str, str, str]:
    base = (os.environ.get(profile.base_url_env) or "").strip().rstrip("/")
    key = (os.environ.get(profile.api_key_env) or "").strip()
    model = (os.environ.get(profile.model_env) or "").strip() or profile.default_model
    return base, key, model


def chat_completion(
    profile: LLMProfile,
    messages: List[Dict[str, str]],
    *,
    timeout_s: float = 180.0,
) -> Tuple[Any, Optional[Dict[str, Any]]]:
    base, key, model = resolve_profile(profile)
    if not base:
        return None, {
            "error": {
                "message": f"Base URL not set: {profile.base_url_env}",
                "type": "configuration_error",
            }
        }

    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("Install the 'openai' package: pip install openai") from e

    client = OpenAI(api_key=key or "not-needed", base_url=base, timeout=timeout_s)
    try:
        resp = client.chat.completions.create(model=model, messages=messages)
        return resp, None
    except Exception as e:
        err_body: Dict[str, Any]
        try:
            err_body = {"error": {"message": str(e), "type": type(e).__name__}}
            body = getattr(e, "body", None)
            if body is not None:
                if isinstance(body, dict):
                    err_body = body
                else:
                    err_body["error"]["raw"] = str(body)
        except Exception:
            err_body = {"error": {"message": str(e), "type": type(e).__name__}}
        return None, err_body


def assistant_content_from_response(resp: Any) -> str:
    if resp is None:
        return ""
    try:
        return (resp.choices[0].message.content or "").strip()
    except (AttributeError, IndexError, TypeError):
        return ""


def response_to_full_json(resp: Any) -> str:
    if resp is None:
        return ""
    try:
        if hasattr(resp, "model_dump_json"):
            return resp.model_dump_json(indent=2)
        if hasattr(resp, "model_dump"):
            return json.dumps(resp.model_dump(), indent=2, default=str)
    except Exception:
        pass
    return json.dumps({"repr": repr(resp)}, indent=2)
