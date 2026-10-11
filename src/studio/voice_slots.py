"""音色插槽存在插件数据里。包内 voice_id 只作档案，不参与克隆和合成。"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from src.minimax_tts import DEFAULT_MODEL, require_api_key
from src.studio.audio_sample import SampleError, prepare_sample
from src.studio.bench import validate_theme

STATUS_LABEL = {
    "ready": "可用",
    "not_ready": "还不能用",
    "cloning": "生成中",
    "failed": "失败",
}
_DEFAULTS = (
    ("ai-enterprise-owner", "AI企业主"),
    ("female-zhao-shang-lead", "女招商主管"),
)
_DEFAULT_MATCH = {
    "企业主": "ai-enterprise-owner",
    "企业老板": "ai-enterprise-owner",
    "招商运营": "female-zhao-shang-lead",
    "招商顾问": "female-zhao-shang-lead",
    "招商主管": "female-zhao-shang-lead",
    "女招商主管": "female-zhao-shang-lead",
}
_SLOT_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_lock = threading.Lock()


def slots_path(data_root: Path) -> Path:
    return Path(data_root) / "voice-slots.json"


def cast_path(data_root: Path, theme: str) -> Path:
    theme = validate_theme(theme)
    return Path(data_root) / "temp" / "studio_facts" / f"{theme}-cast.json"


def _blank(slot_id: str, name: str, *, sample_kind: str, sample: str, packaged: str) -> dict[str, Any]:
    return {
        "id": slot_id,
        "name": name,
        "sample_kind": sample_kind,
        "sample": sample,
        "packaged_voice_id": packaged,
        "account_voice_id": "",
        "model": "",
        "status": "not_ready",
        "error": "",
    }


def seed_slots(code_root: Path) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for slug, fallback in _DEFAULTS:
        meta_path = Path(code_root) / "assets" / "voices" / slug / "voice.json"
        name = fallback
        sample = f"assets/voices/{slug}/voice.mp3"
        packaged = ""
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            name = str(meta.get("name") or fallback)
            sample_name = str(meta.get("sample") or "voice.mp3")
            sample = f"assets/voices/{slug}/{sample_name}"
            packaged = str(meta.get("voice_id") or "")
        slots.append(
            _blank(slug, name, sample_kind="package", sample=sample, packaged=packaged)
        )
    return slots


def _recover(slots: list[dict[str, Any]]) -> bool:
    changed = False
    for slot in slots:
        if slot.get("status") != "cloning":
            continue
        changed = True
        if str(slot.get("account_voice_id") or "").strip():
            slot["status"] = "ready"
            slot["error"] = "上次替换中断，仍使用原来的音色"
        else:
            slot["status"] = "failed"
            slot["account_voice_id"] = ""
            slot["error"] = "克隆中断，请重试"
    return changed


def load_slots(data_root: Path, code_root: Path) -> list[dict[str, Any]]:
    path = slots_path(data_root)
    if not path.is_file():
        slots = seed_slots(code_root)
        save_slots(data_root, slots)
        return slots
    data = json.loads(path.read_text(encoding="utf-8"))
    slots = data.get("slots") if isinstance(data, dict) else None
    if not isinstance(slots, list):
        slots = seed_slots(code_root)
        save_slots(data_root, slots)
        return slots
    return slots


def recover_slots(data_root: Path, code_root: Path) -> None:
    """进程重启后，停在克隆中的插槽不能一直占着。没有文件时不新建。"""
    if not slots_path(data_root).is_file():
        return
    slots = load_slots(data_root, code_root)
    if _recover(slots):
        save_slots(data_root, slots)


def save_slots(data_root: Path, slots: list[dict[str, Any]]) -> None:
    path = slots_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"slots": slots}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def public_slot(slot: dict[str, Any]) -> dict[str, Any]:
    status = str(slot.get("status") or "not_ready")
    if status not in STATUS_LABEL:
        status = "not_ready"
    ready = status == "ready" and bool(str(slot.get("account_voice_id") or "").strip())
    return {
        "id": slot["id"],
        "name": slot["name"],
        "status": status,
        "status_label": STATUS_LABEL[status],
        "error": str(slot.get("error") or ""),
        "selectable": ready,
    }


def minimax_ready() -> bool:
    return bool((os.environ.get("MINIMAX_API_KEY") or "").strip())


def sample_file(slot: dict[str, Any], data_root: Path, code_root: Path) -> Path:
    raw = str(slot.get("sample") or "")
    base = Path(code_root) if slot.get("sample_kind") == "package" else Path(data_root)
    path = (base / raw).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError("样音路径越界")
    return path


def _find(slots: list[dict[str, Any]], slot_id: str) -> dict[str, Any]:
    for slot in slots:
        if slot.get("id") == slot_id:
            return slot
    raise ValueError("没有这个声音")


def _slot_ready(slot: dict[str, Any]) -> bool:
    return slot.get("status") == "ready" and bool(str(slot.get("account_voice_id") or "").strip())


def fill_defaults(rows: list[dict[str, Any]], slots: list[dict[str, Any]]) -> bool:
    """没人动过、且还空着的行，在对应默认声音已经可用时写上。"""
    by_id = {slot["id"]: slot for slot in slots}
    changed = False
    for row in rows:
        if row.get("touched") or row.get("slot_id"):
            continue
        slot_id = _DEFAULT_MATCH.get(str(row.get("speaker") or ""), "")
        slot = by_id.get(slot_id)
        if slot is None or not _slot_ready(slot):
            continue
        row["slot_id"] = slot_id
        changed = True
    return changed


def _save_cast(data_root: Path, theme: str, rows: list[dict[str, Any]]) -> None:
    path = cast_path(data_root, theme)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"rows": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_cast(
    data_root: Path,
    theme: str,
    lines: list[dict[str, Any]],
    *,
    code_root: Path | None = None,
) -> None:
    """按口播首次出现写下待绑定行。没有口播句就不留绑定文件。"""
    theme = validate_theme(theme)
    seen: list[str] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        speaker = str(line.get("speaker") or "").strip()
        if speaker and speaker not in seen:
            seen.append(speaker)
    path = cast_path(data_root, theme)
    if not seen:
        if path.is_file():
            path.unlink()
        return
    rows: list[dict[str, Any]] = [
        {"speaker": speaker, "slot_id": "", "touched": False} for speaker in seen
    ]
    fill_defaults(rows, load_slots(data_root, code_root or data_root))
    _save_cast(data_root, theme, rows)


def read_cast(data_root: Path, theme: str) -> list[dict[str, Any]] | None:
    path = cast_path(data_root, theme)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return None
    clean: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        speaker = str(row.get("speaker") or "").strip()
        if not speaker:
            continue
        clean.append(
            {
                "speaker": speaker,
                "slot_id": str(row.get("slot_id") or ""),
                "touched": bool(row.get("touched")),
            }
        )
    return clean


def apply_cast_defaults(
    data_root: Path,
    theme: str,
    slots: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """打开这一集时再补一次，后来才可用的默认声音也能对上还没人选过的行。"""
    rows = read_cast(data_root, theme)
    if rows is None:
        return None
    if fill_defaults(rows, slots):
        _save_cast(data_root, theme, rows)
    return rows


def bind_speaker(data_root: Path, theme: str, speaker: str, slot_id: str, slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = read_cast(data_root, theme)
    if rows is None:
        raise ValueError("这一集没有角色声音记录")
    speaker = speaker.strip()
    slot_id = slot_id.strip()
    if slot_id:
        slot = _find(slots, slot_id)
        if not _slot_ready(slot):
            raise ValueError("这个声音还不能用")
    found = False
    for row in rows:
        if row["speaker"] == speaker:
            row["slot_id"] = slot_id
            row["touched"] = True
            found = True
    if not found:
        raise ValueError("没有这个角色")
    _save_cast(data_root, theme, rows)
    return rows


def voice_block_reason(rows: list[dict[str, str]] | None, slots: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    by_id = {slot["id"]: slot for slot in slots}
    problems: list[str] = []
    for row in rows:
        speaker = row["speaker"]
        slot_id = row.get("slot_id") or ""
        if not slot_id:
            problems.append(f"{speaker}还没有选择音色")
            continue
        slot = by_id.get(slot_id)
        if slot is None:
            problems.append(f"{speaker}的音色不存在")
            continue
        if slot.get("status") != "ready" or not str(slot.get("account_voice_id") or "").strip():
            label = STATUS_LABEL.get(str(slot.get("status") or ""), "还不能用")
            problems.append(f"{speaker}的音色{label}")
    return "；".join(problems)


def account_voice(slot: dict[str, Any]) -> tuple[str, str]:
    """只返回本账号 voice_id。没有就不拿包内 id 顶上。"""
    voice_id = str(slot.get("account_voice_id") or "").strip()
    if slot.get("status") != "ready" or not voice_id:
        raise RuntimeError(f"{slot.get('name') or '音色'}还不能用于配音")
    model = str(slot.get("model") or DEFAULT_MODEL)
    return voice_id, model


def voice_for_speaker(speaker: str, rows: list[dict[str, str]], slots: list[dict[str, Any]]) -> tuple[str, str]:
    slot_id = ""
    for row in rows:
        if row["speaker"] == speaker:
            slot_id = row.get("slot_id") or ""
            break
    if not slot_id:
        raise RuntimeError(f"{speaker}还没有选择音色")
    for slot in slots:
        if slot.get("id") == slot_id:
            return account_voice(slot)
    raise RuntimeError(f"{speaker}的音色不存在")


def cast_view(rows: list[dict[str, str]] | None, slots: list[dict[str, Any]]) -> dict[str, Any]:
    if rows is None:
        return {"needs_cast": False, "rows": [], "voice_block": ""}
    by_id = {slot["id"]: public_slot(slot) for slot in slots}
    view_rows = []
    for row in rows:
        chosen = by_id.get(row.get("slot_id") or "")
        view_rows.append(
            {
                "speaker": row["speaker"],
                "slot_id": row.get("slot_id") or "",
                "slot_name": (chosen or {}).get("name") or "",
                "status": (chosen or {}).get("status") or "",
                "status_label": (chosen or {}).get("status_label") or "未选择",
            }
        )
    return {
        "needs_cast": True,
        "rows": view_rows,
        "voice_block": voice_block_reason(rows, slots),
    }


def _fail(slot: dict[str, Any], reason: str) -> None:
    if str(slot.get("account_voice_id") or "").strip():
        slot["status"] = "ready"
    else:
        slot["status"] = "failed"
        slot["account_voice_id"] = ""
    slot["error"] = reason


def _store_sample(data_root: Path, slot_id: str, audio: Path) -> str:
    dest_dir = Path(data_root) / "voice-slots" / slot_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "sample.mp3"
    dest.write_bytes(audio.read_bytes())
    return f"voice-slots/{slot_id}/sample.mp3"


def ensure_key() -> None:
    try:
        require_api_key()
    except RuntimeError as exc:
        raise RuntimeError("缺少 MINIMAX_API_KEY。请在设置里填写 MiniMax 密钥后再克隆。") from exc


def perform_clone(
    data_root: Path,
    code_root: Path,
    slot_id: str,
    *,
    upload_path: Path | None = None,
    clone_audio: Callable[..., tuple[str, str]] | None = None,
    prepare: Callable[..., Path] | None = None,
) -> dict[str, Any]:
    """用当前样音或一份新音轨克隆。失败时已成功过的 voice_id 保留。"""
    with _lock:
        slots = load_slots(data_root, code_root)
        slot = _find(slots, slot_id)
        slot["status"] = "cloning"
        slot["error"] = ""
        save_slots(data_root, slots)
    try:
        ensure_key()
        work = Path(data_root) / "temp" / "voice-clone" / uuid.uuid4().hex[:12]
        work.mkdir(parents=True, exist_ok=True)
        if upload_path is not None:
            ready = (prepare or prepare_sample)(upload_path, work)
        else:
            current = sample_file(slot, data_root, code_root)
            ready = (prepare or prepare_sample)(current, work)
        if clone_audio is None:
            from src.minimax_clone import activate_voice, clone_voice, new_voice_id, upload_clone_audio

            file_id = upload_clone_audio(ready)
            voice_id = new_voice_id()
            clone_voice(file_id, voice_id)
            activate_voice(voice_id, work / "activate.mp3")
            model = DEFAULT_MODEL
        else:
            voice_id, model = clone_audio(ready)
        with _lock:
            slots = load_slots(data_root, code_root)
            slot = _find(slots, slot_id)
            if upload_path is not None:
                slot["sample_kind"] = "upload"
                slot["sample"] = _store_sample(data_root, slot_id, ready)
            slot["account_voice_id"] = voice_id
            slot["model"] = model or DEFAULT_MODEL
            slot["status"] = "ready"
            slot["error"] = ""
            save_slots(data_root, slots)
            return public_slot(slot)
    except (SampleError, RuntimeError, OSError, ValueError) as exc:
        with _lock:
            slots = load_slots(data_root, code_root)
            slot = _find(slots, slot_id)
            _fail(slot, str(exc))
            save_slots(data_root, slots)
        raise


def add_slot(
    data_root: Path,
    code_root: Path,
    name: str,
    upload_path: Path,
    *,
    prepare: Callable[..., Path] | None = None,
) -> dict[str, Any]:
    label = name.strip()
    if not label:
        raise ValueError("请填写展示名")
    with _lock:
        slots = load_slots(data_root, code_root)
        if any(str(slot.get("name") or "") == label for slot in slots):
            raise ValueError("展示名已存在")
        work = Path(data_root) / "temp" / "voice-clone" / uuid.uuid4().hex[:12]
        work.mkdir(parents=True, exist_ok=True)
        ready = (prepare or prepare_sample)(upload_path, work)
        slot_id = "slot-" + uuid.uuid4().hex[:8]
        if not _SLOT_ID.match(slot_id):
            raise ValueError("插槽编号不合法")
        sample = _store_sample(data_root, slot_id, ready)
        slot = _blank(slot_id, label, sample_kind="upload", sample=sample, packaged="")
        slots.append(slot)
        save_slots(data_root, slots)
        return slot
