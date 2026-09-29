"""DeepSeek Chat Completions（OpenAI 兼容）薄封装。"""

from __future__ import annotations

import os
from typing import Any

from src.env_load import load_dotenv, require_deepseek_api_key

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


def deepseek_settings() -> dict[str, str]:
    load_dotenv()
    return {
        "api_key": require_deepseek_api_key(),
        "base_url": (os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        "model": (os.environ.get("DEEPSEEK_MODEL") or DEFAULT_MODEL).strip(),
    }


def chat(
    messages: list[dict[str, str]],
    *,
    client: Any | None = None,
    thinking: bool = True,
    reasoning_effort: str = "high",
) -> str:
    """调用 chat.completions，只返回最终 content（不含思维链）。"""
    settings = deepseek_settings()
    if client is None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "未安装 openai 包。请在本仓执行：\n"
                "  uv pip install -r requirements.txt"
            ) from exc
        client = OpenAI(api_key=settings["api_key"], base_url=settings["base_url"])

    kwargs: dict[str, Any] = {
        "model": settings["model"],
        "messages": messages,
        "stream": False,
    }
    if thinking:
        kwargs["reasoning_effort"] = reasoning_effort
        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content
    if not content or not str(content).strip():
        raise RuntimeError("DeepSeek 返回空 content")
    return str(content).strip()
