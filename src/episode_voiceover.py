"""整集口播配音。操作台在进程内调用，避免冻结后把二进制当成 python 再开脚本。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from src.env_load import plugin_root
from src.minimax_tts import synthesize_to_mp3

SPEAKER_SLUG = {
    "招商顾问": "advisor",
    "企业主": "owner",
}


def load_voice(slug: str, repo_root: Path | None = None) -> dict:
    root = repo_root or plugin_root()
    path = root / "assets" / "voices" / slug / "voice.json"
    if not path.is_file():
        raise FileNotFoundError(f"找不到音色清单: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("voice_id"):
        raise ValueError(f"{path} 缺少 voice_id")
    return data


def speaker_file_slug(speaker: str) -> str:
    return SPEAKER_SLUG.get(speaker, speaker.replace(" ", "-"))


def merge_result_lines(previous: list, updates: list) -> list:
    """按 id 替换已有记录，其余条留在原位。"""
    order: list[str] = []
    by_id: dict = {}
    for row in previous:
        if not isinstance(row, dict):
            continue
        lid = str(row.get("id") or "")
        if not lid or lid in by_id:
            continue
        by_id[lid] = row
        order.append(lid)
    for row in updates:
        if not isinstance(row, dict):
            continue
        lid = str(row.get("id") or "")
        if not lid:
            continue
        if lid not in by_id:
            order.append(lid)
        by_id[lid] = row
    return [by_id[lid] for lid in order]


def synthesize_one(
    *,
    voice_id: str,
    model: str,
    text_file: Path,
    out_mp3: Path,
    dry_run: bool,
    speak: Callable[..., dict[str, Any]] | None = None,
) -> dict:
    text = text_file.read_text(encoding="utf-8")
    if dry_run:
        return {
            "dry_run": True,
            "voice_id": voice_id,
            "model": model,
            "text_file": str(text_file),
            "out": str(out_mp3),
            "char_count": len(text),
        }
    fn = speak or synthesize_to_mp3
    try:
        return fn(voice_id=voice_id, text=text, out_path=out_mp3, model=model)
    except RuntimeError as exc:
        raise RuntimeError(f"TTS 失败 ({voice_id}): {exc}") from exc


def synthesize_manifest(
    manifest: Path,
    out_dir: Path,
    *,
    only: list[str] | None = None,
    dry_run: bool = False,
    repo_root: Path | None = None,
    log: Callable[[str], None] | None = None,
) -> None:
    """按清单出 MP3。失败抛 RuntimeError。不写 stdout，免得弄脏 Hub 的 JSON 行。"""
    root = repo_root or plugin_root()
    manifest_path = Path(manifest).expanduser()
    if not manifest_path.is_file():
        alt = root / manifest
        if alt.is_file():
            manifest_path = alt
        else:
            raise FileNotFoundError(f"找不到清单: {manifest}")
    dest = Path(out_dir).expanduser()
    if not dest.is_absolute():
        dest = root / dest
    dest.mkdir(parents=True, exist_ok=True)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    lines = data.get("lines") or []
    chosen = set(only or [])

    def say(message: str) -> None:
        if log:
            log(message)

    results: list[dict] = []
    for line in lines:
        lid = line["id"]
        if chosen and lid not in chosen:
            continue
        text = line["text"]
        # 引号必须原样；禁止剥引号。仅信任清单正文。
        voice = load_voice(line["voice_slug"], root)
        voice_id = voice["voice_id"]
        model = voice.get("model") or "speech-2.8-hd"
        file_slug = speaker_file_slug(line["speaker"])
        stem = f"{lid}_{file_slug}"
        text_file = dest / f"{stem}.txt"
        out_mp3 = dest / f"{stem}.mp3"
        text_file.write_text(text, encoding="utf-8")
        entry = {
            "id": lid,
            "segment": line.get("segment"),
            "speaker": line["speaker"],
            "voice_slug": line["voice_slug"],
            "voice_id": voice_id,
            "model": model,
            "text_file": str(text_file),
            "mp3": str(out_mp3),
            "char_count": len(text),
        }
        say(f"[{lid}] {line['speaker']} → {voice_id} ({len(text)} 字)")
        try:
            entry["tts"] = synthesize_one(
                voice_id=voice_id,
                model=model,
                text_file=text_file,
                out_mp3=out_mp3,
                dry_run=dry_run,
            )
            entry["ok"] = True
        except Exception as exc:  # noqa: BLE001 — 汇总后一次抛出
            entry["ok"] = False
            entry["error"] = str(exc)
            say(f"  FAIL: {exc}")
        results.append(entry)

    out_manifest = dest / "manifest-out.json"
    lines_out = results
    if chosen and out_manifest.is_file():
        previous = json.loads(out_manifest.read_text(encoding="utf-8"))
        lines_out = merge_result_lines(previous.get("lines") or [], results)
    out_manifest.write_text(
        json.dumps(
            {
                "source_manifest": str(manifest_path),
                "title": data.get("title"),
                "lines": lines_out,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    say(f"wrote {out_manifest}")
    failed = [row for row in results if not row.get("ok")]
    if failed:
        detail = "\n".join(str(row.get("error") or row["id"]) for row in failed)
        raise RuntimeError(detail or f"{len(failed)} 条失败")
    if not results:
        raise RuntimeError("没有要配的台词（检查 --only）")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="整集成片配音：voiceover 清单 → MiniMax TTS → MP3"
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out-dir", default="output/hanyangzao-hook-cta/voiceover")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", action="append", default=[])
    args = parser.parse_args(argv)

    def say(message: str) -> None:
        stream = sys.stderr if message.startswith("  FAIL:") else sys.stdout
        print(message, file=stream, flush=True)

    try:
        synthesize_manifest(
            Path(args.manifest),
            Path(args.out_dir),
            only=args.only,
            dry_run=args.dry_run,
            log=say,
        )
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        if "没有要配" in str(exc):
            return 2
        return 1
    return 0
