"""提示词模板加载与 {{placeholder}} 填充（标准库，无 Jinja）。"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent / "prompt_templates"


def default_templates_dir() -> Path:
    """模板放在源码旁，随仓库一起发给同事。"""
    return TEMPLATES_DIR


PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)


def parse_style_id(manifest_text: str) -> str:
    for line in manifest_text.splitlines():
        stripped = line.strip().strip("`")
        if stripped.startswith("style_id:"):
            return stripped.split(":", 1)[1].strip().strip("`")
    raise ValueError("manifest.md 缺少 style_id")


def strip_frontmatter(text: str) -> str:
    return FRONTMATTER_RE.sub("", text, count=1).lstrip()


def read_template(name: str, *, templates_dir: Path | None = None) -> str:
    root = templates_dir or default_templates_dir()
    path = root / name
    if not path.is_file():
        raise FileNotFoundError(f"模板不存在: {path}")
    return strip_frontmatter(path.read_text(encoding="utf-8"))


def load_style_and_duration(*, templates_dir: Path | None = None) -> dict[str, str]:
    root = templates_dir or default_templates_dir()
    manifest = (root / "manifest.md").read_text(encoding="utf-8")
    style_id = parse_style_id(manifest)
    style = read_template(f"style/{style_id}.md", templates_dir=root)
    duration = read_template("duration.md", templates_dir=root)
    blocking = read_template("blocking.md", templates_dir=root)
    return {
        "style": style,
        "duration_rules": duration,
        "blocking_rules": blocking,
        "style_id": style_id,
    }


def fill(template: str, variables: dict[str, str]) -> str:
    missing: set[str] = set()

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            missing.add(key)
            return match.group(0)
        return variables[key]

    out = PLACEHOLDER_RE.sub(repl, template)
    if missing:
        raise KeyError(f"模板缺少占位符取值: {sorted(missing)}")
    leftover = PLACEHOLDER_RE.findall(out)
    if leftover:
        raise KeyError(f"填充后仍有未替换占位符: {sorted(set(leftover))}")
    return out


def build_prompt(module_file: str, variables: dict[str, str], *, templates_dir: Path | None = None) -> str:
    """组装发给 DeepSeek 的完整 user 提示（含风格/时长注入）。"""
    root = templates_dir or default_templates_dir()
    base = load_style_and_duration(templates_dir=root)
    merged = {**base, **variables}
    # style_id 不是模板占位符，去掉以免干扰
    merged.pop("style_id", None)
    body = read_template(module_file, templates_dir=root)
    return fill(body, merged)
