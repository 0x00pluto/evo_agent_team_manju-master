"""用自建应用的 App ID / Secret 读取飞书 wiki 或 docx 正文。

操作台发给别人用，不跑在本机 Agent 会话里，所以只走开放平台公开接口。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import quote

OPEN_BASE = "https://open.feishu.cn"
_TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
_DOC_RE = re.compile(r"https?://[^/\s]*feishu\.cn/(wiki|docx)/([A-Za-z0-9]+)")

MISSING_CREDS = "请在设置里填写飞书 App ID 和 App Secret"
FORBIDDEN = (
    "飞书拒绝读取。请确认应用已开通「查看新版文档」和「查看知识库」，"
    "并把应用加进这篇文档或对应知识空间。"
)
_FORBIDDEN_CODES = {99991663, 99991668, 99991672}

HttpFn = Callable[[str, str, dict[str, str] | None, dict[str, Any] | None], dict[str, Any]]


def credentials(env: dict[str, str] | None = None) -> tuple[str, str]:
    source = os.environ if env is None else env
    app_id = str(source.get("FEISHU_APP_ID") or "").strip()
    secret = str(source.get("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not secret:
        raise RuntimeError(MISSING_CREDS)
    return app_id, secret


def document_ref(url: str) -> tuple[str, str]:
    """返回 (wiki|docx, token)。链接必须整段就是一篇文档。"""
    match = _DOC_RE.search(url or "")
    if not match or match.group(0) != (url or "").strip():
        raise ValueError("不是飞书文档链接")
    return match.group(1), match.group(2)


def _loads(raw: str, status: int) -> dict[str, Any]:
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"飞书返回不是 JSON（HTTP {status}）") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("飞书返回不是 JSON")
    return payload


def _ensure_ok(payload: dict[str, Any], status: int = 200) -> dict[str, Any]:
    code = payload.get("code", 0)
    msg = str(payload.get("msg") or payload.get("message") or "").strip()
    denied = status == 403 or code in _FORBIDDEN_CODES or "permission" in msg.lower() or "权限" in msg
    if denied and (status == 403 or code not in (0, None)):
        detail = f"（{msg}）" if msg else ""
        raise RuntimeError(FORBIDDEN + detail)
    if code not in (0, None):
        raise RuntimeError(f"飞书读取失败: {msg or code}")
    return payload


def _default_http(
    method: str,
    url: str,
    headers: dict[str, str] | None,
    body: dict[str, Any] | None,
) -> dict[str, Any]:
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json; charset=utf-8")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status = getattr(resp, "status", 200)
            payload = _loads(resp.read().decode("utf-8"), status)
    except urllib.error.HTTPError as exc:
        status = exc.code
        payload = _loads(exc.read().decode("utf-8", errors="replace"), status)
        return _ensure_ok(payload, status)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"飞书读取失败: {exc.reason}") from exc
    return _ensure_ok(payload, status)


def _auth_header(token_body: dict[str, Any]) -> dict[str, str]:
    access = str(token_body.get("tenant_access_token") or "").strip()
    if not access:
        raise RuntimeError("飞书没有返回访问令牌")
    return {"Authorization": f"Bearer {access}"}


def _docx_id(kind: str, token: str, call: HttpFn, auth: dict[str, str]) -> str:
    if kind == "docx":
        return token
    node_body = call(
        "GET",
        f"{OPEN_BASE}/open-apis/wiki/v2/spaces/get_node?token={quote(token)}",
        auth,
        None,
    )
    _ensure_ok(node_body)
    node = (node_body.get("data") or {}).get("node") or {}
    obj_type = str(node.get("obj_type") or "")
    obj_token = str(node.get("obj_token") or "").strip()
    if obj_type != "docx" or not obj_token:
        shown = obj_type or "未知"
        raise RuntimeError(f"这篇知识库文档不是新版文档（docx），当前类型是 {shown}")
    return obj_token


def fetch_document(
    url: str,
    *,
    http: HttpFn | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """读取一篇 wiki 或 docx 的纯文本。wiki 会先解析成 docx。"""
    kind, token = document_ref(url)
    app_id, secret = credentials(env)
    call = http or _default_http
    token_body = call(
        "POST",
        OPEN_BASE + _TOKEN_PATH,
        {"Content-Type": "application/json; charset=utf-8"},
        {"app_id": app_id, "app_secret": secret},
    )
    _ensure_ok(token_body)
    auth = _auth_header(token_body)
    doc_id = _docx_id(kind, token, call, auth)
    content_body = call(
        "GET",
        f"{OPEN_BASE}/open-apis/docx/v1/documents/{quote(doc_id, safe='')}/raw_content",
        auth,
        None,
    )
    _ensure_ok(content_body)
    content = (content_body.get("data") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("飞书文档没有正文")
    return content
