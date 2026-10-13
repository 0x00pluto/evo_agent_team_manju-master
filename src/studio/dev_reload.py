"""本机操作台监视 Python 源码。判断本身不重启进程。"""

from __future__ import annotations

from pathlib import Path

POLL_SECONDS = 0.5
SETTLE_SECONDS = 0.3


def python_sources(root: Path) -> list[Path]:
    """只盯 src 下的 Python 和操作台入口。页面与提示词模板每次从磁盘读，不必重启。"""
    root = Path(root)
    src = root / "src"
    files = [path for path in src.rglob("*.py") if path.is_file()] if src.is_dir() else []
    entry = root / "scripts" / "run_studio.py"
    if entry.is_file():
        files.append(entry)
    return sorted(files)


def mtime_snapshot(paths: list[Path]) -> dict[str, int]:
    found: dict[str, int] = {}
    for path in paths:
        try:
            found[str(path)] = path.stat().st_mtime_ns
        except OSError:
            continue
    return found


def should_reload(before: dict[str, int], after: dict[str, int], *, busy: bool) -> bool:
    """有变更且没有生成任务时才重启，避免打断正在跑的一集。"""
    if busy:
        return False
    return before != after
