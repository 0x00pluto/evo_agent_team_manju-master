"""把脚本文本和操作说明整理成 episode 与 voiceover 两份事实。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

from src.dex_chat import chat

ChatFn = Callable[..., str]

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SHOT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_ID_TOKEN_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")

NARRATOR = "旁白"
_MAX_HAN_PER_SHOT = 72


def display_speaker(raw: str) -> str:
    """对白保留原名。没有称呼的口播记为旁白。"""
    name = str(raw or "").strip()
    return name or NARRATOR

_SYSTEM = """你是漫剧美术。只输出一个 JSON 对象，不要解释，不要 Markdown。

出镜段落、分镜条数、台词和说话人已经由程序定死。你只补外貌、场景和运镜，禁止增删分镜，禁止改台词。

硬规则：
- 角色 name 必须与给定名单逐字一致。
- 场景 id 必须与给定 scene-1、scene-2… 一致，不要新造场景。
- shots 的 id 必须与给定 V01、V02… 一致。不要返回 dialogue。
- slug 只用小写英文、数字和短横线。角色 id 同样。
- 场景的 space、props 只写空环境。主桌和主位座椅空着，不要把角色写进场景里坐着或站着。远处虚化、看不清脸的路人可以有。
- 运镜草案按竖屏成片写。景别用先开口者的单人景别，不要写成横屏双人全景再滑过去。本片选用按情绪挑，不是菜单：仔细听用缓推，放松或看到环境用拉远，介绍园区用慢摇给园区，换脸用硬切，两人交代场景可环绕，话要落地用固定。不要每镜都缓推再硬切。不要用一次横移把两人的脸滑过去。

