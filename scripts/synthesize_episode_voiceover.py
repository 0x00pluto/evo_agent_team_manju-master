#!/usr/bin/env python3
"""整集成片配音：读 voiceover 清单，调用本仓 MiniMax TTS 逐句出 MP3。"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.episode_voiceover import main, merge_result_lines  # noqa: E402

__all__ = ["main", "merge_result_lines"]


if __name__ == "__main__":
    raise SystemExit(main())
