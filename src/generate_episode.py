"""从 episode 事实 + 模板模块组装调用，写出可复制提示词包。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from src.deepseek_client import chat
from src.prompt_fill import build_prompt

ChatFn = Callable[..., str]


def dialogue_block(lines: list[dict[str, str]]) -> str:
    parts = []
    for item in lines:
        speaker = item.get("speaker", "")
        text = item.get("text", "")
        parts.append(f"{speaker}：{text}" if speaker else text)
    return "\n".join(parts)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.rstrip() + "\n", encoding="utf-8")


def render_shot(sh: dict[str, Any], *, chat_fn: ChatFn = chat) -> str:
    """调用 DeepSeek 写出单镜 LibTV 块（含 ```text 正文）。"""
    dialogue = sh.get("dialogue")
    if isinstance(dialogue, list):
        dialogue_text = dialogue_block(dialogue)
    else:
        dialogue_text = str(dialogue or "")
    vars_shot = {
        "shot_id": sh.get("id", ""),
        "duration_hint": sh.get("duration_hint", ""),
        "shot_type": sh.get("shot_type", ""),
        "camera": sh.get("camera", ""),
        "protagonist": sh.get("protagonist", ""),
        "action": sh.get("action", "待生成"),
        "dialogue": dialogue_text,
        "sfx": sh.get("sfx", ""),
        "lighting": sh.get("lighting", ""),
        "scene_ref": sh.get("scene_ref", ""),
        "ref_images": sh.get("ref_images", ""),
        "scene_slot": resolve_scene_slot(sh) or "…",
    }
    content = chat_fn(
        [
            {
                "role": "system",
                "content": (
                    "你只输出 LibTV 九要素分镜块。"
                    "台词必须与用户给出的原文完全一致。"
                ),
            },
            {
                "role": "user",
                "content": build_prompt("shot_libtv.md", vars_shot),
            },
        ]
    )
    content = _lock_ref_line(content, str(sh.get("ref_images") or ""))
    content = _lock_scene_line(content, resolve_scene_slot(sh))
    return f"## {sh.get('id', '')}\n\n{content.strip()}\n"


_MIXED_SLOT_RE = re.compile(r"\{\{Mixed \d+\}\}")


def resolve_scene_slot(sh: dict[str, Any]) -> str:
    """场景行只留最后一张图的占位。旧稿没有 {{Mixed N}} 时返回空，交给模型原文。"""
    slot = str(sh.get("scene_slot") or "").strip()
    if slot:
        return slot
    found = _MIXED_SLOT_RE.findall(str(sh.get("ref_images") or ""))
    return found[-1] if found else ""


def _lock_labeled_line(content: str, label: str, value: str) -> str:
    value = value.strip()
    if not value:
        return content
    line = f"{label}：{value}"
    if re.search(rf"^{label}：.*$", content, flags=re.M):
        return re.sub(rf"^{label}：.*$", line, content, count=1, flags=re.M)
    if re.search(r"^风格：", content, flags=re.M):
        return re.sub(r"^风格：", f"{line}\n风格：", content, count=1, flags=re.M)
    return content.replace("```text\n", f"```text\n{line}\n", 1)


def _lock_ref_line(content: str, ref_images: str) -> str:
    """参考图清单由程序定死，模型写成「无」时换回来。"""
    return _lock_labeled_line(content, "参考图", ref_images)


def _lock_scene_line(content: str, scene_slot: str) -> str:
    """场景行只留 Mixed 占位，模型写上的段落标题会被盖掉。"""
    return _lock_labeled_line(content, "场景", scene_slot)


def upsert_shot_markdown(path: Path, shot_id: str, section: str, *, after_id: str | None = None) -> None:
    """覆盖已有 ## shot_id 节；否则插在 after_id 节之后，或追加到文末。"""
    block = section.strip() + "\n\n"
    heading = f"## {shot_id}\n"
    if path.is_file():
        text = path.read_text(encoding="utf-8")
    else:
        text = "# LibTV 分镜\n\n"
    if not text.endswith("\n"):
        text += "\n"

    start = text.find(heading)
    if start != -1:
        rest = text[start + len(heading) :]
        nxt = rest.find("\n## ")
        end = len(text) if nxt == -1 else start + len(heading) + nxt + 1
        text = text[:start] + block + text[end:]
    else:
        insert_at = len(text)
        if after_id:
            after_heading = f"## {after_id}\n"
            after_start = text.find(after_heading)
            if after_start != -1:
                rest = text[after_start + len(after_heading) :]
                nxt = rest.find("\n## ")
                insert_at = (
                    len(text)
                    if nxt == -1
                    else after_start + len(after_heading) + nxt + 1
                )
        text = text[:insert_at] + block + text[insert_at:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def generate_episode(
    episode: dict[str, Any],
    out_dir: Path,
    *,
    chat_fn: ChatFn = chat,
) -> list[Path]:
    written: list[Path] = []
    title = episode.get("title", "episode")
    readme = (
        f"# {title}\n\n"
        "本目录由 `scripts/generate_prompts.py` 经 **DeepSeek** 生成。\n"
        "复制顺序：角色三视图 → 面部特写 → 场景贴图 → LibTV 分镜。\n"
        "LibTV：9:16 · 全能参考 · 时长见各镜建议秒数。\n"
    )
    _write(out_dir / "00-使用说明.md", readme)
    written.append(out_dir / "00-使用说明.md")

    for ch in episode.get("characters", []):
        cid = ch["id"]
        name = ch["name"]
        vars_common = {
            "name": name,
            "appearance": ch.get("appearance", ""),
            "wardrobe": ch.get("wardrobe", ""),
            "expression": ch.get("expression", ""),
        }
        sheet_out = chat_fn(
            [
                {
                    "role": "system",
                    "content": "你只输出可复制的生图提示词，不要解释。",
                },
                {
                    "role": "user",
                    "content": build_prompt("character_sheet.md", vars_common),
                },
            ]
        )
        close_out = chat_fn(
            [
                {
                    "role": "system",
                    "content": "你只输出可复制的生图提示词，不要解释。",
                },
                {
                    "role": "user",
                    "content": build_prompt("character_closeup.md", vars_common),
                },
            ]
        )
        path = out_dir / f"01-角色-{cid}.md"
        body = (
            f"# 角色：{name}\n\n"
            f"## 三视图\n\n{sheet_out}\n\n"
            f"## 面部特写\n\n{close_out}\n"
        )
        _write(path, body)
        written.append(path)

    scene_parts: list[str] = ["# 场景贴图\n"]
    for sc in episode.get("scenes", []):
        sid = sc["id"]
        vars_scene = {
            "time_of_day": sc.get("time_of_day", ""),
            "space": sc.get("space", ""),
            "light": sc.get("light", ""),
            "props": sc.get("props", ""),
        }
        content = chat_fn(
            [
                {
                    "role": "system",
                    "content": "你只输出可复制的场景生图提示词，不要解释。",
                },
                {
                    "role": "user",
                    "content": build_prompt("scene.md", vars_scene),
                },
            ]
        )
        scene_parts.append(f"## {sid} · {sc.get('label', sid)}\n\n{content}\n")
    scene_path = out_dir / "02-场景.md"
    _write(scene_path, "\n".join(scene_parts))
    written.append(scene_path)

    shot_parts: list[str] = ["# LibTV 分镜\n"]
    for sh in episode.get("shots", []):
        shot_parts.append(render_shot(sh, chat_fn=chat_fn))
    shot_path = out_dir / "03-分镜.md"
    _write(shot_path, "\n".join(shot_parts))
    written.append(shot_path)
    return written
