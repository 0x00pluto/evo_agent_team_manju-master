"""把原稿整理成标准分段脚本。提示词在 prompt_templates/script_normalize.md。"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from src.deepseek_client import chat
from src.prompt_fill import read_template
from src.studio.compile_episode import (
    bracket_title,
    extract_json,
    looks_like_many_beats,
    parse_sections,
)

ChatFn = Callable[..., str]

FAIL = "没能把脚本整理成分段"
_TONE_RE = re.compile(r"(?:（[^）]{0,12}）|\([^)]{0,12}\))$")


def _is_image_line(line: str) -> bool:
    """配图地址里有冒号，不能送去当台词。"""
    return line.startswith("![")


def _strip_images(script: str) -> str:
    kept = [raw for raw in script.splitlines() if not _is_image_line(raw.strip())]
    return "\n".join(kept)


def _rendered_usable(script: str, sections: list[dict[str, Any]]) -> bool:
    """模型结果至少一段、每段有句子。说话人保留原名，不再查别名表。"""
    if not sections:
        return False
    if len(sections) < 2 and looks_like_many_beats(script):
        return False
    for section in sections:
        items = section.get("items") or []
        if not items:
            return False
    return True


def _clean_speaker(raw: str) -> str:
    return _TONE_RE.sub("", raw.strip()).strip()


def _proposal(data: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    preamble = str(data.get("preamble") or "")
    rows = data.get("sections")
    if not isinstance(rows, list) or not rows:
        raise ValueError("模型没有返回分段")
    sections: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("分段格式不对")
        title = str(item.get("title") or "").replace("【", "").replace("】", "").strip()
        if not title:
            raise ValueError("分段没有标题")
        lines_in = item.get("lines")
        if not isinstance(lines_in, list):
            raise ValueError("分段没有句子")
        lines: list[dict[str, str]] = []
        for line in lines_in:
            if not isinstance(line, dict):
                raise ValueError("句子格式不对")
            text = str(line.get("text") or "").strip()
            if not text or _is_image_line(text):
                continue
            lines.append({"speaker": _clean_speaker(str(line.get("speaker") or "")), "text": text})
        if not lines:
            raise ValueError("分段没有句子")
        sections.append({"title": title, "lines": lines})
    if not sections:
        raise ValueError("模型没有返回分段")
    return preamble, sections


def _lines_in_source(script: str, sections: list[dict[str, Any]]) -> bool:
    for section in sections:
        for line in section["lines"]:
            text = line["text"]
            if not text or text not in script:
                return False
    return True


def _safe_preamble(text: str) -> str:
    rows: list[str] = []
    for raw in text.splitlines():
        if bracket_title(raw) or _is_image_line(raw.strip()):
            continue
        rows.append(raw)
    return "\n".join(rows).strip()


def render_standard_script(preamble: str, sections: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    pre = _safe_preamble(preamble)
    if pre:
        chunks.extend([pre, ""])
    for section in sections:
        chunks.extend([f"【{section['title']}】", ""])
        for line in section["lines"]:
            speaker = line["speaker"]
            text = line["text"]
            chunks.append(f"{speaker}：{text}" if speaker else text)
            chunks.append("")
    return "\n".join(chunks).strip() + "\n"


def load_prompt() -> str:
    return read_template("script_normalize.md").strip()


def _standard_chat(messages: list[dict[str, str]]) -> str:
    # 整理分段只核对原文，不需要长思维链。
    return chat(messages, thinking=False)


def _ask(script: str, chat_fn: ChatFn) -> tuple[str, list[dict[str, Any]]]:
    raw = chat_fn(
        [
            {"role": "system", "content": load_prompt()},
            {"role": "user", "content": script},
        ]
    )
    return _proposal(extract_json(raw))


def preprocess_script(script: str, *, chat_fn: ChatFn | None = None) -> str:
    """丢掉配图后一律叫模型。台词对不上原文就再请求一次。"""
    cleaned = _strip_images(script)
    ask = chat_fn or _standard_chat
    saw_content = False
    last_runtime: BaseException | None = None
    for _ in range(2):
        try:
            preamble, proposed = _ask(cleaned, ask)
        except (RuntimeError, OSError) as exc:
            last_runtime = exc
            continue
        except (ValueError, json.JSONDecodeError):
            saw_content = True
            continue
        saw_content = True
        if not _lines_in_source(script, proposed):
            continue
        rendered = render_standard_script(preamble, proposed)
        if _rendered_usable(rendered, parse_sections(rendered)):
            return rendered
    if not saw_content and last_runtime is not None:
        raise last_runtime
    raise ValueError(FAIL)
