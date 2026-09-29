"""操作台任务：读脚本 → 整理事实 → 提示词 → 配音。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.generate_episode import generate_episode
from src.studio.bench import validate_theme
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


def synthesize_voice(root: Path, slug: str) -> None:
    if not (os.environ.get("MINIMAX_API_KEY") or "").strip():
        raise RuntimeError(
            "缺少 MINIMAX_API_KEY。提示词已生成。在启动操作台的终端里 export 后再重跑配音。"
        )
    cmd = [
        sys.executable,
        str(root / "scripts" / "synthesize_episode_voiceover.py"),
        "--manifest",
        str(facts_dir(root) / f"{slug}-voiceover.json"),
        "--out-dir",
        str(root / "output" / slug / "voiceover"),
    ]
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err or f"配音失败（{proc.returncode}）")


def run_pipeline(
    root: Path,
    job: Job,
    script: str,
    selections: list[dict[str, Any]],
    *,
    compile_fn: Callable[..., dict[str, Any]] = compile_bundle,
    generate_fn: Callable[..., list[Path]] = generate_episode,
    voice_fn: Callable[[Path, str], None] = synthesize_voice,
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
        voice_fn(root, bundle["slug"])
    except Exception as exc:  # noqa: BLE001 — 提示词已落盘，配音失败仍可复制
        job.voice_error = str(exc)
    job.status = "done"
    job.touch()


class JobManager:
    def __init__(self, root: Path, *, pipeline: Callable[..., None] = run_pipeline) -> None:
        self.root = Path(root).resolve()
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
            self.pipeline(self.root, job, script, selections)
        except Exception as exc:  # noqa: BLE001
            job.status = "error"
            job.error = str(exc)
            job.touch()
        finally:
            with self._lock:
                self._busy = False
