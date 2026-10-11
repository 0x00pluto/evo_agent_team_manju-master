"""从已生成的 output/<主题>/ 抽出可复制块与配音列表。"""

from __future__ import annotations

import re
from pathlib import Path

_THEME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_CN_BLOCK = re.compile(r"### 【中文提示词】\s*```(?:text)?\n(.*?)```", re.S)
_SHOT_BLOCK = re.compile(
    r"^## ([A-Za-z0-9][A-Za-z0-9_-]*)\s*\n+```(?:text)?\n(.*?)```",
    re.M | re.S,
)
_SCENE_HEAD = re.compile(r"^## ([A-Za-z0-9_-]+) · (.+)$", re.M)
_VOICE_NAME = re.compile(r"^(\d{2})_([A-Za-z0-9][A-Za-z0-9_-]*)\.mp3$")
_FILE_SPEAKER = {"owner": "企业主", "advisor": "招商顾问", "narration": "旁白"}


def validate_theme(theme: str) -> str:
    t = (theme or "").strip()
    if not _THEME_RE.match(t) or len(t) > 64:
        raise ValueError("主题名仅允许小写字母、数字和短横线")
    return t


def _fact_paths(root: Path, theme: str, *, code_root: Path | None = None) -> tuple[Path, Path]:
    """操作台事实在数据根的 temp；参考稿仍在代码根的 assets/episodes。"""
    theme = validate_theme(theme)
    code = Path(code_root) if code_root is not None else Path(root)
    bases = (
        Path(root) / "temp" / "studio_facts",
        code / "assets" / "episodes",
    )
    for base in bases:
        episode = base / f"{theme}.json"
        voice = base / f"{theme}-voiceover.json"
        if episode.is_file() and voice.is_file():
            return episode, voice
    fallback = bases[-1]
    return fallback / f"{theme}.json", fallback / f"{theme}-voiceover.json"


def output_dir(root: Path, theme: str) -> Path:
    base = (Path(root) / "output").resolve()
    target = (base / validate_theme(theme)).resolve()
    if not target.is_relative_to(base):
        raise ValueError("主题路径越界")
    return target


def voice_dir(root: Path, theme: str) -> Path:
    base = output_dir(root, theme)
    target = (base / "voiceover").resolve()
    if not target.is_relative_to(base):
        raise ValueError("配音路径越界")
    return target


def voice_mp3(root: Path, theme: str, filename: str) -> Path:
    """只打开这一集 voiceover 里、文件名符合 01_owner.mp3 的那一条。"""
    name = Path(str(filename or "")).name
    if name != str(filename or "") or not _VOICE_NAME.match(name):
        raise ValueError("配音文件不对")
    folder = voice_dir(root, theme).resolve()
    target = (folder / name).resolve()
    if not target.is_relative_to(folder) or not target.is_file():
        raise FileNotFoundError("文件不存在")
    return target


def _cn_blocks(text: str) -> list[str]:
    return [m.group(1).strip() for m in _CN_BLOCK.finditer(text)]


def _split_sections(text: str, headings: tuple[str, ...]) -> dict[str, str]:
    """按二级标题切开，键为标题原文。"""
    parts = re.split(r"^## ", text, flags=re.M)
    found: dict[str, str] = {}
    for part in parts[1:]:
        line, _, body = part.partition("\n")
        title = line.strip()
        if title in headings:
            found[title] = body
    return found


