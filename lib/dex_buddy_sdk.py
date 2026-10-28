"""Dex Buddy 插件 SDK 1.0.0。拷进插件 lib/ 后：
独立跑用 DEX_BUDDY_API_KEY 打 Dex Buddy 网关（开发者付钱）；
工作台里由 Node 注入 DEX_BUDDY_MODELS_URL，走宿主（谁用谁付钱）。
require_entitlement 在 Python 里始终直接返回；工作台真校验写在 index.js。
对照文档母版的 __version__，不一致就整文件再拷。不要把 Key 打进 zip。
"""

from __future__ import annotations

import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

__version__ = "1.0.0"
DEFAULT_BASE = "https://www.dexbuddy.app"
MISSING_KEY = (
    "独立运行需要环境变量 DEX_BUDDY_API_KEY（账号里的用户 API Key，dbh_sk_ 开头）。"
    "写进本机 .env，不要放进插件设置，也不要打进 zip。装进 Dex Buddy 后会改走宿主，扣使用者的积分。"
)


class DexModelsError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _env_map(env: dict[str, str] | None) -> dict[str, str]:
    return dict(os.environ if env is None else env)


def _trim(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


class _Completions:
    def __init__(self, client: "Models") -> None:
        self._client = client

    def create(self, body: Any, options: dict[str, Any] | None = None) -> Any:
        return self._client._post("/v1/chat/completions", body, options)


class _Chat:
    def __init__(self, client: "Models") -> None:
        self.completions = _Completions(client)


class _Billing:
    def __init__(self, client: "Models") -> None:
        self._client = client

    def quote(self, body: Any, options: dict[str, Any] | None = None) -> Any:
        return self._client._post("/v1/billing/quote", body, options)


class _Images:
    def __init__(self, client: "Models") -> None:
        self._client = client

    def generate(self, payload: dict[str, Any], options: dict[str, Any] | None = None) -> Any:
        return self._client._generate_image(payload, options)


class Models:
    def __init__(self, env: dict[str, str] | None = None) -> None:
        self._env = _env_map(env)
        self.chat = _Chat(self)
        self.billing = _Billing(self)
        self.images = _Images(self)

    def list(self) -> Any:
        return self._request("GET", "/v1/models")

    def _models_url(self) -> str:
        return _trim(self._env.get("DEX_BUDDY_MODELS_URL")).rstrip("/")

    def _gateway(self) -> str:
        return _trim(self._env.get("DEX_GATEWAY_BASE_URL")) or DEFAULT_BASE

    def _headers(self, options: dict[str, Any] | None, json_body: bool) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if json_body:
            headers["Content-Type"] = "application/json"
        models_url = self._models_url()
        if not models_url:
            key = _trim(self._env.get("DEX_BUDDY_API_KEY"))
            if not key:
                raise DexModelsError("UNAUTHORIZED", MISSING_KEY, 401)
            headers["Authorization"] = f"Bearer {key}"
        if options and isinstance(options.get("idempotencyKey"), str):
            token = options["idempotencyKey"].strip()
            if token:
                headers["Idempotency-Key"] = token
        return headers

    def _request(self, method: str, path: str, body: Any = None, options: dict[str, Any] | None = None) -> Any:
        base = self._models_url() or self._gateway().rstrip("/")
        url = f"{base}{path if path.startswith('/') else '/' + path}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers(options, body is not None))
        try:
            with _urlopen(req) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8") if err.fp else ""
            parsed: Any = None
            if raw.strip():
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = None
            raise _error_from_body(parsed, err.code) from err
        except urllib.error.URLError as err:
            raise DexModelsError("NETWORK_ERROR", str(err.reason or err), 0) from err

    def _post(self, path: str, body: Any, options: dict[str, Any] | None) -> Any:
        return self._request("POST", path, body, options)

    def _generate_image(self, payload: dict[str, Any], options: dict[str, Any] | None) -> Any:
        if self._models_url():
            return self._post("/images/generate", payload, options)
        model = _trim(payload.get("model"))
        output_path = _trim(payload.get("outputPath"))
        record = payload.get("input") if isinstance(payload.get("input"), dict) else {}
        prompt = _trim(record.get("prompt"))
        if not model:
            raise DexModelsError("INVALID_BODY", "缺少 model", 400)
        if not prompt:
            raise DexModelsError("INVALID_BODY", "缺少 prompt", 400)
        if not output_path or not os.path.isabs(output_path):
            raise DexModelsError("INVALID_BODY", "outputPath 必须是绝对路径", 400)
        local_images = [
            item.strip()
            for item in (record.get("input_images") or [])
            if isinstance(item, str) and item.strip()
        ]
        file_ids = []
        for index, file_path in enumerate(local_images):
            file_options = options
            if options and isinstance(options.get("idempotencyKey"), str) and options["idempotencyKey"].strip():
                file_options = {"idempotencyKey": f"{options['idempotencyKey'].strip()}:file:{index}"}
            file_ids.append(self._upload_reference(file_path, file_options))
        body: dict[str, Any] = {"model": model, "prompt": prompt}
        aspect = _trim(record.get("aspect_ratio"))
        if aspect:
            body["aspect_ratio"] = aspect
        if file_ids:
            body["fileIds"] = file_ids
        generated = self._post("/v1/images/generate", body, options)
        download_url = generated.get("downloadUrl") if isinstance(generated, dict) else None
        if not isinstance(download_url, str) or not download_url.strip():
            raise DexModelsError("BAD_RESPONSE", "网关生图结果无效", 502)
        try:
            with _urlopen(download_url) as response:
                data = response.read()
        except urllib.error.URLError as err:
            raise DexModelsError("NETWORK_ERROR", str(err.reason or err), 0) from err
        if not data:
            raise DexModelsError("BAD_RESPONSE", "生成图是空的", 502)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        model_out = generated.get("model") if isinstance(generated, dict) else model
        return {"status": "succeeded", "output": output_path, "model": model_out if isinstance(model_out, str) else model}

    def _upload_reference(self, file_path: str, options: dict[str, Any] | None) -> str:
        data = Path(file_path).read_bytes()
        if not data:
            raise DexModelsError("INVALID_BODY", f"参考图是空的：{file_path}", 400)
        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        issued = self._post(
            "/v1/files",
            {"contentType": content_type, "contentLength": len(data)},
            options,
        )
        if not isinstance(issued, dict):
            raise DexModelsError("BAD_RESPONSE", "网关 files 凭证无效", 502)
        upload_url = issued.get("uploadUrl")
        token = issued.get("token")
        key = issued.get("key")
        file_id = issued.get("id")
        if not all(isinstance(item, str) and item.strip() for item in (upload_url, token, key, file_id)):
            raise DexModelsError("BAD_RESPONSE", "网关 files 凭证无效", 502)
        boundary = "----DexBuddyForm"
        filename = os.path.basename(file_path) or "image"
        chunks = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"token\"\r\n\r\n{token}\r\n".encode("utf-8"),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"key\"\r\n\r\n{key}\r\n".encode("utf-8"),
            (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
            + data
            + b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
        req = urllib.request.Request(
            str(upload_url),
            data=b"".join(chunks),
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with _urlopen(req) as response:
                response.read()
        except urllib.error.HTTPError as err:
            raise DexModelsError("UPSTREAM_ERROR", f"参考图上传失败（{err.code}）", err.code) from err
        except urllib.error.URLError as err:
            raise DexModelsError("NETWORK_ERROR", str(err.reason or err), 0) from err
        return str(file_id)


def _error_from_body(body: Any, status: int) -> DexModelsError:
    record = body if isinstance(body, dict) else None
    nested = record.get("error") if record else None
    if isinstance(nested, dict) and isinstance(nested.get("message"), str) and nested["message"].strip():
        code = nested["code"] if isinstance(nested.get("code"), str) and nested["code"].strip() else "BAD_RESPONSE"
        return DexModelsError(code, nested["message"], status)
    if record and isinstance(record.get("error"), str) and record["error"].strip():
        code = record["code"] if isinstance(record.get("code"), str) and record["code"].strip() else "BAD_RESPONSE"
        return DexModelsError(code, record["error"], status)
    return DexModelsError("BAD_RESPONSE", f"网关请求失败（{status}）", status)


def _urlopen(req: urllib.request.Request | str, timeout: int = 120):
    url = req.full_url if isinstance(req, urllib.request.Request) else req
    handlers = []
    if "127.0.0.1" in url or "localhost" in url:
        # 本机代理不要走系统 HTTP_PROXY，否则工作台里的 Python 会卡住。
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    return opener.open(req, timeout=timeout)


def bind_models(env: dict[str, str] | None = None) -> Models:
    return Models(env)


def require_entitlement() -> None:
    return None
