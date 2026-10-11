"""克隆前检查样音。超限或不含音轨时不发起上传。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

MAX_BYTES = 20 * 1024 * 1024
MIN_SECONDS = 10
MAX_SECONDS = 5 * 60
_VIDEO = {".mp4", ".m4v", ".mov", ".mkv"}
_AUDIO = {".mp3", ".m4a", ".wav"}

Run = Callable[..., subprocess.CompletedProcess[str]]


class SampleError(ValueError):
    """样音不符合克隆限制。调用方不应再请求 MiniMax。"""


def assert_limits(*, size: int, duration: float | None, has_audio: bool) -> None:
    if size > MAX_BYTES:
        raise SampleError("文件大于 20MB，不能克隆")
    if size <= 0 or not has_audio or duration is None:
        raise SampleError("没有音轨，不能克隆")
    if duration < MIN_SECONDS:
        raise SampleError("音轨短于 10 秒，不能克隆")
    if duration > MAX_SECONDS:
        raise SampleError("音轨长于 5 分钟，不能克隆")


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise SampleError("需要本机安装 ffmpeg，才能从视频抽出音轨") from exc


def probe_media(path: Path, run: Run | None = None) -> tuple[bool, float | None]:
    """返回是否有音轨，以及时长（秒）。"""
    runner = run or _run
    streams = runner(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ]
    )
    if streams.returncode != 0 and not (streams.stdout or "").strip():
        if "No such file" in (streams.stderr or ""):
            raise SampleError("样音文件不存在")
        raise SampleError("没有音轨，不能克隆")
    has_audio = "audio" in (streams.stdout or "")
    duration_run = runner(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    raw = (duration_run.stdout or "").strip()
    duration: float | None
    try:
        duration = float(raw) if raw else None
    except ValueError:
        duration = None
    return has_audio, duration


def extract_audio(src: Path, dest: Path, run: Run | None = None) -> Path:
    runner = run or _run
    dest.parent.mkdir(parents=True, exist_ok=True)
    done = runner(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-vn",
            "-acodec",
            "libmp3lame",
            "-ar",
            "44100",
            "-ac",
            "1",
            str(dest),
        ]
    )
    if done.returncode != 0 or not dest.is_file() or dest.stat().st_size <= 0:
        raise SampleError("没有音轨，不能克隆")
    return dest


def prepare_sample(
    src: Path,
    work_dir: Path,
    *,
    probe: Callable[[Path], tuple[bool, float | None]] | None = None,
    extract: Callable[[Path, Path], Path] | None = None,
) -> Path:
    """视频先抽音轨。时长或体积不合格时直接拒绝。"""
    path = Path(src)
    if not path.is_file():
        raise SampleError("样音文件不存在")
    suffix = path.suffix.lower()
    if suffix not in _VIDEO and suffix not in _AUDIO:
        raise SampleError("只接收 MP4，或 mp3 / m4a / wav 音轨")
    target = path
    if suffix in _VIDEO:
        pull = extract or extract_audio
        target = pull(path, work_dir / "track.mp3")
    look = probe or probe_media
    has_audio, duration = look(target)
    assert_limits(size=target.stat().st_size, duration=duration, has_audio=has_audio)
    return target
