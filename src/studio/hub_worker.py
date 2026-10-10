"""Hub 插件的常驻进程：stdin 一行请求，stdout 一行响应。

任务仍由 JobManager 的后台线程跑。createJob 写完响应就返回，页面再来问 getJob。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

from src.env_load import apply_plugin_settings, data_root, load_dotenv, plugin_root
from src.studio.bench import list_recent, load_bench
from src.studio.jobs import JobManager, resynth_line
from src.studio.server import (
    download_zip,
    load_script,
    read_voice,
    reveal_voice,
    section_choices,
)

class StudioSession:
    def __init__(
        self,
        root: Path,
        manager: JobManager | None = None,
        *,
        data_root: Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.data_root = Path(data_root).resolve() if data_root is not None else self.root
        self.manager = manager or JobManager(self.data_root, code_root=self.root)

    def dispatch(self, method: str, params: dict[str, Any] | None) -> Any:
        payload = params if isinstance(params, dict) else {}
        if method == "preview":
            script = load_script(self.data_root, payload)
            return {"sections": section_choices(script)}
        if method == "createJob":
            script = load_script(self.data_root, payload)
            sections = payload.get("sections")
            if not isinstance(sections, list):
                raise ValueError("请为每一段选择分镜或只配音")
            return self.manager.create(script, sections).to_dict()
        if method == "getJob":
            job = self.manager.get(str(payload.get("id") or ""))
            if job is None:
                raise FileNotFoundError("无此任务")
            return job.to_dict()
        if method == "recent":
            return {"recent": list_recent(self.data_root)}
        if method == "bench":
            return load_bench(self.data_root, str(payload.get("theme") or ""), code_root=self.root)
        if method == "resynth":
            return resynth_line(
                self.data_root,
                str(payload.get("theme") or ""),
                str(payload.get("id") or ""),
                str(payload.get("text") or ""),
                code_root=self.root,
            )
        if method == "reveal":
            return reveal_voice(self.data_root, str(payload.get("theme") or ""))
        if method == "readVoice":
            return read_voice(
                self.data_root,
                str(payload.get("theme") or ""),
                str(payload.get("file") or ""),
            )
        if method == "downloadZip":
            return download_zip(self.data_root, str(payload.get("theme") or ""))
        raise ValueError("没有这个方法")


def write_message(stdout: TextIO, message: dict[str, Any]) -> None:
    stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    stdout.flush()


def serve_stdio(
    session: StudioSession,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> None:
    incoming = stdin or sys.stdin
    outgoing = stdout or sys.stdout
    for raw in incoming:
        line = raw.strip()
        if not line:
            continue
        req_id: Any = None
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("请求必须是对象")
            req_id = req.get("id")
            params = req.get("params")
            apply_plugin_settings(req.get("settings") if isinstance(req.get("settings"), dict) else None)
            result = session.dispatch(str(req.get("method") or ""), params if isinstance(params, dict) else {})
            write_message(outgoing, {"id": req_id, "ok": True, "result": result})
        except Exception as exc:  # noqa: BLE001 — 协议层把失败收成一行，进程继续听下一条
            write_message(outgoing, {"id": req_id, "ok": False, "error": str(exc)})


def main() -> int:
    load_dotenv()
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass
    serve_stdio(StudioSession(plugin_root(), data_root=data_root()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