JSON 形状：
{
  "slug": "example-episode",
  "title": "",
  "scope": "",
  "characters": [{"id":"","name":"","appearance":"","wardrobe":"","expression":""}],
  "scenes": [{"id":"scene-1","label":"","time_of_day":"","space":"","light":"","props":""}],
  "shots": [{"id":"V01","shot_type":"","camera":"","protagonist":"","action":"","sfx":"","lighting":""}]
}
"""

_HEADING_RE = re.compile(r"^【([^】]+)】\s*$")
_NOTE_HEADING_RE = re.compile(r"^#{1,6}\s+\S")
_DIALOGUE_RE = re.compile(r"^([^：:\n（]{1,20})(?:（[^）]{0,12}）)?[：:]\s*(.+)$")
_BEAT_RE = re.compile(r"秒")


def _is_image_line(line: str) -> bool:
    """配图 Markdown 的地址里有冒号，不能当成「说话人：台词」。"""
    return line.startswith("![")


def strip_image_lines(script: str) -> str:
    kept = [raw for raw in script.splitlines() if not _is_image_line(raw.strip())]
    return "\n".join(kept)


def _model_snippet(text: str, pos: int, *, radius: int = 80) -> str:
    start = max(0, pos - radius)
    end = min(len(text), pos + radius)
    chunk = text[start:end]
    if start:
        chunk = "…" + chunk
    if end < len(text):
        chunk = chunk + "…"
    return f"{chunk}（共 {len(text)} 字）"


def extract_json(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    if start < 0:
        raise ValueError("模型没有返回 JSON")
    body = raw[start:]
    try:
        data, _ = json.JSONDecoder().raw_decode(body)
    except json.JSONDecodeError as exc:
        snippet = _model_snippet(body, exc.pos)
        raise ValueError(f"返回的内容不是合法 JSON（{exc}）。模型原文：{snippet}") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON 必须是对象")
    return data


def _han_count(text: str) -> int:
    return len(_HAN_RE.findall(text))


def _slug_or_hash(raw: str, title: str) -> str:
    s = (raw or "").strip().lower()
    if _SLUG_RE.match(s) and len(s) <= 64:
        return s
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
    return f"episode-{digest}"


def _token(raw: str, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (raw or "").lower()).strip("-")
    if _ID_TOKEN_RE.match(s):
        return s[:48]
    return fallback


def _utterance(line: str) -> str:
    text = line.strip()
    text = re.sub(r"^[^：:\n]{1,24}(?:（[^）]{0,12}）)?[：:]\s*", "", text)
    return text.strip()


def script_utterances(script: str) -> list[str]:
    rows: list[str] = []
    for raw in script.splitlines():
        line = raw.strip()
        if not line or (line.startswith("【") and line.endswith("】")):
            continue
        if line.startswith("#") or line.startswith("- ") or _is_image_line(line):
            continue
        uttered = _utterance(line)
        if uttered:
            rows.append(uttered)
    return rows


def _locate(script: str, text: str) -> int:
    """在原文坐标系里找配音句。读法引号处允许换成一小段数字。"""
    if text and text in script:
        return script.find(text)
    parts = re.split(r'"[^"]*"', text)
    literals = [p for p in parts if p]
    if len(parts) > 1 and literals:
        pattern = r".{0,24}".join(re.escape(p) for p in literals)
        found = re.search(pattern, script)
        if found:
            return found.start()
    return -1


def validate_bundle(data: dict[str, Any], script: str) -> dict[str, Any]:
    episode = data.get("episode")
    voiceover = data.get("voiceover")
    if not isinstance(episode, dict) or not isinstance(voiceover, dict):
        raise ValueError("JSON 缺少 episode 或 voiceover")

    title = str(episode.get("title") or "").strip() or "未命名"
    slug = _slug_or_hash(str(data.get("slug") or ""), title)
    episode["title"] = title
    episode["style"] = "cinematic-photoreal-short-drama"
    episode["source"] = str(episode.get("source") or "studio")

    characters = episode.get("characters") or []
    scenes = episode.get("scenes") or []
    shots = episode.get("shots") or []
    if not isinstance(characters, list) or not isinstance(scenes, list) or not isinstance(shots, list):
        raise ValueError("characters / scenes / shots 必须是数组")

    for i, ch in enumerate(characters):
        if not isinstance(ch, dict) or not str(ch.get("name") or "").strip():
            raise ValueError(f"角色 {i + 1} 缺少 name")
        ch["id"] = _token(str(ch.get("id") or ""), f"role-{i + 1}")
        for key in ("appearance", "wardrobe", "expression"):
            ch.setdefault(key, "")
    for i, sc in enumerate(scenes):
        if not isinstance(sc, dict):
            raise ValueError(f"场景 {i + 1} 不是对象")
        sc["id"] = _token(str(sc.get("id") or ""), f"scene-{i + 1}")
        sc["label"] = str(sc.get("label") or sc["id"])
        for key in ("time_of_day", "space", "light", "props"):
            sc.setdefault(key, "")

    utterances = script_utterances(script)
    seen_ids: set[str] = set()
    for sh in shots:
        if not isinstance(sh, dict):
            raise ValueError("分镜必须是对象")
        sid = str(sh.get("id") or "").strip()
        if not _SHOT_ID_RE.match(sid):
            raise ValueError(f"分镜 id 不合法: {sid!r}")
        if sid in seen_ids:
            raise ValueError(f"分镜 id 重复: {sid}")
        seen_ids.add(sid)
        dialogue = sh.get("dialogue") or []
        if not isinstance(dialogue, list) or not dialogue:
            raise ValueError(f"{sid} 缺少对白")
        han = 0
        for item in dialogue:
            if not isinstance(item, dict):
                raise ValueError(f"{sid} 对白格式不对")
            text = str(item.get("text") or "").strip()
            if text not in script:
                raise ValueError(f"{sid} 的台词不在脚本原文里: {text}")
            if utterances and text not in utterances and not any(text in u for u in utterances):
                raise ValueError(f"{sid} 的台词被改写了: {text}")
            han += _han_count(text)
            item["text"] = text
            item["speaker"] = display_speaker(str(item.get("speaker") or ""))
        if han > _MAX_HAN_PER_SHOT:
            raise ValueError(f"{sid} 超过 12 秒上限（{han} 字），请拆镜")
        for key in (
            "duration_hint",
            "shot_type",
            "camera",
            "protagonist",
            "action",
            "sfx",
            "lighting",
            "scene_ref",
            "ref_images",
            "scene_slot",
        ):
            sh.setdefault(key, "")

    lines = voiceover.get("lines") or []
    if not isinstance(lines, list):
        raise ValueError("voiceover.lines 必须是数组")
    positions: list[int] = []
    for line in lines:
        if not isinstance(line, dict):
            raise ValueError("配音行必须是对象")
        speaker = display_speaker(str(line.get("speaker") or ""))
        text = str(line.get("text") or "").strip()
        text = re.sub(r"^（[^）]{0,12}）", "", text).strip()
        if not text:
            raise ValueError("配音文本为空")
        pos = _locate(script, text)
        if pos < 0:
            raise ValueError(f"配音文本对不上脚本: {text[:40]}")
        positions.append(pos)
        line["speaker"] = speaker
        line.pop("voice_slug", None)
        line["text"] = text
        segment = str(line.get("segment") or "vo")
        if not re.fullmatch(r"[a-z0-9-]{1,24}", segment):
            segment = "vo"
        line["segment"] = segment
    if positions != sorted(positions):
        raise ValueError("配音顺序与脚本不一致")
    for i, line in enumerate(lines):
        line["id"] = f"{i + 1:02d}"

    shot_texts = [
        str(item.get("text") or "")
        for sh in shots
        for item in (sh.get("dialogue") or [])
    ]
    for text in shot_texts:
        if text not in [str(line.get("text") or "") for line in lines]:
            raise ValueError(f"出镜台词没有进配音清单: {text}")

    voiceover["title"] = str(voiceover.get("title") or f"{title}（整集配音）")
    voiceover["episode"] = slug
    voiceover.pop("voice_map", None)
    voiceover["lines"] = lines

    from src.studio.bench import summary_from_facts

    return {
        "slug": slug,
        "episode": episode,
        "voiceover": voiceover,
        "summary": summary_from_facts(episode, voiceover),
    }


def _section_items(body_lines: list[str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw in body_lines:
        line = raw.strip()
        if line.startswith("- "):
            line = line[2:].strip()
        if not line or line.startswith("#") or _is_image_line(line):
            continue
        matched = _DIALOGUE_RE.match(line)
        if matched:
            items.append(
                {
                    "kind": "dialogue",
                    "speaker": matched.group(1).strip(),
                    "text": matched.group(2).strip(),
                }
            )
        elif line:
            items.append({"kind": "narration", "speaker": "", "text": line})
    return items


def _plain_line(raw: str) -> str:
    """去掉行首标题记号和加粗星号，再判断是不是整行【】。"""
    line = raw.strip()
    line = re.sub(r"^#{1,6}\s*", "", line)
    line = line.replace("*", "")
    return line.strip()


def bracket_title(raw: str) -> str | None:
    matched = _HEADING_RE.match(_plain_line(raw))
    if not matched:
        return None
    return matched.group(1).strip()


def _is_note_heading(raw: str) -> bool:
    if bracket_title(raw):
        return False
    return bool(_NOTE_HEADING_RE.match(raw.strip()))


def parse_sections(script: str) -> list[dict[str, Any]]:
    """按【】切段。第一段标题之前的角色说明、选题不进列表。"""
    sections: list[dict[str, Any]] = []
    title = ""
    start = ""
    body: list[str] = []
    started = False
    for raw in script.splitlines():
        heading = bracket_title(raw)
        if heading:
            if started:
                sections.append(_section_record(len(sections), title, body, start))
            started = True
            title = heading
            start = raw.strip()
            body = []
            continue
        if _is_note_heading(raw):
            if not started:
                continue
            sections.append(_section_record(len(sections), title, body, start))
            started = False
            break
        if started:
            body.append(raw)
    if started:
        sections.append(_section_record(len(sections), title, body, start))
    return sections


def _section_record(
    index: int,
    title: str,
    body: list[str],
    start: str = "",
) -> dict[str, Any]:
    items = _section_items(body)
    has_dialogue = any(item["kind"] == "dialogue" for item in items)
    preview = next((item["text"] for item in items), "")
    return {
        "index": index,
        "title": title,
        "preview": preview[:42],
        "mode": "shot" if has_dialogue else "voice",
        "start": start,
        "items": items,
    }


def _line_start(script: str, pos: int) -> int:
    if pos > 0 and script[pos - 1] != "\n":
        return script.rfind("\n", 0, pos) + 1
    return pos


def sections_from_anchors(script: str, proposed: list[Any]) -> list[dict[str, Any]] | None:
    """用原文里按顺序出现的短句切开。对不上就返回 None。"""
    if not isinstance(proposed, list) or len(proposed) < 2:
        return None
    found: list[tuple[int, str, str]] = []
    cursor = 0
    for item in proposed:
        if not isinstance(item, dict):
            return None
        start = str(item.get("start") or "").strip()
        title = str(item.get("title") or "").strip()
        if len(start) < 4 or not title:
            return None
        raw_pos = script.find(start, cursor)
        if raw_pos < 0:
            return None
        pos = _line_start(script, raw_pos)
        if found and pos <= found[-1][0]:
            return None
        found.append((pos, title, start))
        cursor = raw_pos + len(start)
    sections: list[dict[str, Any]] = []
    for index, (pos, title, start) in enumerate(found):
        end = found[index + 1][0] if index + 1 < len(found) else len(script)
        lines = script[pos:end].splitlines()
        first = lines[0].strip() if lines else ""
        drop_label = bool(first) and (
            bracket_title(lines[0]) or (first == start and not _DIALOGUE_RE.match(first))
        )
        body = lines[1:] if drop_label else lines
        trimmed: list[str] = []
        for raw in body:
            if _is_note_heading(raw):
                break
            trimmed.append(raw)
        sections.append(_section_record(index, title, trimmed, start))
    return sections


def _dialogue_count(script: str) -> int:
    count = 0
    for raw in script.splitlines():
        line = raw.strip()
        if line.startswith("- "):
            line = line[2:].strip()
        if _is_image_line(line):
            continue
        if _DIALOGUE_RE.match(line):
            count += 1
    return count


def looks_like_many_beats(script: str) -> bool:
    if _han_count(script) < 40:
        return False
    return len(_BEAT_RE.findall(script)) >= 2 or _dialogue_count(script) >= 2


_PROGRAM_FAIL = "脚本里没有【】段落，可以改用大模型整理"


def prepare_script(
    script: str,
    *,
    split_with: str = "program",
    chat_fn: ChatFn | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """程序切段为默认。只有明确要求时才调用大模型。"""
    if split_with == "model":
        from src.script_preprocess import preprocess_script

        canonical = preprocess_script(script, chat_fn=chat_fn)
        return canonical, parse_sections(canonical)
    cleaned = strip_image_lines(script)
    sections = parse_sections(cleaned)
    if not sections:
        raise ValueError(_PROGRAM_FAIL)
    return cleaned, sections


def split_sections(
    script: str,
    *,
    split_with: str = "program",
    chat_fn: ChatFn | None = None,
) -> list[dict[str, Any]]:
    """按所选入口切段。未指定时用程序。"""
    _, sections = prepare_script(script, split_with=split_with, chat_fn=chat_fn)
    return sections


def script_preamble(script: str) -> str:
    rows: list[str] = []
    for raw in script.splitlines():
        if bracket_title(raw):
            break
        rows.append(raw)
    return "\n".join(rows).strip()


def _sections_for_selections(
    script: str,
    selections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """勾选里带了原文起点就按起点切，对不上再退回本地切段。"""
    if not selections or not all(isinstance(item, dict) for item in selections):
        return parse_sections(script)
    ordered = sorted(selections, key=lambda item: int(item.get("index") or 0))
    proposed: list[dict[str, str]] = []
    for item in ordered:
        if not isinstance(item, dict):
            return parse_sections(script)
        start = str(item.get("start") or "").strip()
        if not start:
            return parse_sections(script)
        title = str(item.get("title") or "").strip() or start[:24]
        proposed.append({"title": title, "start": start})
    if len(proposed) < 2:
        return parse_sections(script)
    return sections_from_anchors(script, proposed) or parse_sections(script)


def resolve_modes(script: str, selections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections = _sections_for_selections(script, selections)
    if not sections:
        raise ValueError("脚本里没有【】段落")
    chosen: dict[int, str] = {}
    for item in selections or []:
        if not isinstance(item, dict):
            raise ValueError("段落选择格式不对")
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError) as exc:
            raise ValueError("段落选择格式不对") from exc
        mode = str(item.get("mode") or "")
        if mode not in ("shot", "voice"):
            raise ValueError(f"段落 {index + 1} 请选择「生成分镜」或「只配音」")
        chosen[index] = mode
    resolved: list[dict[str, Any]] = []
    for section in sections:
        mode = chosen.get(section["index"])
        if mode not in ("shot", "voice"):
            raise ValueError(f"请为「{section['title']}」选择「生成分镜」或「只配音」")
        resolved.append({**section, "mode": mode})
    return resolved


def _reading(text: str) -> str:
    return text.replace("12000", '"一万两千"')


def _sentences(text: str) -> list[str]:
    if _han_count(text) <= _MAX_HAN_PER_SHOT:
        return [text]
    parts = [part.strip() for part in re.split(r"(?<=[。！？])", text) if part.strip()]
    return parts or [text]


def _pack_lines(lines: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    groups: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    han = 0
    for line in lines:
        count = _han_count(line["text"])
        if current and han + count > _MAX_HAN_PER_SHOT:
            groups.append(current)
            current = []
            han = 0
        current.append(line)
        han += count
    if current:
        groups.append(current)
    return groups


def build_locked(script: str, selections: list[dict[str, Any]]) -> dict[str, Any]:
    """勾选结果锁住出镜台词和配音条。不调用模型。"""
    resolved = resolve_modes(script, selections)
    voice_lines: list[dict[str, str]] = []
    shot_groups: list[dict[str, Any]] = []
    scenes: list[dict[str, str]] = []
    names: list[str] = []
    shot_texts: list[str] = []
    voice_only_texts: list[str] = []

    for section in resolved:
        items = section["items"]
        dialogues = [item for item in items if item["kind"] == "dialogue"]
        narrations = [item for item in items if item["kind"] == "narration"]
        filmed_source = dialogues or narrations if section["mode"] == "shot" else []
        filmed: list[dict[str, str]] = []
        for line in filmed_source:
            for piece in _sentences(line["text"]):
                filmed.append({"speaker": line["speaker"], "text": piece})
        if section["mode"] == "shot":
            if not filmed:
                raise ValueError(f"「{section['title']}」没有可出镜的句子")
            scene_id = f"scene-{len(scenes) + 1}"
            scenes.append({"id": scene_id, "label": section["title"]})
            for group in _pack_lines(filmed):
                shot_groups.append(
                    {"section": section, "scene_id": scene_id, "lines": group}
                )
            for line in filmed:
                shot_texts.append(line["text"])
                speaker_name = str(line["speaker"] or "").strip()
                if speaker_name and speaker_name not in names:
                    names.append(speaker_name)

        for line in items:
            pieces = (
                _sentences(line["text"])
                if line in filmed_source
                else [line["text"]]
            )
            for piece in pieces:
                on_screen = piece in shot_texts and line in filmed_source
                if on_screen:
                    voice_lines.append(
                        {
                            "speaker": display_speaker(line["speaker"]),
                            "text": piece,
                            "segment": "shot",
                        }
                    )
                else:
                    voice_only_texts.append(line["text"] if piece == line["text"] else piece)
                    voice_lines.append(
                        {
                            "speaker": display_speaker(line["speaker"]),
                            "text": _reading(piece),
                            "segment": "vo",
                        }
                    )

    if not voice_lines and not shots:
        raise ValueError("脚本里没有可配音的句子")

    shots: list[dict[str, Any]] = []
    for index, group in enumerate(shot_groups, start=1):
        han = sum(_han_count(line["text"]) for line in group["lines"])
        seconds = max(4, min(12, round(han / 5) or 4))
        shots.append(
            {
                "id": f"V{index:02d}",
                "duration_hint": f"约{seconds}秒（硬上限12秒）",
                "shot_type": "",
                "camera": "",
                "protagonist": display_speaker(group["lines"][0]["speaker"]),
                "action": "",
                "dialogue": [
                    {
                        "speaker": display_speaker(line["speaker"]),
                        "text": line["text"],
                    }
                    for line in group["lines"]
                ],
                "sfx": "",
                "lighting": "",
                "scene_ref": f"场景 {group['scene_id']}（{group['section']['title']}）",
                "ref_images": "",
                "scene_id": group["scene_id"],
            }
        )

    title_hint = resolved[0]["title"] if resolved else "未命名"
    return {
        "preamble": script_preamble(script),
        "sections": [
            {"index": section["index"], "title": section["title"], "mode": section["mode"]}
            for section in resolved
        ],
        "title_hint": title_hint,
        "characters": [{"name": name} for name in names],
        "scenes": scenes,
        "shots": shots,
        "voice_lines": voice_lines,
        "shot_texts": shot_texts,
        "voice_only_texts": voice_only_texts,
    }


def _rows(data: dict[str, Any], key: str) -> list[Any]:
    rows = data.get(key)
    if isinstance(rows, list):
        return rows
    episode = data.get("episode")
    if isinstance(episode, dict) and isinstance(episode.get(key), list):
        return episode[key]
    return []


def _by_key(rows: list[Any], key: str) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and str(row.get(key) or "").strip():
            found[str(row[key]).strip()] = row
    return found


def _fill(target: dict[str, Any], source: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        value = str(source.get(key) or "").strip()
        if value:
            target[key] = value


def _merge(locked: dict[str, Any], creative: dict[str, Any]) -> dict[str, Any]:
    title = str(creative.get("title") or "").strip() or locked["title_hint"]
    episode_in = creative.get("episode") if isinstance(creative.get("episode"), dict) else {}
    title = str(episode_in.get("title") or "").strip() or title
    characters = []
    by_name = _by_key(_rows(creative, "characters"), "name")
    for index, spec in enumerate(locked["characters"], start=1):
        source = by_name.get(spec["name"], {})
        row = {
            "id": str(source.get("id") or f"role-{index}"),
            "name": spec["name"],
            "appearance": "",
            "wardrobe": "",
            "expression": "",
        }
        _fill(row, source, ("appearance", "wardrobe", "expression"))
        characters.append(row)

    scenes = []
    by_scene = _by_key(_rows(creative, "scenes"), "id")
    model_scenes = [row for row in _rows(creative, "scenes") if isinstance(row, dict)]
    for index, spec in enumerate(locked["scenes"]):
        source = by_scene.get(spec["id"]) or (model_scenes[index] if index < len(model_scenes) else {})
        row = {
            "id": spec["id"],
            "label": spec["label"],
            "time_of_day": "",
            "space": "",
            "light": "",
            "props": "",
        }
        _fill(row, source, ("label", "time_of_day", "space", "light", "props"))
        scenes.append(row)

    by_shot = _by_key(_rows(creative, "shots"), "id")
    model_shots = [row for row in _rows(creative, "shots") if isinstance(row, dict)]
    shots = []
    for index, spec in enumerate(locked["shots"]):
        source = by_shot.get(spec["id"]) or (model_shots[index] if index < len(model_shots) else {})
        row = {key: value for key, value in spec.items() if key != "scene_id"}
        _fill(row, source, ("shot_type", "camera", "protagonist", "action", "sfx", "lighting"))
        row["dialogue"] = spec["dialogue"]
        row["scene_ref"] = spec["scene_ref"]
        row["duration_hint"] = spec["duration_hint"]
        row["ref_images"], row["scene_slot"] = _ref_images(spec)
        shots.append(row)

    return {
        "title": title,
        "style": "cinematic-photoreal-short-drama",
        "source": "studio",
        "scope": str(creative.get("scope") or episode_in.get("scope") or "按勾选出镜"),
        "characters": characters,
        "scenes": scenes,
        "shots": shots,
    }


def _mixed(index: int) -> str:
    return f"{{{{Mixed {index}}}}}"


def _ref_images(spec: dict[str, Any]) -> tuple[str, str]:
    """出镜角色各留一张三视图，最后一张只留场景占位。不写段落标题。"""
    speakers: list[str] = []
    for item in spec.get("dialogue") or []:
        name = str(item.get("speaker") or "").strip()
        if name and name != NARRATOR and name not in speakers:
            speakers.append(name)
    parts: list[str] = []
    index = 1
    for name in speakers:
        parts.append(f"图{index}: {_mixed(index)} {name}三视图")
        index += 1
    parts.append(f"图{index}: {_mixed(index)}")
    return "；".join(parts), _mixed(index)


def assert_shot_membership(episode: dict[str, Any], locked: dict[str, Any]) -> None:
    allowed = set(locked["shot_texts"])
    banned = set(locked["voice_only_texts"])
    for shot in episode.get("shots") or []:
        for item in shot.get("dialogue") or []:
            text = str(item.get("text") or "")
            if text not in allowed:
                raise ValueError(f"分镜台词不属于勾选的出镜段: {text}")
            if text in banned:
                raise ValueError(f"只配音的句子进了分镜: {text}")


def _creative_prompt(locked: dict[str, Any]) -> str:
    shot_lines = []
    for shot in locked["shots"]:
        lines = " / ".join(
            f"{item['speaker']}：{item['text']}" for item in shot["dialogue"]
        )
        shot_lines.append(f"{shot['id']}｜{shot['scene_ref']}｜{lines}")
    names = "、".join(item["name"] for item in locked["characters"]) or "无"
    scenes = "、".join(f"{item['id']}（{item['label']}）" for item in locked["scenes"]) or "无"
    return (
        f"角色说明：\n{locked['preamble'] or '（无）'}\n\n"
        f"角色名单：{names}\n"
        f"场景：{scenes}\n"
        f"已锁定分镜：\n" + "\n".join(shot_lines)
    )


def _creative_chat(messages: list[dict[str, str]]) -> str:
    return chat(messages, response_format={"type": "json_object"}, max_tokens=8192)


def compile_bundle(
    script: str,
    selections: list[dict[str, Any]],
    *,
    chat_fn: ChatFn | None = None,
) -> dict[str, Any]:
    script = script.strip()
    if len(script) < 20:
        raise ValueError("脚本太短")
    locked = build_locked(script, selections)
    creative: dict[str, Any] = {}
    ask = chat_fn or _creative_chat
    if locked["shots"]:
        raw = ask(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _creative_prompt(locked)},
            ]
        )
        creative = extract_json(raw)
        if not isinstance(creative, dict):
            raise ValueError("模型没有返回 JSON")
    episode = _merge(locked, creative)
    assert_shot_membership(episode, locked)
    voiceover = {
        "title": f"{episode['title']}（整集配音）",
        "note": "id 为整集脚本时间线顺序",
        "lines": locked["voice_lines"],
    }
    slug = str(creative.get("slug") or "")
    return validate_bundle(
        {"slug": slug, "episode": episode, "voiceover": voiceover},
        script,
    )