def parse_character_file(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    name_m = re.search(r"^# 角色：(.+)$", text, re.M)
    name = name_m.group(1).strip() if name_m else path.stem
    sections = _split_sections(text, ("三视图", "面部特写"))
    blocks: list[dict[str, str]] = []
    for kind in ("三视图", "面部特写"):
        body = sections.get(kind, "")
        cn = _cn_blocks(body)
        if not cn:
            continue
        blocks.append({"name": name, "kind": kind, "text": cn[0]})
    return blocks


def parse_scenes(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    heads = list(_SCENE_HEAD.finditer(text))
    scenes: list[dict[str, str]] = []
    for i, head in enumerate(heads):
        start = head.end()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        cn = _cn_blocks(text[start:end])
        if not cn:
            continue
        scenes.append(
            {
                "id": head.group(1),
                "label": head.group(2).strip(),
                "text": cn[0],
            }
        )
    return scenes


def parse_shots(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    return [
        {"id": m.group(1), "text": m.group(2).strip()}
        for m in _SHOT_BLOCK.finditer(text)
    ]


def parse_title(path: Path) -> str:
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _speakers_by_id(root: Path, theme: str, code_root: Path | None) -> dict[str, str]:
    try:
        _episode, voice_path = _fact_paths(root, theme, code_root=code_root)
    except ValueError:
        return {}
    if not voice_path.is_file():
        return {}
    import json

    data = json.loads(voice_path.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for line in data.get("lines") or []:
        if isinstance(line, dict) and line.get("id"):
            found[str(line["id"])] = str(line.get("speaker") or "")
    return found


def list_voice(root: Path, theme: str, *, code_root: Path | None = None) -> list[dict[str, str]]:
    folder = voice_dir(root, theme)
    if not folder.is_dir():
        return []
    speakers = _speakers_by_id(root, theme, code_root)
    rows: list[dict[str, str]] = []
    for mp3 in sorted(folder.glob("*.mp3")):
        m = _VOICE_NAME.match(mp3.name)
        if not m:
            continue
        txt = mp3.with_suffix(".txt")
        text = txt.read_text(encoding="utf-8").strip() if txt.is_file() else ""
        speaker = speakers.get(m.group(1)) or _FILE_SPEAKER.get(m.group(2), m.group(2))
        rows.append(
            {
                "id": m.group(1),
                "speaker": speaker,
                "file": mp3.name,
                "url": f"/media/{theme}/voiceover/{mp3.name}",
                "text": text,
            }
        )
    return rows


def load_bench(root: Path, theme: str, *, code_root: Path | None = None) -> dict:
    theme = validate_theme(theme)
    out = output_dir(root, theme)
    if not (out / "03-分镜.md").is_file() and not list(out.glob("01-角色-*.md")):
        raise FileNotFoundError(f"还没有这一集的提示词: {theme}")

    characters: list[dict[str, str]] = []
    for path in sorted(out.glob("01-角色-*.md")):
        characters.extend(parse_character_file(path))

    brief_path = out / "studio-brief.json"
    summary = {"shots": [], "voice_only": []}
    instruction = ""
    if brief_path.is_file():
        import json

        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        summary = brief.get("summary") or summary
        instruction = str(brief.get("instruction") or "")
    summary.setdefault("shots", [])
    summary.setdefault("voice_only", [])

    if not summary.get("shots"):
        episode_path, vo_path = _fact_paths(root, theme, code_root=code_root)
        if episode_path.is_file() and vo_path.is_file():
            import json

            episode = json.loads(episode_path.read_text(encoding="utf-8"))
            voiceover = json.loads(vo_path.read_text(encoding="utf-8"))
            summary = summary_from_facts(episode, voiceover)

    return {
        "theme": theme,
        "title": parse_title(out / "00-使用说明.md") or theme,
        "instruction": instruction,
        "summary": summary,
        "characters": characters,
        "scenes": parse_scenes(out / "02-场景.md"),
        "shots": parse_shots(out / "03-分镜.md"),
        "voice": list_voice(root, theme, code_root=code_root),
    }


def summary_from_facts(episode: dict, voiceover: dict) -> dict:
    shot_texts: list[str] = []
    shots: list[dict[str, str]] = []
    for sh in episode.get("shots") or []:
        lines = [str(d.get("text") or "") for d in (sh.get("dialogue") or [])]
        shot_texts.extend(lines)
        shots.append(
            {
                "id": str(sh.get("id") or ""),
                "preview": " / ".join(x for x in lines if x)[:80],
            }
        )
    voice_only: list[dict[str, str]] = []
    for line in voiceover.get("lines") or []:
        text = str(line.get("text") or "")
        if text in shot_texts:
            continue
        voice_only.append(
            {
                "id": str(line.get("id") or ""),
                "segment": str(line.get("segment") or ""),
                "preview": text[:80],
            }
        )
    return {"shots": shots, "voice_only": voice_only}


def list_recent(root: Path, *, limit: int = 8) -> list[dict[str, str]]:
    out = Path(root) / "output"
    if not out.is_dir():
        return []
    rows: list[dict[str, str]] = []
    for child in out.iterdir():
        if not child.is_dir():
            continue
        try:
            theme = validate_theme(child.name)
        except ValueError:
            continue
        marker = child / "03-分镜.md"
        if not marker.is_file():
            continue
        rows.append(
            {
                "theme": theme,
                "title": parse_title(child / "00-使用说明.md") or theme,
                "updated_at": str(int(marker.stat().st_mtime)),
            }
        )
    rows.sort(key=lambda r: r["updated_at"], reverse=True)
    return rows[:limit]
