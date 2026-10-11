"""Hub 插件的常驻进程：stdin 一行请求，stdout 一行响应。

任务仍由 JobManager 的后台线程跑。createJob 写完响应就返回，页面再来问 getJob。
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from src.env_load import apply_plugin_settings, data_root, load_dotenv, plugin_root
from src.studio.bench import list_recent, load_bench
from src.studio.jobs import JobManager, resynth_line
from src.studio.server import (
    _with_cast,
    download_zip,
    load_script,
    preview_payload,
    queue_add,
    queue_clone,
    read_voice,
    reveal_voice,
    write_media_bytes,
)
from src.studio.voice_slots import (
    account_voice_rows,
    bind_speaker,
    cast_view,
    delete_account_voice,
    load_slots,
    minimax_ready,
    public_slot,
    recover_slots,
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
            return preview_payload(script, split_with=payload.get("split_with"))
        if method == "createJob":
            script = load_script(self.data_root, payload)
            sections = payload.get("sections")
            if not isinstance(sections, list):
                raise ValueError("请为每一段选择「生成分镜」或「只配音」")
            return self.manager.create(script, sections).to_dict()
        if method == "getJob":
            job = self.manager.get(str(payload.get("id") or ""))
            if job is None:
                raise FileNotFoundError("无此任务")
            return job.to_dict()
        if method == "recent":
            return {"recent": list_recent(self.data_root)}
        if method == "bench":
            theme = str(payload.get("theme") or "")
            bench = load_bench(self.data_root, theme, code_root=self.root)
            return _with_cast(self.data_root, self.root, theme, bench)
        if method == "listSlots":
            slots = load_slots(self.data_root, self.root)
            return {"slots": [public_slot(slot) for slot in slots], "minimax_ready": minimax_ready()}
        if method == "listAccountVoices":
            return {"voices": account_voice_rows(self.data_root, self.root)}
        if method == "deleteAccountVoice":
            return delete_account_voice(self.data_root, self.root, str(payload.get("voice_id") or ""))
        if method == "bindSlot":
            theme = str(payload.get("theme") or "")
            rows = bind_speaker(
                self.data_root,
                theme,
                str(payload.get("speaker") or ""),
                str(payload.get("slot_id") or ""),
                load_slots(self.data_root, self.root),
            )
            return cast_view(rows, load_slots(self.data_root, self.root))
        if method == "cloneSlot":
            return queue_clone(self.manager, self.data_root, self.root, str(payload.get("id") or ""))
        if method == "replaceSlot":
            dest = write_media_bytes(
                self.data_root,
                str(payload.get("filename") or "sample.mp4"),
                base64.b64decode(str(payload.get("base64") or "")),
            )
            return queue_clone(
                self.manager,
                self.data_root,
                self.root,
                str(payload.get("id") or ""),
                dest,
            )
        if method == "addSlot":
            dest = write_media_bytes(
                self.data_root,
                str(payload.get("filename") or "sample.mp4"),
                base64.b64decode(str(payload.get("base64") or "")),
            )
            return queue_add(
                self.manager,
                self.data_root,
                self.root,
                str(payload.get("name") or ""),
                dest,
            )
        if method == "generateVoice":
            return self.manager.start_voice(str(payload.get("theme") or "")).to_dict()
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
    recover_slots(data_root(), plugin_root())
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass
    serve_stdio(StudioSession(plugin_root(), data_root=data_root()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
