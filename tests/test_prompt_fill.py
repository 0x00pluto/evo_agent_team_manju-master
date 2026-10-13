"""env_load / prompt_fill / generate 干跑测试（不打真网）。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(REPO))

from src.env_load import load_dotenv, require_deepseek_api_key
from src.generate_episode import generate_episode
from src.prompt_fill import (
    build_prompt,
    fill,
    load_style_and_duration,
    parse_style_id,
    read_template,
)


class EnvLoadTests(unittest.TestCase):
    def test_missing_key_mentions_example(self) -> None:
        old = os.environ.pop("DEEPSEEK_API_KEY", None)
        try:
            with patch("src.env_load.load_dotenv", return_value=None):
                with self.assertRaises(RuntimeError) as ctx:
                    require_deepseek_api_key()
            msg = str(ctx.exception)
            self.assertIn(".env.example", msg)
            self.assertIn("platform.deepseek.com", msg)
        finally:
            if old is not None:
                os.environ["DEEPSEEK_API_KEY"] = old

    def test_dotenv_does_not_override_process_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "DEEPSEEK_API_KEY=from-file\nFOO_ONLY=1\n", encoding="utf-8"
            )
            os.environ["DEEPSEEK_API_KEY"] = "from-process"
            os.environ.pop("FOO_ONLY", None)
            load_dotenv(env_path)
            self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "from-process")
            self.assertEqual(os.environ.get("FOO_ONLY"), "1")
            os.environ.pop("FOO_ONLY", None)


class PromptFillTests(unittest.TestCase):
    def test_style_injected_not_hardcoded_in_shot_template(self) -> None:
        base = load_style_and_duration()
        self.assertIn("电影级写实", base["style"])
        self.assertEqual(base["style_id"], "cinematic-photoreal-short-drama")
        prompt = build_prompt(
            "shot_libtv.md",
            {
                "shot_id": "V01",
                "duration_hint": "约11秒",
                "shot_type": "近景",
                "camera": "缓推",
                "protagonist": "企业主",
                "action": "待生成",
                "dialogue": "测试台词",
                "sfx": "",
                "lighting": "",
                "scene_ref": "old_site",
                "ref_images": "图1: {{Mixed 1}} 企业主三视图；图2: {{Mixed 2}}",
                "scene_slot": "{{Mixed 2}}",
            },
        )
        self.assertIn("电影级写实", prompt)
        self.assertIn("测试台词", prompt)
        self.assertIn("废除", prompt)
        self.assertIn("先空间", prompt)
        self.assertIn("无路径换阵", prompt)
        self.assertIn("硬切", prompt)
        self.assertIn("竖屏", prompt)
        self.assertIn("缓推", prompt)
        self.assertIn("拉远", prompt)
        self.assertIn("慢摇", prompt)
        self.assertIn("环绕", prompt)
        self.assertIn("不是菜单", prompt)
        self.assertNotIn("甩", prompt)
        # 不钉动作、不锁运镜菜单
        self.assertNotIn("默认不迈步", prompt)
        self.assertNotIn("脚钉死", prompt)
        self.assertNotIn("运镜三选一", prompt)

    def test_camera_catalog_stays_out_of_shot_prompt(self) -> None:
        catalog = read_template("camera_moves.md")
        self.assertIn("升", catalog)
        self.assertIn("跟", catalog)
        self.assertIn("甩", catalog)
        self.assertIn("介绍园区", catalog)
        self.assertNotIn("camera_moves", load_style_and_duration())

    def test_scene_prompt_requires_empty_hero_seats(self) -> None:
        prompt = build_prompt(
            "scene.md",
            {
                "time_of_day": "白天",
                "space": "洽谈区",
                "light": "自然光",
                "props": "资料",
            },
        )
        self.assertIn("主位座椅", prompt)
        self.assertIn("不要坐着或站着可辨认的对谈者或主角", prompt)
        self.assertIn("不要主角入画", prompt)
        self.assertIn("不要把风格里的「过肩 / 肩扛」写成有人肩线入画的机位", prompt)

    def test_compile_draft_uses_hard_cut_and_empty_scene(self) -> None:
        from src.studio.compile_episode import _SYSTEM

        self.assertIn("慢摇给园区", _SYSTEM)
        self.assertIn("不是菜单", _SYSTEM)
        self.assertNotIn("不要写横移", _SYSTEM)
        self.assertIn("主位座椅空着", _SYSTEM)

    def test_missing_placeholder_raises(self) -> None:
        with self.assertRaises(KeyError):
            fill("hello {{name}}", {})

    def test_parse_style_id(self) -> None:
        self.assertEqual(
            parse_style_id("foo\nstyle_id: cinematic-photoreal-short-drama\n"),
            "cinematic-photoreal-short-drama",
        )


class GenerateDryTests(unittest.TestCase):
    def test_generate_with_mock_chat(self) -> None:
        episode = {
            "title": "测试集",
            "characters": [
                {
                    "id": "a",
                    "name": "角色A",
                    "appearance": "短发",
                    "wardrobe": "衬衫",
                    "expression": "沉稳",
                }
            ],
            "scenes": [
                {
                    "id": "s1",
                    "label": "场景1",
                    "time_of_day": "黄昏",
                    "space": "院内",
                    "light": "逆光",
                    "props": "楼群",
                }
            ],
            "shots": [
                {
                    "id": "V01",
                    "duration_hint": "4秒",
                    "shot_type": "近景",
                    "camera": "固定",
                    "protagonist": "角色A",
                    "action": "点头",
                    "dialogue": [{"speaker": "角色A", "text": "你好"}],
                    "sfx": "",
                    "lighting": "",
                    "scene_ref": "s1",
                    "ref_images": "图1",
                }
            ],
        }
        calls: list[str] = []

        def fake_chat(messages, **kwargs):
            calls.append(messages[-1]["content"][:40])
            return f"MOCK_OUTPUT_{len(calls)}"

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            paths = generate_episode(episode, out, chat_fn=fake_chat)
            self.assertTrue((out / "01-角色-a.md").is_file())
            self.assertTrue((out / "02-场景.md").is_file())
            self.assertTrue((out / "03-分镜.md").is_file())
            self.assertGreaterEqual(len(calls), 4)
            self.assertTrue(all(p.exists() for p in paths))


if __name__ == "__main__":
    unittest.main()
