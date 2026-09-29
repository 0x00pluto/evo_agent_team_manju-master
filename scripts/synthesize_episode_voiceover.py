#!/usr/bin/env python3
"""整集成片配音：读 voiceover 清单，调兄弟仓 MiniMax TTS 逐句出 MP3。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SIBLING = Path(
    os.environ.get(
        "IP_DIGITAL_HUMAN_ROOT",
        "/Users/peng.zhi/Documents/Codex/IP数字人项目",
    )
)
SPEAKER_SLUG = {
    "招商顾问": "advisor",
    "企业主": "owner",
}


def load_voice(slug: str) -> dict:
    path = REPO_ROOT / "assets" / "voices" / slug / "voice.json"
    if not path.is_file():
        raise FileNotFoundError(f"找不到音色清单: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("voice_id"):
        raise ValueError(f"{path} 缺少 voice_id")
    return data


def speaker_file_slug(speaker: str) -> str:
    return SPEAKER_SLUG.get(speaker, speaker.replace(" ", "-"))


def synthesize_one(
    *,
    sibling_root: Path,
    voice_id: str,
    model: str,
    text_file: Path,
    out_mp3: Path,
    dry_run: bool,
) -> dict:
    cli = sibling_root / "scripts" / "media" / "synthesize-voice.mjs"
    if not cli.is_file():
        raise FileNotFoundError(
            f"找不到兄弟仓 TTS CLI: {cli}\n"
            "设置 IP_DIGITAL_HUMAN_ROOT 指向「IP数字人项目」根目录。"
        )
    cmd = [
        "node",
        str(cli),
        "--voice-id",
        voice_id,
        "--text-file",
        str(text_file),
        "--out",
        str(out_mp3),
        "--model",
        model,
    ]
    if dry_run:
        return {"dry_run": True, "cmd": cmd}
    proc = subprocess.run(
        cmd,
        cwd=str(sibling_root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"TTS 失败 ({voice_id}): {err or proc.returncode}")
    # stdout 为结果 JSON；失败信息在 stderr
    payload: dict = {}
    out = (proc.stdout or "").strip()
    if out:
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            payload = {"raw_stdout": out}
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="整集成片配音：voiceover 清单 → 兄弟仓 MiniMax TTS → MP3"
    )
    parser.add_argument(
        "--manifest",
        required=True,
        help="配音清单 JSON（assets/episodes/*-voiceover.json）",
    )
    parser.add_argument(
        "--out-dir",
        default="output/hanyangzao-hook-cta/voiceover",
        help="配音产物目录",
    )
    parser.add_argument(
        "--sibling-root",
        default=str(DEFAULT_SIBLING),
        help="IP数字人项目根目录（或设 IP_DIGITAL_HUMAN_ROOT）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的命令")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="只配指定 id，可重复（如 --only M03）",
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest).expanduser()
    if not manifest_path.is_file():
        # 相对本仓根
        alt = REPO_ROOT / args.manifest
        if alt.is_file():
            manifest_path = alt
        else:
            print(f"找不到清单: {args.manifest}", file=sys.stderr)
            return 2

    out_dir = Path(args.out_dir).expanduser()
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    sibling = Path(args.sibling_root).expanduser()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    lines = data.get("lines") or []
    only = set(args.only)

    results: list[dict] = []
    for line in lines:
        lid = line["id"]
        if only and lid not in only:
            continue
        text = line["text"]
        # 引号必须原样；禁止剥引号。仅信任清单正文。
        voice = load_voice(line["voice_slug"])
        voice_id = voice["voice_id"]
        model = voice.get("model") or "speech-2.8-hd"
        file_slug = speaker_file_slug(line["speaker"])
        stem = f"{lid}_{file_slug}"
        text_file = out_dir / f"{stem}.txt"
        out_mp3 = out_dir / f"{stem}.mp3"
        # 与清单 text 一致写入（含 ASCII 引号）
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
        print(f"[{lid}] {line['speaker']} → {voice_id} ({len(text)} 字)", flush=True)
        try:
            tts = synthesize_one(
                sibling_root=sibling,
                voice_id=voice_id,
                model=model,
                text_file=text_file,
                out_mp3=out_mp3,
                dry_run=args.dry_run,
            )
            entry["tts"] = tts
            entry["ok"] = True
        except Exception as exc:  # noqa: BLE001 — 汇总后非零退出
            entry["ok"] = False
            entry["error"] = str(exc)
            print(f"  FAIL: {exc}", file=sys.stderr, flush=True)
        results.append(entry)

    out_manifest = out_dir / "manifest-out.json"
    out_manifest.write_text(
        json.dumps(
            {
                "source_manifest": str(manifest_path),
                "title": data.get("title"),
                "lines": results,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out_manifest}")
    failed = [r for r in results if not r.get("ok")]
    if failed:
        print(f"{len(failed)} 条失败", file=sys.stderr)
        return 1
    if not results:
        print("没有要配的台词（检查 --only）", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
