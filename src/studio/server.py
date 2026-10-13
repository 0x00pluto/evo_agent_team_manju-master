"""stdlib HTTP：操作台页面、任务、媒体与打开配音文件夹。"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import subprocess
import sys
import threading
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from src.feishu_doc import fetch_document
from src.studio.bench import list_recent, load_bench, validate_theme, voice_dir, voice_mp3
from src.studio.compile_episode import display_speaker, prepare_script
from src.studio.jobs import JobManager, resynth_line
from src.studio.audio_sample import SampleError, prepare_sample
from src.studio.voice_slots import (
    add_slot,
    apply_cast_defaults,
    bind_speaker,
    cast_view,
    ensure_key,
    load_slots,
    minimax_ready,
    perform_clone,
    public_slot,
    recover_slots,
    sample_file,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
_FEISHU_RE = re.compile(
    r"https?://[^\s)>\]]*feishu\.cn/(?:wiki|docx)/[A-Za-z0-9]+"
)
_CHUNK = 1024 * 1024
_MAX_JSON = 1_500_000
_MAX_UPLOAD = 2 * 1024 * 1024
_MAX_MEDIA = 20 * 1024 * 1024


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


def section_lines(section: dict[str, Any]) -> list[dict[str, str]]:
    """交给页面核对的口播。空名在这里写成旁白，全文不截断。"""
    rows: list[dict[str, str]] = []
    for item in section.get("items") or []:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        rows.append(
            {
                "speaker": display_speaker(str(item.get("speaker") or "")),
                "text": text,
            }
        )
    return rows


def preview_payload(script: str, **kwargs: Any) -> dict[str, Any]:
    """按 split_with 切段。未指定时用程序。开始任务应提交这里的 script_text。"""
    raw_mode = kwargs.get("split_with")
    split_with = raw_mode if raw_mode in ("program", "model") else "program"
    canonical, sections = prepare_script(
        script,
        split_with=split_with,
        chat_fn=kwargs.get("chat_fn"),
    )
    rows = []
    for section in sections:
        rows.append(
            {
                "index": section["index"],
                "title": section["title"],
                "preview": section["preview"],
                "mode": section["mode"],
                "start": section.get("start") or "",
                "lines": section_lines(section),
            }
        )
    if not rows:
        raise ValueError("没能把脚本整理成分段")
    return {"sections": rows, "script_text": canonical}


def section_choices(script: str, **kwargs: Any) -> list[dict[str, Any]]:
    return preview_payload(script, **kwargs)["sections"]


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


def launch_work(manager: JobManager, work: Any) -> None:
    manager.acquire()

    def run() -> None:
        try:
            work()
        except Exception:
            pass
        finally:
            manager.release()

    threading.Thread(target=run, daemon=True).start()


def write_media_bytes(root: Path, filename: str, data: bytes) -> Path:
    if not data or len(data) > _MAX_MEDIA:
        raise SampleError("文件大于 20MB，不能克隆")
    suffix = Path(filename).suffix.lower()
    if suffix not in (".mp4", ".m4v", ".mov", ".mkv", ".mp3", ".m4a", ".wav"):
        raise SampleError("只接收 MP4，或 mp3 / m4a / wav 音轨")
    dest_dir = Path(root) / "temp" / "voice-clone" / uuid.uuid4().hex[:12]
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / (Path(filename).name or "sample.mp4")
    dest.write_bytes(data)
    return dest


def preflight_slot(data_root: Path, code_root: Path, slot_id: str, upload: Path | None) -> dict[str, Any]:
    ensure_key()
    slots = load_slots(data_root, code_root)
    found = next((slot for slot in slots if slot.get("id") == slot_id), None)
    if found is None:
        raise ValueError("没有这个声音")
    src = upload if upload is not None else sample_file(found, data_root, code_root)
    prepare_sample(src, Path(data_root) / "temp" / "voice-clone" / uuid.uuid4().hex[:12])
    shown = public_slot(found)
    shown["status"] = "cloning"
    shown["status_label"] = "生成中"
    shown["selectable"] = False
    return shown


def queue_clone(manager: JobManager, data_root: Path, code_root: Path, slot_id: str, upload: Path | None = None) -> dict[str, Any]:
    shown = preflight_slot(data_root, code_root, slot_id, upload)
    launch_work(manager, lambda: perform_clone(data_root, code_root, slot_id, upload_path=upload))
    return {"slot": shown}


def queue_add(manager: JobManager, data_root: Path, code_root: Path, name: str, upload: Path) -> dict[str, Any]:
    ensure_key()
    slot = add_slot(data_root, code_root, name, upload)
    slot_id = str(slot["id"])
    launch_work(manager, lambda: perform_clone(data_root, code_root, slot_id))
    shown = public_slot(slot)
    shown["status"] = "cloning"
    shown["status_label"] = "生成中"
    shown["selectable"] = False
    return {"slot": shown}


def _with_cast(root: Path, code_root: Path, theme: str, bench: dict[str, Any]) -> dict[str, Any]:
    slots = load_slots(root, code_root)
    payload = dict(bench)
    payload["cast"] = cast_view(apply_cast_defaults(root, theme, slots), slots)
    payload["minimax_ready"] = minimax_ready()
    return payload


class StudioHandler(BaseHTTPRequestHandler):
    manager: JobManager
    root: Path
    code_root: Path

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
        if path == "/api/voice-slots":
            slots = load_slots(self.root, self.code_root)
            self._json(200, {"slots": [public_slot(slot) for slot in slots], "minimax_ready": minimax_ready()})
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
                theme = bench.group(1)
                payload = load_bench(self.root, theme, code_root=self.code_root)
                self._json(200, _with_cast(self.root, self.code_root, theme, payload))
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
            if path == "/api/voiceover/generate":
                self._generate_voice()
                return
            if path == "/api/voice-slots/bind":
                self._bind_slot()
                return
            if path == "/api/voice-slots/clone":
                self._clone_slot()
                return
            if path == "/api/voice-slots/replace":
                self._replace_slot()
                return
            if path == "/api/voice-slots/add":
                self._add_slot()
                return
            self._json(404, {"error": "not found"})
        except SampleError as exc:
            self._json(400, {"error": str(exc)})
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
        self._json(200, preview_payload(script, split_with=payload.get("split_with")))

    def _create_job(self) -> None:
        payload = self._read_json()
        script = load_script(self.root, payload)
        sections = payload.get("sections")
        if not isinstance(sections, list):
            raise ValueError("请为每一段选择「生成分镜」或「只配音」")
        job = self.manager.create(script, sections)
        self._json(201, job.to_dict())

    def _read_media(self) -> tuple[str, Path]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0 or length > _MAX_MEDIA:
            raise SampleError("文件大于 20MB，不能克隆")
        raw_name = unquote(self.headers.get("X-Filename") or "sample.mp4")
        suffix = Path(raw_name).suffix.lower()
        if suffix not in (".mp4", ".m4v", ".mov", ".mkv", ".mp3", ".m4a", ".wav"):
            raise SampleError("只接收 MP4，或 mp3 / m4a / wav 音轨")
        dest_dir = self.root / "temp" / "voice-clone" / uuid.uuid4().hex[:12]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / (Path(raw_name).name or "sample.mp4")
        remaining = length
        with dest.open("wb") as out:
            while remaining > 0:
                chunk = self.rfile.read(min(_CHUNK, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)
        return raw_name, dest

    def _generate_voice(self) -> None:
        payload = self._read_json()
        job = self.manager.start_voice(str(payload.get("theme") or ""))
        self._json(201, job.to_dict())

    def _bind_slot(self) -> None:
        payload = self._read_json()
        theme = str(payload.get("theme") or "")
        rows = bind_speaker(
            self.root,
            theme,
            str(payload.get("speaker") or ""),
            str(payload.get("slot_id") or ""),
            load_slots(self.root, self.code_root),
        )
        view = cast_view(rows, load_slots(self.root, self.code_root))
        self._json(200, view)

    def _clone_slot(self) -> None:
        payload = self._read_json()
        slot_id = str(payload.get("id") or "").strip()
        self._json(202, queue_clone(self.manager, self.root, self.code_root, slot_id))

    def _replace_slot(self) -> None:
        slot_id = unquote(self.headers.get("X-Slot-Id") or "").strip()
        if not slot_id:
            raise ValueError("没有这个声音")
        _name, dest = self._read_media()
        self._json(202, queue_clone(self.manager, self.root, self.code_root, slot_id, dest))

    def _add_slot(self) -> None:
        name = unquote(self.headers.get("X-Slot-Name") or "").strip()
        _filename, dest = self._read_media()
        self._json(202, queue_add(self.manager, self.root, self.code_root, name, dest))

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


def make_handler(manager: JobManager, root: Path, code_root: Path | None = None) -> type[BaseHTTPRequestHandler]:
    class Bound(StudioHandler):
        pass

    Bound.manager = manager
    Bound.root = root
    Bound.code_root = Path(code_root).resolve() if code_root is not None else root
    return Bound


def serve(root: Path, *, host: str = "127.0.0.1", port: int = 8767) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("拒绝非本机绑定")
    root = Path(root).resolve()
    recover_slots(root, root)
    manager = JobManager(root)
    httpd = ThreadingHTTPServer((host, port), make_handler(manager, root))
    httpd.studio_manager = manager  # type: ignore[attr-defined]
    return httpd
