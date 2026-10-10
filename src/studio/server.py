"""stdlib HTTP：操作台页面、任务、媒体与打开配音文件夹。"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import subprocess
import sys
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from src.feishu_doc import fetch_document
from src.studio.bench import list_recent, load_bench, validate_theme, voice_dir, voice_mp3
from src.studio.compile_episode import split_sections
from src.studio.jobs import JobManager, resynth_line

STATIC_DIR = Path(__file__).resolve().parent / "static"
_FEISHU_RE = re.compile(
    r"https?://[^\s)>\]]*feishu\.cn/(?:wiki|docx)/[A-Za-z0-9]+"
)
_CHUNK = 1024 * 1024
_MAX_JSON = 1_500_000
_MAX_UPLOAD = 2 * 1024 * 1024


def feishu_url_in(text: str) -> str:
    m = _FEISHU_RE.search(text or "")
    return m.group(0) if m else ""


def explicit_feishu_url(payload: dict[str, Any]) -> str:
    """只认 feishu_url 字段。说明正文里出现的链接不算来源。"""
    raw = payload.get("feishu_url")
    if not isinstance(raw, str):
        return ""
    url = raw.strip()
    found = feishu_url_in(url)
    if not url or found != url:
        return ""
    return url


def section_choices(script: str, **kwargs: Any) -> list[dict[str, Any]]:
    rows = []
    for section in split_sections(script, **kwargs):
        rows.append(
            {
                "index": section["index"],
                "title": section["title"],
                "preview": section["preview"],
                "mode": section["mode"],
                "start": section.get("start") or "",
            }
        )
    if not rows:
        raise ValueError("脚本里没有【】段落")
    return rows


def fetch_feishu(url: str) -> str:
    if not feishu_url_in(url):
        raise ValueError("不是飞书文档链接")
    return fetch_document(url)


def read_staged(root: Path, staged: str) -> str:
    base = (root / "temp" / "studio_uploads").resolve()
    target = Path(staged).expanduser().resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise ValueError("上传文件无效")
    return target.read_text(encoding="utf-8")


_SCRIPT_SUFFIXES = {".md", ".markdown", ".txt"}


def load_script(root: Path, payload: dict[str, Any]) -> str:
    """飞书链接、已暂存上传、页内脚本文本三者只留一个。"""
    staged = str(payload.get("staged_path") or "").strip()
    url = explicit_feishu_url(payload)
    raw_text = payload.get("script_text")
    text = raw_text if isinstance(raw_text, str) else ""
    has_text = bool(text.strip())
    if sum(bool(item) for item in (staged, url, has_text)) > 1:
        raise ValueError("飞书链接和上传脚本只保留后选的一个")
    if staged:
        return read_staged(root, staged)
    if url:
        return fetch_feishu(url)
    if has_text:
        filename = str(payload.get("filename") or "").strip()
        if filename and Path(filename).suffix.lower() not in _SCRIPT_SUFFIXES:
            raise ValueError("只接收 .md / .txt 脚本")
        if len(text.encode("utf-8")) > _MAX_UPLOAD:
            raise ValueError("请上传 2MB 以内的文本脚本")
        return text
    if str(payload.get("feishu_url") or "").strip():
        raise ValueError("请只填写飞书文档链接")
    raise ValueError("请上传脚本，或填写飞书文档链接")


def reveal_voice(root: Path, theme: str) -> dict[str, Any]:
    folder = voice_dir(root, theme)
    if not folder.is_dir():
        raise FileNotFoundError("还没有配音文件夹")
    if sys.platform == "win32":
        # 资源管理器在成功打开文件夹时也经常返回非 0，不能拿退出码判断失败。
        subprocess.run(["explorer", str(folder)], check=False)
        return {"ok": True, "path": str(folder)}
    proc = subprocess.run(["open", str(folder)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "无法打开文件夹").strip())
    return {"ok": True, "path": str(folder)}


def voiceover_zip_bytes(root: Path, theme: str) -> tuple[str, bytes]:
    folder = voice_dir(root, theme)
    if not folder.is_dir():
        raise FileNotFoundError("还没有配音")
    names = sorted(folder.glob("*.mp3"))
    if not names:
        raise FileNotFoundError("文件夹里没有 MP3")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for mp3 in names:
            zf.write(mp3, arcname=mp3.name)
    safe = validate_theme(theme)
    return f"{safe}-voiceover.zip", buf.getvalue()


def read_voice(root: Path, theme: str, filename: str) -> dict[str, str]:
    target = voice_mp3(root, theme, filename)
    return {
        "file": target.name,
        "mime": "audio/mpeg",
        "base64": base64.b64encode(target.read_bytes()).decode("ascii"),
    }


def download_zip(root: Path, theme: str) -> dict[str, str]:
    filename, body = voiceover_zip_bytes(root, theme)
    return {
        "filename": filename,
        "mime": "application/zip",
        "base64": base64.b64encode(body).decode("ascii"),
    }


class StudioHandler(BaseHTTPRequestHandler):
    manager: JobManager
    root: Path

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        __import__("sys").stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(code, data, "application/json; charset=utf-8")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        if length > _MAX_JSON:
            raise ValueError("请求过大")
        data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("JSON 必须是对象")
        return data

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path in ("/", "/index.html"):
            self._send(200, (STATIC_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/recent":
            self._json(200, {"recent": list_recent(self.root)})
            return
        if path.startswith("/api/jobs/") and path.count("/") == 3:
            job = self.manager.get(path.rsplit("/", 1)[-1])
            if job is None:
                self._json(404, {"error": "无此任务"})
                return
            self._json(200, job.to_dict())
            return
        bench = re.fullmatch(r"/api/bench/([^/]+)", path)
        if bench:
            try:
                self._json(200, load_bench(self.root, bench.group(1)))
            except FileNotFoundError as exc:
                self._json(404, {"error": str(exc)})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            return
        zipped = re.fullmatch(r"/api/voiceover/([^/]+)\.zip", path)
        if zipped:
            self._send_zip(zipped.group(1))
            return
        if path.startswith("/media/"):
            self._serve_media(path[len("/media/") :])
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/api/stage":
                self._stage()
                return
            if path == "/api/preview":
                self._preview()
                return
            if path == "/api/jobs":
                self._create_job()
                return
            if path == "/api/reveal":
                self._reveal()
                return
            if path == "/api/voiceover/resynth":
                self._resynth()
                return
            self._json(404, {"error": "not found"})
        except FileNotFoundError as exc:
            self._json(404, {"error": str(exc)})
        except RuntimeError as exc:
            code = 409 if "进行中" in str(exc) else 400
            self._json(code, {"error": str(exc)})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": str(exc)})

    def _stage(self) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0 or length > _MAX_UPLOAD:
            raise ValueError("请上传 2MB 以内的文本脚本")
        raw_name = unquote(self.headers.get("X-Filename") or "script.md")
        suffix = Path(raw_name).suffix.lower()
        if suffix not in (".md", ".markdown", ".txt"):
            raise ValueError("只接收 .md / .txt 脚本")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(raw_name).name).strip("-") or "script.md"
        dest_dir = self.root / "temp" / "studio_uploads" / __import__("uuid").uuid4().hex[:12]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / safe
        remaining = length
        with dest.open("wb") as out:
            while remaining > 0:
                chunk = self.rfile.read(min(_CHUNK, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)
        self._json(201, {"path": str(dest.resolve()), "filename": dest.name})

    def _preview(self) -> None:
        payload = self._read_json()
        script = load_script(self.root, payload)
        self._json(200, {"sections": section_choices(script)})

    def _create_job(self) -> None:
        payload = self._read_json()
        script = load_script(self.root, payload)
        sections = payload.get("sections")
        if not isinstance(sections, list):
            raise ValueError("请为每一段选择分镜或只配音")
        job = self.manager.create(script, sections)
        self._json(201, job.to_dict())

    def _resynth(self) -> None:
        payload = self._read_json()
        result = resynth_line(
            self.root,
            str(payload.get("theme") or ""),
            str(payload.get("id") or ""),
            str(payload.get("text") or ""),
        )
        self._json(200, result)

    def _reveal(self) -> None:
        payload = self._read_json()
        self._json(200, reveal_voice(self.root, str(payload.get("theme") or "")))

    def _send_zip(self, theme: str) -> None:
        try:
            filename, body = voiceover_zip_bytes(self.root, theme)
        except FileNotFoundError as exc:
            self._json(404, {"error": str(exc)})
            return
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        self._send(
            200,
            body,
            "application/zip",
            {"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    def _serve_media(self, rel: str) -> None:
        rel = rel.lstrip("/")
        parts = [p for p in rel.split("/") if p]
        if not parts or any(p in (".", "..") for p in parts):
            self._json(400, {"error": "非法路径"})
            return
        try:
            theme = validate_theme(parts[0])
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        base = (self.root / "output" / theme).resolve()
        target = (base.joinpath(*parts[1:])).resolve() if len(parts) > 1 else base
        if not target.is_relative_to(base) or not target.is_file():
            self._json(404, {"error": "文件不存在"})
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        size = target.stat().st_size
        range_hdr = self.headers.get("Range")
        if range_hdr and range_hdr.startswith("bytes="):
            spec = range_hdr[6:].strip()
            start_s, _, end_s = spec.partition("-")
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else size - 1
            end = min(end, size - 1)
            if start < 0 or start > end:
                self.send_response(416)
                self.end_headers()
                return
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with target.open("rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(_CHUNK, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with target.open("rb") as f:
            while True:
                chunk = f.read(_CHUNK)
                if not chunk:
                    break
                self.wfile.write(chunk)


def make_handler(manager: JobManager, root: Path) -> type[BaseHTTPRequestHandler]:
    class Bound(StudioHandler):
        pass

    Bound.manager = manager
    Bound.root = root
    return Bound


def serve(root: Path, *, host: str = "127.0.0.1", port: int = 8767) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("拒绝非本机绑定")
    root = Path(root).resolve()
    manager = JobManager(root)
    httpd = ThreadingHTTPServer((host, port), make_handler(manager, root))
    return httpd
