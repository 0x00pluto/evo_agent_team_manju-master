"""MiniMax 国际站同步配音。单句口播远短于 5000 字，不走异步长文。"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

API_BASE = "https://api.minimax.io"
SYNC_CHAR_LIMIT = 5000
DEFAULT_MODEL = "speech-2.8-hd"
DEFAULT_LANGUAGE_BOOST = "Chinese"

PostJson = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]
FetchBytes = Callable[[str], bytes]


def require_api_key(api_key: str | None = None) -> str:
    key = (api_key if api_key is not None else os.environ.get("MINIMAX_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("缺少 MINIMAX_API_KEY")
    return key


def _loads(raw: str, status: int) -> dict[str, Any]:
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"MiniMax 响应非 JSON (HTTP {status})") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"MiniMax 响应非 JSON (HTTP {status})")
    return payload


def _assert_ok(payload: dict[str, Any], context: str) -> None:
    base = payload.get("base_resp") or {}
    code = base.get("status_code")
    if code is not None and code != 0:
        msg = base.get("status_msg") or "unknown"
        raise RuntimeError(f"{context} 失败: status_code={code}, status_msg={msg}")


def _default_post(url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            status = getattr(resp, "status", 200)
            payload = _loads(resp.read().decode("utf-8"), status)
    except urllib.error.HTTPError as exc:
        payload = _loads(exc.read().decode("utf-8", errors="replace"), exc.code)
        msg = (payload.get("base_resp") or {}).get("status_msg") or f"HTTP {exc.code}"
        raise RuntimeError(f"MiniMax HTTP {exc.code}: {msg}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"MiniMax 请求失败: {exc.reason}") from exc
    if status >= 400:
        msg = (payload.get("base_resp") or {}).get("status_msg") or f"HTTP {status}"
        raise RuntimeError(f"MiniMax HTTP {status}: {msg}")
    _assert_ok(payload, "MiniMax POST /v1/t2a_v2")
    return payload


def _default_fetch(url: str) -> bytes:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            if getattr(resp, "status", 200) >= 400:
                raise RuntimeError(f"下载音频失败 HTTP {resp.status}")
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"下载音频失败 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"下载音频失败: {exc.reason}") from exc


def build_sync_body(voice_id: str, text: str, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "text": text,
        "stream": False,
        "output_format": "url",
        "language_boost": DEFAULT_LANGUAGE_BOOST,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": 1,
            "vol": 1,
            "pitch": 0,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
    }


def _write_audio(audio: str, out_path: Path, fetch_bytes: FetchBytes) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if audio.startswith("http"):
        out_path.write_bytes(fetch_bytes(audio))
        return
    try:
        data = bytes.fromhex(audio)
    except ValueError as exc:
        raise RuntimeError("同步合成返回的音频无法解码") from exc
    if not data:
        raise RuntimeError("同步合成未返回 audio")
    out_path.write_bytes(data)


def synthesize_to_mp3(
    *,
    voice_id: str,
    text: str,
    out_path: Path,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    post_json: PostJson | None = None,
    fetch_bytes: FetchBytes | None = None,
) -> dict[str, Any]:
    """调用 t2a_v2，把 URL 或 hex 音频写成 MP3。"""
    voice = str(voice_id or "").strip()
    spoken = str(text or "")
    dest = Path(out_path)
    if not voice:
        raise RuntimeError("缺少 voiceId")
    if not spoken.strip():
        raise RuntimeError("配音文本为空")
    if len(spoken) > SYNC_CHAR_LIMIT:
        raise RuntimeError(f"单句超过 {SYNC_CHAR_LIMIT} 字，当前只支持同步合成")
    key = require_api_key(api_key)
    body = build_sync_body(voice, spoken, model or DEFAULT_MODEL)
    post = post_json or _default_post
    payload = post(
        f"{API_BASE}/v1/t2a_v2",
        body,
        {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    _assert_ok(payload, "MiniMax POST /v1/t2a_v2")
    audio = (payload.get("data") or {}).get("audio")
    if not isinstance(audio, str) or not audio:
        raise RuntimeError("同步合成未返回 audio")
    _write_audio(audio, dest, fetch_bytes or _default_fetch)
    usage = (payload.get("extra_info") or {}).get("usage_characters")
    return {
        "outPath": str(dest),
        "mode": "sync",
        "usageCharacters": usage if usage is not None else len(spoken),
        "voiceId": voice,
        "model": body["model"],
    }
