"""操作台任务：读脚本 → 整理事实 → 提示词 → 配音。"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.episode_voiceover import synthesize_manifest
from src.generate_episode import generate_episode
from src.studio.bench import _fact_paths, validate_theme, voice_dir
from src.studio.compile_episode import compile_bundle, resolve_modes

Runner = Callable[..., None]


@dataclass
class Job:
    id: str
    status: str = "queued"
    theme: str = ""
    title: str = ""
    error: str = ""
    voice_error: str = ""
    instruction: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "theme": self.theme,
            "title": self.title,
            "error": self.error,
            "voice_error": self.voice_error,
            "instruction": self.instruction,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def stamp_slug(slug: str, root: Path, *, now: datetime | None = None) -> str:
    """目录名用本地时间开头，同一秒已有目录时再加 -2。"""
    moment = now or datetime.now()
    prefix = moment.strftime("%Y%m%d-%H%M%S-")
    name = validate_theme(slug).strip("-")
    taken = root / "output"

    def fit(suffix: str) -> str:
        room = 64 - len(prefix) - len(suffix)
        trimmed = name[:room].strip("-") or "ep"
        if len(trimmed) > room:
            trimmed = trimmed[:room].strip("-") or "e"
        return validate_theme(f"{prefix}{trimmed}{suffix}")

    candidate = fit("")
    extra = 2
    while (taken / candidate).is_dir():
        candidate = fit(f"-{extra}")
        extra += 1
        if extra > 99:
            raise RuntimeError("同一秒内的目录太多")
    return candidate


def facts_dir(root: Path) -> Path:
    path = root / "temp" / "studio_facts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_facts(root: Path, bundle: dict[str, Any], selections: list[dict[str, Any]]) -> Path:
    slug = validate_theme(bundle["slug"])
    episodes = facts_dir(root)
    (episodes / f"{slug}.json").write_text(
        json.dumps(bundle["episode"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (episodes / f"{slug}-voiceover.json").write_text(
        json.dumps(bundle["voiceover"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    out = root / "output" / slug
    out.mkdir(parents=True, exist_ok=True)
    brief = {
        "sections": selections,
        "summary": bundle["summary"],
        "title": bundle["episode"].get("title") or slug,
    }
    (out / "studio-brief.json").write_text(
        json.dumps(brief, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return out


_LINE_ID = re.compile(r"^[A-Za-z0-9]{1,8}$")
_FILE_SLUG = {"招商顾问": "advisor", "企业主": "owner"}


def resynth_line(
    root: Path,
    theme: str,
    line_id: str,
    text: str,
    *,
    code_root: Path | None = None,
) -> dict[str, str]:
    """只改一条口播并重配，不动其它句和分镜提示词。"""
    theme = validate_theme(theme)
    line_id = str(line_id or "").strip()
    text = str(text or "").strip()
    if not _LINE_ID.fullmatch(line_id):
        raise ValueError("配音编号不对")
    if not text:
        raise ValueError("配音文本为空")
    if not (os.environ.get("MINIMAX_API_KEY") or "").strip():
        raise RuntimeError("缺少 MINIMAX_API_KEY。提示词不受影响，在设置里填上密钥后再重配这一条。")
    code = Path(code_root) if code_root is not None else Path(root)
    _episode, voice_path = _fact_paths(root, theme, code_root=code)
    if not voice_path.is_file():
        raise FileNotFoundError("还没有这一集的配音清单")
    data = json.loads(voice_path.read_text(encoding="utf-8"))
    found = None
    for line in data.get("lines") or []:
        if isinstance(line, dict) and str(line.get("id") or "") == line_id:
            found = line
            break
    if found is None:
        raise ValueError(f"清单里没有第 {line_id} 条")
    found["text"] = text
    voice_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    synthesize_manifest(voice_path, voice_dir(root, theme), only=[line_id], repo_root=code)
    speaker = str(found.get("speaker") or "")
    file_slug = _FILE_SLUG.get(speaker, speaker.replace(" ", "-"))
    filename = f"{line_id}_{file_slug}.mp3"
    return {
        "id": line_id,
        "text": text,
        "file": filename,
        "url": f"/media/{theme}/voiceover/{filename}?v={int(time.time())}",
    }


def synthesize_voice(root: Path, slug: str, *, code_root: Path | None = None) -> None:
    if not (os.environ.get("MINIMAX_API_KEY") or "").strip():
        raise RuntimeError(
            "缺少 MINIMAX_API_KEY。提示词已生成。在设置里填写 MiniMax 密钥后再重跑配音。"
        )
    code = Path(code_root) if code_root is not None else Path(root)
    synthesize_manifest(
        facts_dir(root) / f"{slug}-voiceover.json",
        root / "output" / slug / "voiceover",
        repo_root=code,
    )


def run_pipeline(
    root: Path,
    job: Job,
    script: str,
    selections: list[dict[str, Any]],
    *,
    code_root: Path | None = None,
    compile_fn: Callable[..., dict[str, Any]] = compile_bundle,
    generate_fn: Callable[..., list[Path]] = generate_episode,
    voice_fn: Callable[..., None] = synthesize_voice,
) -> None:
    job.status = "compiling"
    job.touch()
    bundle = compile_fn(script, selections)
    bundle["slug"] = stamp_slug(bundle["slug"], root)
    voiceover = bundle.get("voiceover")
    if isinstance(voiceover, dict):
        voiceover["episode"] = bundle["slug"]
    job.theme = bundle["slug"]
    job.title = str(bundle["episode"].get("title") or bundle["slug"])
    write_facts(root, bundle, selections)
    job.status = "prompting"
    job.touch()
    generate_fn(bundle["episode"], root / "output" / bundle["slug"])
    job.status = "voicing"
    job.touch()
    try:
        if voice_fn is synthesize_voice:
            synthesize_voice(root, bundle["slug"], code_root=code_root)
        else:
            voice_fn(root, bundle["slug"])
    except Exception as exc:  # noqa: BLE001 — 提示词已落盘，配音失败仍可复制
        job.voice_error = str(exc)
    job.status = "done"
    job.touch()


class JobManager:
    def __init__(
        self,
        root: Path,
        *,
        code_root: Path | None = None,
        pipeline: Callable[..., None] = run_pipeline,
    ) -> None:
        self.root = Path(root).resolve()
        self.code_root = Path(code_root).resolve() if code_root is not None else self.root
        self.pipeline = pipeline
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._busy = False

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def create(self, script: str, selections: list[dict[str, Any]]) -> Job:
        script = script.strip()
        if len(script) < 20:
            raise ValueError("脚本太短")
        if not isinstance(selections, list) or not selections:
            raise ValueError("请为每一段选择分镜或只配音")
        resolve_modes(script, selections)
        note = json.dumps(selections, ensure_ascii=False)
        with self._lock:
            if self._busy:
                raise RuntimeError("已有任务进行中")
            self._busy = True
            job = Job(id=uuid.uuid4().hex[:12], instruction=note, status="queued")
            self._jobs[job.id] = job
        thread = threading.Thread(
            target=self._worker,
            args=(job, script, selections),
            daemon=True,
        )
        thread.start()
        return job

    def _worker(self, job: Job, script: str, selections: list[dict[str, Any]]) -> None:
        try:
            if self.pipeline is run_pipeline:
                run_pipeline(self.root, job, script, selections, code_root=self.code_root)
            else:
                self.pipeline(self.root, job, script, selections)
        except Exception as exc:  # noqa: BLE001
            job.status = "error"
            job.error = str(exc)
            job.touch()
        finally:
            with self._lock:
                self._busy = False
