#!/usr/bin/env python3
"""CLI：用 DeepSeek 根据模板模块生成本集可复制提示词。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.generate_episode import generate_episode, render_shot, upsert_shot_markdown  # noqa: E402
from src.prompt_fill import build_prompt  # noqa: E402


def load_episode(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("episode JSON 必须是对象")
        return data
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "解析 YAML 需要 PyYAML。请执行：uv pip install -r requirements.txt\n"
            "或把 episode 另存为 .json。"
        ) from exc
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("episode 必须是 YAML 映射")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="用 DeepSeek 根据模板模块生成本集可复制提示词"
    )
    parser.add_argument("--episode", required=True, help="本集事实 YAML/JSON 路径")
    parser.add_argument("--out", required=True, help="输出目录（建议 output/<主题>/）")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只组装发给 DeepSeek 的提示并打印，不调用 API",
    )
    parser.add_argument(
        "--only-shot",
        default="",
        help="只生成该镜 id，并写入 --out/03-分镜.md（不重生角色与场景）",
    )
    args = parser.parse_args(argv)

    episode_path = Path(args.episode).expanduser()
    if not episode_path.is_file():
        print(f"找不到 episode: {episode_path}", file=sys.stderr)
        return 2
    out_dir = Path(args.out).expanduser()
    episode = load_episode(episode_path)

    if args.only_shot:
        shots = episode.get("shots") or []
        match = next((s for s in shots if s.get("id") == args.only_shot), None)
        if match is None:
            print(f"episode 中没有镜头: {args.only_shot}", file=sys.stderr)
            return 2
        if args.dry_run:
            print(build_prompt("shot_libtv.md", {"shot_id": match["id"], "duration_hint": match.get("duration_hint", ""), "shot_type": match.get("shot_type", ""), "camera": match.get("camera", ""), "protagonist": match.get("protagonist", ""), "action": match.get("action", ""), "dialogue": "", "sfx": "", "lighting": match.get("lighting", ""), "scene_ref": match.get("scene_ref", ""), "ref_images": match.get("ref_images", "")})[:400])
            print("dry-run 完成（未调用 DeepSeek）")
            return 0
        idx = shots.index(match)
        after_id = shots[idx - 1]["id"] if idx > 0 else None
        section = render_shot(match)
        shot_path = out_dir / "03-分镜.md"
        upsert_shot_markdown(shot_path, match["id"], section, after_id=after_id)
        print(shot_path)
        return 0

    if args.dry_run:
        for ch in episode.get("characters", []):
            vars_common = {
                "name": ch["name"],
                "appearance": ch.get("appearance", ""),
                "wardrobe": ch.get("wardrobe", ""),
                "expression": ch.get("expression", ""),
            }
            print("=== character_sheet", ch["id"], "===")
            print(build_prompt("character_sheet.md", vars_common)[:800], "…\n")
        print("dry-run 完成（未调用 DeepSeek）")
        return 0

    paths = generate_episode(episode, out_dir)
    for p in paths:
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
