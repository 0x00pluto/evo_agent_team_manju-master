"""Dex Buddy Chat Completions 薄封装。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from src.env_load import load_dotenv, plugin_root, require_dex_buddy_api_key

FALLBACK_CHAT_MODEL = "dexbuddy-chat"


def _ensure_sdk_path() -> None:
    candidates = (plugin_root() / "lib", Path(__file__).resolve().parents[1] / "lib")
    for lib in candidates:
        text = str(lib)
        if lib.is_dir() and text not in sys.path:
            sys.path.insert(0, text)
            return
    fallback = str(plugin_root() / "lib")
    if fallback not in sys.path:
        sys.path.insert(0, fallback)


_ensure_sdk_path()

from dex_buddy_sdk import bind_models  # noqa: E402


def pick_chat_model(listed: Any) -> str:
    data = listed.get("data") if isinstance(listed, dict) else None
    if not isinstance(data, list):
        data = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("kind") != "chat":
            continue
        model_id = item.get("id")
        if isinstance(model_id, str) and model_id.strip():
            return model_id.strip()
    return FALLBACK_CHAT_MODEL


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str) and item.strip():
            parts.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts).strip()


def _message_content(response: Any) -> str:
    if not isinstance(response, dict):
        raise RuntimeError("对话返回空 content")
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("对话返回空 content")
    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("对话返回空 content")
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    text = _content_text(message.get("content"))
    if not text:
        raise RuntimeError("对话返回空 content")
    return text


def chat(
    messages: list[dict[str, str]],
    *,
    response_format: dict[str, str] | None = None,
    max_tokens: int | None = None,
) -> str:
    """调用 chat.completions，只返回最终 content。"""
    load_dotenv()
    require_dex_buddy_api_key()
    models = bind_models()
    listed = models.list()
    model = pick_chat_model(listed)
    body: dict[str, Any] = {"model": model, "messages": messages}
    if response_format is not None:
        body["response_format"] = response_format
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    response = models.chat.completions.create(body)
    return _message_content(response)
