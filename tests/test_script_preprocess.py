"""脚本预处理：坏标题仍单独成段，单测不打外网。"""

from __future__ import annotations

import json
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.prompt_fill import read_template  # noqa: E402
from src.script_preprocess import load_prompt  # noqa: E402
from src.studio.compile_episode import parse_sections, prepare_script  # noqa: E402

BROKEN_CTA = """【0-20秒·钩子引入】
企业老板：入驻产业园以后，除了厂房，园区还能提供什么？

【47-57秒·格局升华】
企业老板：原来看园区，不能只看厂房好不好。

【57-70秒·收尾CTA]--
选址东湖高新区，欢迎到访光谷生物医药科创中心。
"""

WELL_FORMED = """【0-20秒·钩子】
企业老板：入驻产业园以后，除了厂房，园区还能提供什么？

【20-40秒·旁白】
东湖高新集团深耕园区运营三十多年。
"""


def _standard_reply() -> str:
    return json.dumps(
        {
            "preamble": "",
            "sections": [
                {
                    "title": "0-20秒·钩子引入",
                    "lines": [
                        {
                            "speaker": "企业老板",
                            "text": "入驻产业园以后，除了厂房，园区还能提供什么？",
                        }
                    ],
                },
                {
                    "title": "47-57秒·格局升华",
                    "lines": [
                        {"speaker": "企业老板", "text": "原来看园区，不能只看厂房好不好。"}
                    ],
                },
                {
                    "title": "57-70秒·收尾CTA",
                    "lines": [
                        {
                            "speaker": "",
                            "text": "选址东湖高新区，欢迎到访光谷生物医药科创中心。",
                        }
                    ],
                },
            ],
        },
        ensure_ascii=False,
    )


class PreprocessTests(unittest.TestCase):
    def test_prompt_lives_in_its_own_template(self) -> None:
        text = read_template("script_normalize.md")
        self.assertIn("【57-70秒·收尾CTA]--", text)
        self.assertEqual(load_prompt(), text.strip())

    def test_broken_cta_heading_stays_its_own_section(self) -> None:
        def chat(messages: list) -> str:
            self.assertEqual(messages[0]["content"], load_prompt())
            self.assertIn("【57-70秒·收尾CTA]--", messages[1]["content"])
            return _standard_reply()

        canonical = prepare_script(BROKEN_CTA, split_with="model", chat_fn=chat)[0]
        sections = parse_sections(canonical)
        self.assertEqual(
            [row["title"] for row in sections],
            ["0-20秒·钩子引入", "47-57秒·格局升华", "57-70秒·收尾CTA"],
        )
        self.assertEqual(sections[-1]["mode"], "voice")
        self.assertTrue(any("选址东湖高新区" in item["text"] for item in sections[-1]["items"]))
        self.assertFalse(any("选址东湖高新区" in item["text"] for item in sections[-2]["items"]))

    def test_program_path_skips_the_model(self) -> None:
        def chat(_messages: list) -> str:
            raise AssertionError("程序切段不应调用模型")

        canonical, sections = prepare_script(WELL_FORMED, chat_fn=chat)
        self.assertEqual([row["title"] for row in sections], ["0-20秒·钩子", "20-40秒·旁白"])
        self.assertIn("【0-20秒·钩子】", canonical)

    def test_program_path_drops_image_lines(self) -> None:
        script = WELL_FORMED + "\n![图片说明很长](https://feishu.cn/file/abc)\n"

        def chat(_messages: list) -> str:
            raise AssertionError("程序切段不应调用模型")

        canonical, sections = prepare_script(script, chat_fn=chat)
        self.assertEqual(len(sections), 2)
        self.assertNotIn("![", canonical)
        texts = [item["text"] for row in sections for item in row["items"]]
        self.assertFalse(any("https" in text for text in texts))

    def test_program_path_asks_to_switch_when_brackets_are_missing(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            prepare_script("企业老板：这句没有标题。\n招商运营：另一句也没有。\n")
        self.assertIn("大模型", str(ctx.exception))

    def test_model_path_still_calls_the_model(self) -> None:
        calls = {"n": 0}

        def chat(_messages: list) -> str:
            calls["n"] += 1
            return json.dumps(
                {
                    "preamble": "",
                    "sections": [
                        {
                            "title": "0-20秒·钩子",
                            "lines": [
                                {
                                    "speaker": "企业老板",
                                    "text": "入驻产业园以后，除了厂房，园区还能提供什么？",
                                }
                            ],
                        },
                        {
                            "title": "20-40秒·旁白",
                            "lines": [
                                {"speaker": "", "text": "东湖高新集团深耕园区运营三十多年。"}
                            ],
                        },
                    ],
                },
                ensure_ascii=False,
            )

        sections = prepare_script(WELL_FORMED, split_with="model", chat_fn=chat)[1]
        self.assertEqual(calls["n"], 1)
        self.assertEqual([row["title"] for row in sections], ["0-20秒·钩子", "20-40秒·旁白"])

    def test_model_path_keeps_fail_and_inner_reason(self) -> None:
        def chat(_messages: list) -> str:
            return "这不是 JSON"

        with patch("src.script_preprocess.sys.stderr", StringIO()):
            with self.assertRaises(ValueError) as ctx:
                prepare_script(WELL_FORMED, split_with="model", chat_fn=chat)
        msg = str(ctx.exception)
        self.assertIn("没能把脚本整理成分段", msg)
        self.assertIn("模型没有返回 JSON", msg)

    def test_broken_json_keeps_parser_and_model_text(self) -> None:
        raw = '{"text": "他说"你好""}'

        def chat(_messages: list) -> str:
            return raw

        stderr = StringIO()
        with patch("src.script_preprocess.sys.stderr", stderr):
            with self.assertRaises(ValueError) as ctx:
                prepare_script(WELL_FORMED, split_with="model", chat_fn=chat)
        msg = str(ctx.exception)
        self.assertIn("没能把脚本整理成分段", msg)
        self.assertIn("返回的内容不是合法 JSON", msg)
        self.assertIn("Expecting", msg)
        self.assertIn("他说", msg)
        self.assertIn(raw, stderr.getvalue())

    def test_retries_when_first_json_is_broken(self) -> None:
        calls = {"n": 0}

        def chat(messages: list) -> str:
            calls["n"] += 1
            self.assertNotIn("上次输出", messages[1]["content"])
            self.assertIn("【0-20秒·钩子】", messages[1]["content"])
            if calls["n"] == 1:
                return '{"text": "他说"你好""}'
            return json.dumps(
                {
                    "preamble": "",
                    "sections": [
                        {
                            "title": "0-20秒·钩子",
                            "lines": [
                                {
                                    "speaker": "企业老板",
                                    "text": "入驻产业园以后，除了厂房，园区还能提供什么？",
                                }
                            ],
                        },
                        {
                            "title": "20-40秒·旁白",
                            "lines": [
                                {"speaker": "", "text": "东湖高新集团深耕园区运营三十多年。"}
                            ],
                        },
                    ],
                },
                ensure_ascii=False,
            )

        with patch("src.script_preprocess.sys.stderr", StringIO()):
            sections = prepare_script(WELL_FORMED, split_with="model", chat_fn=chat)[1]
        self.assertEqual(calls["n"], 2)
        self.assertEqual([row["title"] for row in sections], ["0-20秒·钩子", "20-40秒·旁白"])
