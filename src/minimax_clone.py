"""本账号音色克隆：上传样音、克隆、再用同步合成激活。不读取包内 voice_id。"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable

from src.minimax_tts import API_BASE, DEFAULT_MODEL, require_api_key, synthesize_to_mp3

_VOICE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{6,254}[A-Za-z0-9]$")
ACTIVATE_TEXT = "你好，这是一段音色激活。"

PostMultipart = Callable[[str, dict[str, str], dict[str, tuple[str, bytes, str]], dict[str, str]], dict[str, Any]]
PostJson = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]


def new_voice_id() -> str:
    """字母开头，长度与字符集符合 MiniMax 自定义 voice_id。"""
    return "V" + uuid.uuid4().hex


def build_clone_body(file_id: int, voice_id: str) -> dict[str, Any]:
    voice = str(voice_id or "").strip()
    if not _VOICE_ID_RE.match(voice):
        raise ValueError("voice_id 不合法")
    return {
        "file_id": int(file_id),
        "voice_id": voice,
        "model": DEFAULT_MODEL,
        "need_noise_reduction": True,
        "need_volume_normalization": False,
    }


def _encode_multipart(
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    boundary = "----Manju" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
        )
    for key, (filename, data, mime) in files.items():
        header = (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"{key}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n"
        )
        chunks.append(header.encode() + data + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def _default_upload(url: str, fields: dict[str, str], files: dict[str, tuple[str, bytes, str]], headers: dict[str, str]) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    from src.minimax_tts import _assert_ok, _loads

    body, boundary = _encode_multipart(fields, files)
    sent = dict(headers)
    sent["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(url, data=body, headers=sent, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = _loads(resp.read().decode("utf-8"), getattr(resp, "status", 200))
    except urllib.error.HTTPError as exc:
        payload = _loads(exc.read().decode("utf-8", errors="replace"), exc.code)
        msg = (payload.get("base_resp") or {}).get("status_msg") or f"HTTP {exc.code}"
        raise RuntimeError(f"MiniMax HTTP {exc.code}: {msg}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"MiniMax 请求失败: {exc.reason}") from exc
    _assert_ok(payload, "MiniMax POST /v1/files/upload")
    return payload


def _default_post(url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    from src.minimax_tts import _assert_ok, _loads

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = _loads(resp.read().decode("utf-8"), getattr(resp, "status", 200))
    except urllib.error.HTTPError as exc:
        payload = _loads(exc.read().decode("utf-8", errors="replace"), exc.code)
        msg = (payload.get("base_resp") or {}).get("status_msg") or f"HTTP {exc.code}"
        raise RuntimeError(f"MiniMax HTTP {exc.code}: {msg}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"MiniMax 请求失败: {exc.reason}") from exc
    _assert_ok(payload, "MiniMax POST /v1/voice_clone")
    return payload


def upload_clone_audio(
    path: Path,
    *,
    api_key: str | None = None,
    upload: PostMultipart | None = None,
) -> int:
    key = require_api_key(api_key)
    audio = Path(path)
    data = audio.read_bytes()
    send = upload or _default_upload
    payload = send(
        f"{API_BASE}/v1/files/upload",
        {"purpose": "voice_clone"},
        {"file": (audio.name, data, "audio/mpeg")},
        {"Authorization": f"Bearer {key}"},
    )
    file_id = (payload.get("file") or {}).get("file_id")
    if not isinstance(file_id, int):
        raise RuntimeError("上传样音没有返回 file_id")
    return file_id


def clone_voice(
    file_id: int,
    voice_id: str,
    *,
    api_key: str | None = None,
    post_json: PostJson | None = None,
) -> dict[str, Any]:
    key = require_api_key(api_key)
    body = build_clone_body(file_id, voice_id)
    send = post_json or _default_post
    return send(
        f"{API_BASE}/v1/voice_clone",
        body,
        {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )


def activate_voice(
    voice_id: str,
    dest: Path,
    *,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    speak: Callable[..., dict[str, Any]] | None = None,
) -> None:
    """预览不算激活。短句同步合成后这个 voice_id 才会留下来。"""
    fn = speak or synthesize_to_mp3
    fn(voice_id=voice_id, text=ACTIVATE_TEXT, out_path=dest, model=model, api_key=api_key)
