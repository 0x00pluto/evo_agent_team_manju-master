"""提示词与音色插槽分开。不打外网。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from datetime import datetime  # noqa: E402

from src.minimax_clone import build_clone_body, compose_voice_id  # noqa: E402
from src.studio.audio_sample import MAX_BYTES, SampleError, assert_limits  # noqa: E402
from src.studio.compile_episode import build_locked  # noqa: E402
from src.studio.jobs import resynth_line, run_pipeline  # noqa: E402
from src.studio.jobs import Job  # noqa: E402
from src.studio.voice_slots import (  # noqa: E402
    bind_speaker,
    classify_account_voice,
    load_slots,
    perform_clone,
    public_slot,
    read_cast,
    save_slots,
    voice_block_reason,
)

SCRIPT = """【钩子】
王师傅：厂房不够用了，产线挤在一起。
李顾问：园区可以一起想办法。

【旁白段】
旁边还有一句没有人报名字的口播。
"""


class SpeakerTests(unittest.TestCase):
    def test_unknown_names_and_narration_stay(self) -> None:
        locked = build_locked(
            SCRIPT,
            [{"index": 0, "mode": "shot"}, {"index": 1, "mode": "voice"}],
        )
        speakers = [line["speaker"] for line in locked["voice_lines"]]
        self.assertEqual(speakers[0], "王师傅")
        self.assertIn("李顾问", speakers)
        self.assertIn("旁白", speakers)
        names = [row["name"] for row in locked["characters"]]
        self.assertIn("王师傅", names)
        self.assertNotIn("旁白", names)

    def test_prompt_step_does_not_call_tts(self) -> None:
        def compile_fn(_script: str, _selections: list) -> dict:
            return {
                "slug": "demo",
                "episode": {"title": "甲", "characters": [], "scenes": [], "shots": []},
                "voiceover": {
                    "lines": [
                        {"speaker": "王师傅", "text": "厂房不够用了，产线挤在一起。", "segment": "shot"},
                        {"speaker": "旁白", "text": "旁边还有一句没有人报名字的口播。", "segment": "vo"},
                    ]
                },
                "summary": {"shots": [], "voice_only": []},
            }

        def generate(_episode: dict, out: Path) -> None:
            out.mkdir(parents=True, exist_ok=True)
            (out / "03-分镜.md").write_text("## V01\n```text\n一句\n```\n", encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = Job(id="job")
            with patch("src.studio.jobs.synthesize_manifest", side_effect=AssertionError("不应配音")):
                run_pipeline(
                    root,
                    job,
                    SCRIPT,
                    [{"index": 0, "mode": "shot"}],
                    compile_fn=compile_fn,
                    generate_fn=generate,
                )
            self.assertEqual(job.status, "done")
            self.assertEqual(job.voice_error, "")
            cast = read_cast(root, job.theme)
            self.assertIsNotNone(cast)
            self.assertEqual([row["speaker"] for row in cast or []], ["王师傅", "旁白"])


class SlotTests(unittest.TestCase):
    def test_defaults_are_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            slots = load_slots(Path(tmp), REPO)
        names = [slot["name"] for slot in slots]
        self.assertEqual(names, ["AI企业主", "女招商主管"])
        self.assertEqual(slots[0]["status"], "not_ready")
        self.assertEqual(slots[0]["account_voice_id"], "")
        self.assertTrue(slots[0]["packaged_voice_id"])
        shown = public_slot(slots[0])
        self.assertEqual(shown["status_label"], "还不能用")
        self.assertNotIn("packaged_voice_id", shown)

    def test_clone_body_omits_packaged_id(self) -> None:
        voice_id = compose_voice_id("Sample", datetime(2026, 10, 11, 23, 5, 1))
        body = build_clone_body(12, voice_id)
        self.assertEqual(body["voice_id"], "Manju-Sample-20261011230501")
        self.assertNotEqual(body["voice_id"], "AiEnterpriseOwner")
        self.assertNotEqual(body["voice_id"], "FemaleZhaoShangLead")
        self.assertEqual(body["need_noise_reduction"], True)
        self.assertEqual(body["need_volume_normalization"], False)

    def test_known_packaged_id_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            load_slots(root, REPO)
            shown = perform_clone(
                root,
                REPO,
                "ai-enterprise-owner",
                known_ids=lambda: {"AiEnterpriseOwner"},
            )
            self.assertEqual(shown["selectable"], True)
            slots = load_slots(root, REPO)
            self.assertEqual(slots[0]["account_voice_id"], "AiEnterpriseOwner")
            self.assertEqual(slots[0]["status"], "ready")

    def test_account_voice_label(self) -> None:
        slots = [{"account_voice_id": "ManjuSample20261011230501", "name": "样品"}]
        self.assertEqual(classify_account_voice("ManjuSample20261011230501", slots), "样品")
        self.assertEqual(classify_account_voice("Dh6IP20260814104340", []), "数字人项目")
        self.assertEqual(classify_account_voice("PengJingIP20260729160021", []), "数字人项目")
        self.assertEqual(classify_account_voice("moss_audio_example", []), "认不出")

    def test_limits_reject_before_clone(self) -> None:
        with self.assertRaises(SampleError):
            assert_limits(size=100, duration=3, has_audio=True)
        with self.assertRaises(SampleError):
            assert_limits(size=100, duration=301, has_audio=True)
        with self.assertRaises(SampleError):
            assert_limits(size=MAX_BYTES + 1, duration=20, has_audio=True)
        with self.assertRaises(SampleError):
            assert_limits(size=100, duration=None, has_audio=False)

    def test_failed_replace_keeps_account_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = root / "new.mp3"
            sample.write_bytes(b"mp3")
            slots = load_slots(root, REPO)
            slots[0]["account_voice_id"] = "Vkeepme01"
            slots[0]["status"] = "ready"
            slots[0]["model"] = "speech-2.8-hd"
            save_slots(root, slots)
            called: list[Path] = []

            def clone_audio(path: Path) -> tuple[str, str]:
                called.append(path)
                raise RuntimeError("克隆失败")

            os.environ["MINIMAX_API_KEY"] = "test-key"
            try:
                with self.assertRaises(RuntimeError):
                    perform_clone(
                        root,
                        REPO,
                        slots[0]["id"],
                        upload_path=sample,
                        clone_audio=clone_audio,
                        prepare=lambda src, _work: src,
                    )
            finally:
                os.environ.pop("MINIMAX_API_KEY", None)
            again = load_slots(root, REPO)
            self.assertEqual(again[0]["account_voice_id"], "Vkeepme01")
            self.assertEqual(again[0]["status"], "ready")
            self.assertIn("克隆失败", again[0]["error"])
            self.assertEqual(len(called), 1)

    def test_missing_key_does_not_clone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slots = load_slots(root, REPO)
            called: list[str] = []
            old = os.environ.pop("MINIMAX_API_KEY", None)
            try:
                with self.assertRaises(RuntimeError) as ctx:
                    perform_clone(
                        root,
                        REPO,
                        slots[0]["id"],
                        clone_audio=lambda _path: called.append("x") or ("Vnewvoice", "speech-2.8-hd"),
                        prepare=lambda src, _work: src,
                    )
            finally:
                if old is not None:
                    os.environ["MINIMAX_API_KEY"] = old
            self.assertIn("密钥", str(ctx.exception))
            self.assertEqual(called, [])
            again = load_slots(root, REPO)
            self.assertEqual(again[0]["account_voice_id"], "")
            self.assertEqual(again[0]["status"], "failed")

    def test_success_stores_only_the_new_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = root / "take.mp3"
            sample.write_bytes(b"mp3")
            slots = load_slots(root, REPO)
            os.environ["MINIMAX_API_KEY"] = "test-key"
            try:
                shown = perform_clone(
                    root,
                    REPO,
                    slots[0]["id"],
                    upload_path=sample,
                    clone_audio=lambda _path: ("Vnewonly1", "speech-2.8-hd"),
                    prepare=lambda src, _work: src,
                )
            finally:
                os.environ.pop("MINIMAX_API_KEY", None)
            self.assertEqual(shown["status"], "ready")
            again = load_slots(root, REPO)
            self.assertEqual(again[0]["account_voice_id"], "Vnewonly1")
            self.assertNotEqual(again[0]["account_voice_id"], again[0]["packaged_voice_id"])


class BindTests(unittest.TestCase):
    def _ready(self, root: Path) -> list[dict]:
        slots = load_slots(root, REPO)
        slots[0]["status"] = "ready"
        slots[0]["account_voice_id"] = "Vready001"
        slots[0]["model"] = "speech-2.8-hd"
        save_slots(root, slots)
        return slots

    def test_shared_slot_unblocks_voice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slots = self._ready(root)
            from src.studio.voice_slots import write_cast

            write_cast(
                root,
                "demo-ep",
                [
                    {"speaker": "王师傅", "text": "甲"},
                    {"speaker": "旁白", "text": "乙"},
                ],
            )
            self.assertIn("王师傅", voice_block_reason(read_cast(root, "demo-ep") or [], slots))
            bind_speaker(root, "demo-ep", "王师傅", slots[0]["id"], slots)
            bind_speaker(root, "demo-ep", "旁白", slots[0]["id"], slots)
            rows = read_cast(root, "demo-ep") or []
            self.assertEqual(rows[0]["slot_id"], rows[1]["slot_id"])
            self.assertEqual(voice_block_reason(rows, load_slots(root, REPO)), "")

    def test_not_ready_slot_cannot_be_chosen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slots = load_slots(root, REPO)
            from src.studio.voice_slots import write_cast

            write_cast(root, "demo-ep", [{"speaker": "王师傅", "text": "甲"}], code_root=REPO)
            with self.assertRaises(ValueError) as ctx:
                bind_speaker(root, "demo-ep", "王师傅", slots[0]["id"], slots)
            self.assertIn("还不能用", str(ctx.exception))

    def test_default_match_and_manual_choice_sticks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slots = self._ready(root)
            from src.studio.voice_slots import apply_cast_defaults, write_cast

            write_cast(
                root,
                "demo-ep",
                [
                    {"speaker": "企业老板", "text": "甲"},
                    {"speaker": "招商运营", "text": "乙"},
                    {"speaker": "王师傅", "text": "丙"},
                ],
                code_root=REPO,
            )
            rows = read_cast(root, "demo-ep") or []
            self.assertEqual(rows[0]["slot_id"], "ai-enterprise-owner")
            self.assertEqual(rows[1]["slot_id"], "")
            self.assertEqual(rows[2]["slot_id"], "")
            slots[1]["status"] = "ready"
            slots[1]["account_voice_id"] = "Vlead0001"
            slots[1]["model"] = "speech-2.8-hd"
            save_slots(root, slots)
            filled = apply_cast_defaults(root, "demo-ep", load_slots(root, REPO)) or []
            self.assertEqual(filled[1]["slot_id"], "female-zhao-shang-lead")
            bind_speaker(root, "demo-ep", "企业老板", "", load_slots(root, REPO))
            again = apply_cast_defaults(root, "demo-ep", load_slots(root, REPO)) or []
            self.assertEqual(again[0]["slot_id"], "")
            self.assertTrue(again[0]["touched"])

    def test_resynth_uses_bound_account_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            theme = "demo-ep"
            facts = root / "temp" / "studio_facts"
            facts.mkdir(parents=True)
            (facts / f"{theme}.json").write_text("{}\n", encoding="utf-8")
            (facts / f"{theme}-voiceover.json").write_text(
                json.dumps({"lines": [{"id": "01", "speaker": "王师傅", "text": "旧"}]}),
                encoding="utf-8",
            )
            slots = self._ready(root)
            from src.studio.voice_slots import write_cast

            write_cast(root, theme, [{"speaker": "王师傅", "text": "旧"}])
            bind_speaker(root, theme, "王师傅", slots[0]["id"], load_slots(root, REPO))
            os.environ["MINIMAX_API_KEY"] = "test-key"
            seen: dict[str, str] = {}

            def fake_manifest(*_args: object, **kwargs: object) -> None:
                voice_of = kwargs["voice_of"]
                voice_id, _model = voice_of({"speaker": "王师傅"})
                seen["voice_id"] = voice_id

            try:
                with patch("src.studio.jobs.synthesize_manifest", side_effect=fake_manifest):
                    resynth_line(root, theme, "01", "新的一句口播", code_root=REPO)
            finally:
                os.environ.pop("MINIMAX_API_KEY", None)
            self.assertEqual(seen["voice_id"], "Vready001")

    def test_history_keeps_written_voice_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            theme = "demo-ep"
            facts = root / "temp" / "studio_facts"
            facts.mkdir(parents=True)
            folder = root / "output" / theme / "voiceover"
            folder.mkdir(parents=True)
            (facts / f"{theme}.json").write_text("{}\n", encoding="utf-8")
            (facts / f"{theme}-voiceover.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "id": "01",
                                "speaker": "企业主",
                                "text": "旧",
                                "voice_slug": "ai-enterprise-owner",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (folder / "manifest-out.json").write_text(
                json.dumps({"lines": [{"id": "01", "voice_id": "Valready", "model": "speech-2.8-hd"}]}),
                encoding="utf-8",
            )
            os.environ["MINIMAX_API_KEY"] = "test-key"
            try:
                with patch("src.studio.jobs.synthesize_manifest") as mocked:
                    resynth_line(root, theme, "01", "新的一句口播", code_root=REPO)
            finally:
                os.environ.pop("MINIMAX_API_KEY", None)
            saved = json.loads((facts / f"{theme}-voiceover.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["lines"][0]["voice_id"], "Valready")
            self.assertIsNone(mocked.call_args.kwargs.get("voice_of"))


if __name__ == "__main__":
    unittest.main()
