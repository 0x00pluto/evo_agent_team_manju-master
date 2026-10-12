"""操作台：事实校验、提示词切块、本机路径。不打外网。"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from datetime import datetime
from http.client import HTTPConnection
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.studio.bench import _fact_paths, load_bench, output_dir, parse_shots, validate_theme  # noqa: E402
from src.studio.compile_episode import (  # noqa: E402
    build_locked,
    compile_bundle,
    extract_json,
    parse_sections,
    split_sections,
    validate_bundle,
)
from src.script_preprocess import preprocess_script  # noqa: E402
from src.generate_episode import render_shot  # noqa: E402
from src.env_load import apply_plugin_settings, data_root, load_dotenv, plugin_root  # noqa: E402
from src.episode_voiceover import load_voice  # noqa: E402
from src.studio.hub_worker import StudioSession  # noqa: E402
from src.studio.jobs import Job, JobManager, stamp_slug, write_facts  # noqa: E402
from src.studio.server import (  # noqa: E402
    download_zip,
    explicit_feishu_url,
    load_script,
    read_voice,
    preview_payload,
    section_choices,
    serve,
)

SCRIPT = """【0-20秒·钩子】

企业老板：入驻产业园以后，除了厂房，园区还能提供什么？

招商运营：园区会陪着企业一路走。

【20-40秒·旁白】

东湖高新集团深耕园区运营三十多年，服务过12000多家科技型企业，企业缺什么，我们帮着补什么。
"""

FOUR = """# 角色说明
企业老板戴眼镜，穿浅蓝衬衫。

【0-20秒·钩子引入】
企业老板：入驻产业园以后，除了厂房，园区还能提供什么？
招商运营：园区会陪着企业一路走。

【20-47秒·价值展示】
东湖高新集团深耕园区运营三十多年，服务过12000多家科技型企业。

【47-57秒·格局升华】
企业老板：原来看园区，不能只看厂房好不好。
招商运营：对。好的园区提供的不只是空间，是陪企业一路成长的资源。

【57-70秒·收尾】
想了解园区能为你的企业做什么？欢迎来实地聊聊。
"""

YANGTZE = """# 【0901修改版】 2.双虚拟人对话口播稿（三大产线卖点版）

**选题：生产型企业选厂房，到底看重什么？**

两个虚拟人，角色：【企业主（老板，情绪急躁）】、【招商人员】；前 0-18 秒在旧厂房做对话钩子。

## **脚本正文**

【**0-18 秒・钩子（拥挤旧厂房内双人对话）**】

企业主（语气烦躁无奈）：我这厂房是真不够用了，产线挤得满满的。

招商人员（沉稳）：这确实是老厂房常见的问题。

**【18-52 秒・价值讲解（画面切换园区素材，旁白讲解）】**

有！这些生产企业的痛点，东湖高新・长江新区智造健康园，一次性帮你搞定。

**【52-62 秒・升华（对话收束）】**

企业主（释然）：这么看，选厂房真不是随便选个壳子。

招商人员：没错，优质园区能让厂房空间得到高效利用。

**【62-75 秒・收尾 CTA】**

企业做生产，找厂房，欢迎来长江新区智造健康园实地考察。

## **口播要点**

| 阶段 | 情绪 |
|-|-|
| 对话钩子 | 冲突写实 |
"""

PLAIN_BEATS = """0-18秒钩子
企业主：我这厂房是真不够用了。
招商人员：这确实是老厂房常见的问题。

18-52秒价值
有！这些生产企业的痛点，园区一次性帮你搞定。
"""


def _preview_script_chat(_messages: list) -> str:
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
                        },
                        {"speaker": "招商运营", "text": "园区会陪着企业一路走。"},
                    ],
                },
                {
                    "title": "20-40秒·旁白",
                    "lines": [
                        {
                            "speaker": "",
                            "text": "东湖高新集团深耕园区运营三十多年，服务过12000多家科技型企业，企业缺什么，我们帮着补什么。",
                        }
                    ],
                },
            ],
        },
        ensure_ascii=False,
    )


# 子进程里换掉预处理入口，避免预览去打外网。
_WORKER_PREVIEW = """
import json
import src.script_preprocess as pre
from src.env_load import data_root, plugin_root
from src.studio.hub_worker import StudioSession, serve_stdio

def fake(_messages):
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
                        },
                        {"speaker": "招商运营", "text": "园区会陪着企业一路走。"},
                    ],
                },
                {
                    "title": "20-40秒·旁白",
                    "lines": [
                        {
                            "speaker": "",
                            "text": "东湖高新集团深耕园区运营三十多年，服务过12000多家科技型企业，企业缺什么，我们帮着补什么。",
                        }
                    ],
                },
            ],
        },
        ensure_ascii=False,
    )

real = pre.preprocess_script

def wrapped(script, chat_fn=None):
    return real(script, chat_fn=fake)

pre.preprocess_script = wrapped
serve_stdio(StudioSession(plugin_root(), data_root=data_root()))
"""


def _bundle() -> dict:
    return {
        "slug": "Demo-Park",
        "episode": {
            "title": "园区服务",
            "characters": [
                {
                    "id": "owner",
                    "name": "企业老板",
                    "appearance": "眼镜",
                    "wardrobe": "浅蓝衬衫",
                    "expression": "操心",
                }
            ],
            "scenes": [
                {
                    "id": "lobby",
                    "label": "服务中心",
                    "time_of_day": "日间",
                    "space": "大堂",
                    "light": "明亮",
                    "props": "导台",
                }
            ],
            "shots": [
                {
                    "id": "V01-hook",
                    "duration_hint": "约8秒",
                    "dialogue": [
                        {
                            "speaker": "企业老板",
                            "text": "入驻产业园以后，除了厂房，园区还能提供什么？",
                        },
                        {"speaker": "招商运营", "text": "园区会陪着企业一路走。"},
                    ],
                }
            ],
        },
        "voiceover": {
            "lines": [
                {
                    "id": "H01",
                    "segment": "hook",
                    "speaker": "企业老板",
                    "text": "入驻产业园以后，除了厂房，园区还能提供什么？",
                },
                {
                    "id": "2",
                    "segment": "hook",
                    "speaker": "招商运营",
                    "text": "园区会陪着企业一路走。",
                },
                {
                    "id": "3",
                    "segment": "mid-spec",
                    "speaker": "招商顾问",
                    "text": '东湖高新集团深耕园区运营三十多年，服务过"一万两千"多家科技型企业，企业缺什么，我们帮着补什么。',
                },
            ]
        },
    }


class CompileTests(unittest.TestCase):
    def test_extract_json_strips_fence(self) -> None:
        data = extract_json('```json\n{"slug":"a-b"}\n```')
        self.assertEqual(data["slug"], "a-b")

    def test_validate_normalizes_speakers_and_ids(self) -> None:
        out = validate_bundle(_bundle(), SCRIPT)
        self.assertEqual(out["slug"], "demo-park")
        self.assertEqual(out["episode"]["style"], "cinematic-photoreal-short-drama")
        ids = [line["id"] for line in out["voiceover"]["lines"]]
        self.assertEqual(ids, ["01", "02", "03"])
        self.assertEqual(out["voiceover"]["lines"][0]["speaker"], "企业老板")
        self.assertNotIn("voice_slug", out["voiceover"]["lines"][0])
        self.assertEqual(out["voiceover"]["lines"][1]["speaker"], "招商运营")
        self.assertEqual(len(out["summary"]["shots"]), 1)
        self.assertEqual(out["summary"]["voice_only"][0]["id"], "03")
        self.assertIn('"一万两千"', out["voiceover"]["lines"][2]["text"])

    def test_rejects_rewritten_dialogue(self) -> None:
        data = _bundle()
        data["episode"]["shots"][0]["dialogue"][0]["text"] = "除了厂房还能提供什么？"
        with self.assertRaises(ValueError):
            validate_bundle(data, SCRIPT)

    def test_rejects_shot_over_twelve_seconds(self) -> None:
        data = _bundle()
        long_line = "园" * 80
        script = SCRIPT + "\n企业老板：" + long_line + "\n"
        data["episode"]["shots"][0]["dialogue"] = [{"speaker": "企业老板", "text": long_line}]
        data["voiceover"]["lines"] = [
            {"speaker": "企业主", "segment": "hook", "text": long_line}
        ]
        with self.assertRaises(ValueError) as ctx:
            validate_bundle(data, script)
        self.assertIn("12 秒", str(ctx.exception))

    def test_rejects_voice_out_of_order(self) -> None:
        data = _bundle()
        data["voiceover"]["lines"][0], data["voiceover"]["lines"][1] = (
            data["voiceover"]["lines"][1],
            data["voiceover"]["lines"][0],
        )
        with self.assertRaises(ValueError):
            validate_bundle(data, SCRIPT)


class SectionTests(unittest.TestCase):
    def test_four_sections_skip_preamble(self) -> None:
        sections = parse_sections(FOUR)
        self.assertEqual(len(sections), 4)
        self.assertEqual(
            [row["mode"] for row in sections],
            ["shot", "voice", "shot", "voice"],
        )
        self.assertEqual(sections[0]["title"], "0-20秒·钩子引入")
        self.assertNotIn("角色说明", sections[0]["title"])

    def test_selection_locks_shot_lines(self) -> None:
        defaults = [
            {"index": row["index"], "mode": row["mode"]} for row in parse_sections(FOUR)
        ]
        locked = build_locked(FOUR, defaults)
        texts = [
            item["text"]
            for shot in locked["shots"]
            for item in shot["dialogue"]
        ]
        self.assertEqual(len(locked["shots"]), 2)
        self.assertIn("入驻产业园以后，除了厂房，园区还能提供什么？", texts)
        self.assertNotIn("东湖高新集团深耕园区运营三十多年，服务过12000多家科技型企业。", texts)
        self.assertTrue(any('"一万两千"' in line["text"] for line in locked["voice_lines"]))

        voice_only = [
            {"index": 0, "mode": "voice"},
            {"index": 1, "mode": "voice"},
            {"index": 2, "mode": "shot"},
            {"index": 3, "mode": "voice"},
        ]
        flipped = build_locked(FOUR, voice_only)
        flipped_texts = [
            item["text"]
            for shot in flipped["shots"]
            for item in shot["dialogue"]
        ]
        self.assertEqual(len(flipped["shots"]), 1)
        self.assertTrue(flipped_texts[0].startswith("原来看园区"))
        self.assertNotIn("入驻产业园以后，除了厂房，园区还能提供什么？", flipped_texts)

    def test_long_section_splits_by_sentence(self) -> None:
        line = "园" * 40 + "。" + "区" * 40 + "。"
        script = f"【钩子】\n企业老板：{line}\n"
        locked = build_locked(script, [{"index": 0, "mode": "shot"}])
        self.assertEqual(len(locked["shots"]), 2)
        self.assertEqual(locked["shots"][0]["dialogue"][0]["text"], "园" * 40 + "。")

    def test_model_cannot_add_voice_only_lines(self) -> None:
        def chat(_messages: list) -> str:
            return json.dumps(
                {
                    "slug": "four-demo",
                    "title": "四段",
                    "characters": [
                        {"name": "企业老板", "appearance": "眼镜", "wardrobe": "浅蓝衬衫"}
                    ],
                    "scenes": [
                        {"id": "scene-1", "space": "大堂"},
                        {"id": "scene-2", "space": "休息区"},
                    ],
                    "shots": [
                        {
                            "id": "V01",
                            "camera": "中景",
                            "dialogue": [
                                {
                                    "speaker": "旁白",
                                    "text": "东湖高新集团深耕园区运营三十多年，服务过12000多家科技型企业。",
                                }
                            ],
                        },
                        {"id": "V02", "camera": "近景"},
                        {
                            "id": "V99",
                            "dialogue": [
                                {"text": "想了解园区能为你的企业做什么？欢迎来实地聊聊。"}
                            ],
                        },
                    ],
                },
                ensure_ascii=False,
            )

        selections = [
            {"index": index, "mode": mode}
            for index, mode in enumerate(["shot", "voice", "shot", "voice"])
        ]
        out = compile_bundle(FOUR, selections, chat_fn=chat)
        texts = [
            item["text"]
            for shot in out["episode"]["shots"]
            for item in shot["dialogue"]
        ]
        self.assertEqual([shot["id"] for shot in out["episode"]["shots"]], ["V01", "V02"])
        self.assertTrue(any(text.startswith("入驻产业园以后") for text in texts))
        self.assertFalse(any("深耕园区" in text for text in texts))
        self.assertFalse(any("实地聊聊" in text for text in texts))
        self.assertTrue(any('"一万两千"' in line["text"] for line in out["voiceover"]["lines"]))
        refs = out["episode"]["shots"][0]["ref_images"]
        self.assertIn("图1企业老板三视图", refs)
        self.assertIn("图2招商运营三视图", refs)
        self.assertIn("场景贴图", refs)
        self.assertIn("可选面部特写", refs)
        self.assertNotIn("无", refs)

    def test_bold_wrapped_headings_split_four_ways(self) -> None:
        sections = parse_sections(YANGTZE)
        self.assertEqual(
            [row["title"] for row in sections],
            [
                "0-18 秒・钩子（拥挤旧厂房内双人对话）",
                "18-52 秒・价值讲解（画面切换园区素材，旁白讲解）",
                "52-62 秒・升华（对话收束）",
                "62-75 秒・收尾 CTA",
            ],
        )
        self.assertEqual(
            [row["mode"] for row in sections],
            ["shot", "voice", "shot", "voice"],
        )
        blob = "\n".join(
            item["text"] for row in sections for item in row["items"]
        )
        self.assertNotIn("口播要点", blob)
        self.assertNotIn("冲突写实", blob)
        self.assertNotIn("0901修改版", blob)
        locked = build_locked(
            YANGTZE,
            [{"index": row["index"], "mode": row["mode"]} for row in sections],
        )
        speakers = [line["speaker"] for line in locked["voice_lines"]]
        self.assertIn("企业主", speakers)
        self.assertIn("招商人员", speakers)
        self.assertIn("旁白", speakers)
        self.assertNotIn("招商顾问", speakers)

    def test_image_markdown_is_not_a_speaker(self) -> None:
        script = FOUR + "\n![图片说明很长](https://feishu.cn/file/abc)\n"
        seen = {"n": 0, "user": ""}

        def chat(messages: list) -> str:
            seen["n"] += 1
            seen["user"] = messages[1]["content"]
            return json.dumps(
                {
                    "preamble": "企业老板戴眼镜，穿浅蓝衬衫。",
                    "sections": [
                        {
                            "title": "0-20秒·钩子引入",
                            "lines": [
                                {
                                    "speaker": "企业老板",
                                    "text": "入驻产业园以后，除了厂房，园区还能提供什么？",
                                },
                                {"speaker": "招商运营", "text": "园区会陪着企业一路走。"},
                            ],
                        },
                        {
                            "title": "20-47秒·价值展示",
                            "lines": [
                                {
                                    "speaker": "",
                                    "text": "东湖高新集团深耕园区运营三十多年，服务过12000多家科技型企业。",
                                }
                            ],
                        },
                        {
                            "title": "47-57秒·格局升华",
                            "lines": [
                                {"speaker": "企业老板", "text": "原来看园区，不能只看厂房好不好。"},
                                {
                                    "speaker": "招商运营",
                                    "text": "对。好的园区提供的不只是空间，是陪企业一路成长的资源。",
                                },
                            ],
                        },
                        {
                            "title": "57-70秒·收尾",
                            "lines": [
                                {
                                    "speaker": "",
                                    "text": "想了解园区能为你的企业做什么？欢迎来实地聊聊。",
                                }
                            ],
                        },
                    ],
                },
                ensure_ascii=False,
            )

        canonical = preprocess_script(script, chat_fn=chat)
        self.assertEqual(seen["n"], 1)
        self.assertNotIn("![", seen["user"])
        self.assertNotIn("![", canonical)
        sections = parse_sections(canonical)
        self.assertEqual(len(sections), 4)
        self.assertEqual(sections[-1]["mode"], "voice")
        texts = [item["text"] for row in sections for item in row["items"]]
        self.assertFalse(any("图片说明" in text or "https" in text for text in texts))
        locked = build_locked(
            canonical,
            [
                {
                    "index": row["index"],
                    "mode": row["mode"],
                    "title": row["title"],
                    "start": row["start"],
                }
                for row in sections
            ],
        )
        self.assertTrue(locked["voice_lines"])

    def test_model_standardizes_when_brackets_are_missing(self) -> None:
        def chat(_messages: list) -> str:
            return json.dumps(
                {
                    "preamble": "",
                    "sections": [
                        {
                            "title": "钩子",
                            "lines": [
                                {"speaker": "企业主", "text": "我这厂房是真不够用了。"},
                                {"speaker": "招商人员", "text": "这确实是老厂房常见的问题。"},
                            ],
                        },
                        {
                            "title": "价值",
                            "lines": [
                                {
                                    "speaker": "",
                                    "text": "有！这些生产企业的痛点，园区一次性帮你搞定。",
                                }
                            ],
                        },
                    ],
                },
                ensure_ascii=False,
            )

        sections = split_sections(PLAIN_BEATS, split_with="model", chat_fn=chat)
        self.assertEqual([row["title"] for row in sections], ["钩子", "价值"])
        self.assertEqual([row["mode"] for row in sections], ["shot", "voice"])
        self.assertTrue(
            any("我这厂房是真不够用了" in item["text"] for item in sections[0]["items"])
        )
        self.assertTrue(any(item["text"].startswith("有！") for item in sections[1]["items"]))

    def test_rewritten_lines_are_rejected(self) -> None:
        def chat(_messages: list) -> str:
            return json.dumps(
                {
                    "sections": [
                        {
                            "title": "钩子",
                            "lines": [{"speaker": "企业主", "text": "这段不在脚本里"}],
                        }
                    ]
                },
                ensure_ascii=False,
            )

        with self.assertRaises(ValueError) as ctx:
            split_sections(PLAIN_BEATS, split_with="model", chat_fn=chat)
        self.assertIn("没能把脚本整理成分段", str(ctx.exception))

    def test_retries_once_when_the_first_pass_rewrites(self) -> None:
        calls = {"n": 0}

        def chat(_messages: list) -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps(
                    {
                        "sections": [
                            {
                                "title": "钩子",
                                "lines": [{"speaker": "企业主", "text": "改写了"}],
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "preamble": "两个虚拟人。",
                    "sections": [
                        {
                            "title": "钩子",
                            "lines": [
                                {"speaker": "企业主（语气烦躁）", "text": "我这厂房是真不够用了。"},
                                {"speaker": "招商人员", "text": "这确实是老厂房常见的问题。"},
                            ],
                        },
                        {
                            "title": "价值",
                            "lines": [
                                {
                                    "speaker": "",
                                    "text": "有！这些生产企业的痛点，园区一次性帮你搞定。",
                                }
                            ],
                        },
                    ],
                },
                ensure_ascii=False,
            )

        payload = preview_payload(PLAIN_BEATS, split_with="model", chat_fn=chat)
        self.assertEqual(calls["n"], 2)
        self.assertEqual([row["title"] for row in payload["sections"]], ["钩子", "价值"])
        self.assertIn("【钩子】", payload["script_text"])
        self.assertIn("企业主：我这厂房是真不够用了。", payload["script_text"])
        self.assertNotIn("改写了", payload["script_text"])

    def test_url_is_not_scraped_from_prose(self) -> None:
        prose = "你看一下该如何搞 https://fcnegd976pzo.feishu.cn/wiki/NWvKwCfy8ihL2ZkVCWScSrOznum"
        self.assertEqual(explicit_feishu_url({"instruction": prose}), "")
        self.assertEqual(explicit_feishu_url({"feishu_url": prose}), "")
        self.assertEqual(
            explicit_feishu_url(
                {"feishu_url": "https://fcnegd976pzo.feishu.cn/wiki/NWvKwCfy8ihL2ZkVCWScSrOznum"}
            ),
            "https://fcnegd976pzo.feishu.cn/wiki/NWvKwCfy8ihL2ZkVCWScSrOznum",
        )


class BenchTests(unittest.TestCase):
    def test_theme_rejects_traversal(self) -> None:
        with self.assertRaises(ValueError):
            validate_theme("../.env")

    def test_guanggu_prompts_are_copyable(self) -> None:
        out = REPO / "output" / "guanggu-bio-lifecycle" / "03-分镜.md"
        if not out.is_file():
            self.skipTest("本机还没有光谷生物城产物")
        bench = load_bench(REPO, "guanggu-bio-lifecycle")
        self.assertGreaterEqual(len(bench["characters"]), 2)
        self.assertIn("电影级", bench["characters"][0]["text"])
        self.assertGreaterEqual(len(bench["scenes"]), 2)
        shots = parse_shots(out)
        self.assertGreaterEqual(len(shots), 3)
        self.assertIn("入驻产业园以后", shots[0]["text"])
        self.assertTrue(any(row["id"] == "05" for row in bench["voice"]))


class JobTests(unittest.TestCase):
    def test_one_job_at_a_time(self) -> None:
        gate = threading.Event()

        def pipeline(root: Path, job: Job, script: str, selections: list) -> None:
            gate.wait(2)
            job.theme = "demo-ep"
            job.status = "done"

        manager = JobManager(REPO, pipeline=pipeline)
        script = "【钩子】\n企业老板：我们缺的从来不是空间，是资源。\n"
        selections = [{"index": 0, "mode": "shot"}]
        first = manager.create(script, selections)
        with self.assertRaises(RuntimeError):
            manager.create(script, selections)
        gate.set()
        for _ in range(40):
            if manager.get(first.id).status == "done":
                break
            time.sleep(0.05)
        self.assertEqual(manager.get(first.id).status, "done")

    def test_stamp_slug_uses_clock_then_name(self) -> None:
        when = datetime(2026, 9, 29, 9, 58, 0)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stamped = stamp_slug("four-demo", root, now=when)
            self.assertEqual(stamped, "20260929-095800-four-demo")
            validate_theme(stamped)
            long_name = stamp_slug("n" * 64, root, now=when)
            self.assertTrue(long_name.startswith("20260929-095800-"))
            self.assertLessEqual(len(long_name), 64)
            (root / "output" / stamped).mkdir(parents=True)
            again = stamp_slug("four-demo", root, now=when)
            self.assertEqual(again, "20260929-095800-four-demo-2")

    def test_facts_go_to_temp(self) -> None:
        bundle = {
            "slug": "demo-ep",
            "episode": {"title": "甲"},
            "voiceover": {"lines": []},
            "summary": {"shots": [], "voice_only": []},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_facts(root, bundle, [])
            self.assertTrue((root / "temp" / "studio_facts" / "demo-ep.json").is_file())
            self.assertTrue((root / "temp" / "studio_facts" / "demo-ep-voiceover.json").is_file())
            self.assertFalse((root / "assets" / "episodes" / "demo-ep.json").exists())

    def test_only_resynth_keeps_other_manifest_lines(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "synthesize_episode_voiceover",
            REPO / "scripts" / "synthesize_episode_voiceover.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        merged = module.merge_result_lines(
            [{"id": "01", "text": "甲"}, {"id": "08", "text": "旧"}],
            [{"id": "08", "text": "新"}],
        )
        self.assertEqual([row["id"] for row in merged], ["01", "08"])
        self.assertEqual(merged[1]["text"], "新")
        self.assertEqual(merged[0]["text"], "甲")

    def test_shot_prompt_keeps_ref_line(self) -> None:
        def chat(_messages: list) -> str:
            return "```text\n【V01】\n参考图：无\n景别：中景\n```"

        text = render_shot(
            {
                "id": "V01",
                "dialogue": [{"speaker": "企业主", "text": "一句"}],
                "ref_images": "图1企业主三视图；图2旧厂房场景贴图；可选面部特写",
            },
            chat_fn=chat,
        )
        self.assertIn("参考图：图1企业主三视图；图2旧厂房场景贴图；可选面部特写", text)
        self.assertNotIn("参考图：无", text)


class ServerTests(unittest.TestCase):
    def test_index_and_blocks_escape(self) -> None:
        httpd = serve(REPO, host="127.0.0.1", port=0)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/")
            page = conn.getresponse().read().decode("utf-8")
            self.assertIn("漫剧操作台", page)
            nav = page.split("<main", 1)[0]
            self.assertIn('<button type="button" class="font-semibold tracking-wide" @click="newScript()">AI漫剧大师</button>', nav)
            intake = page.split("screen === 'prompt'", 1)[0].split("screen === 'intake'", 1)[1]
            prompt = page.split("screen === 'prompt'", 1)[1].split("screen === 'history'", 1)[0]
            self.assertIn("加载脚本", intake)
            self.assertIn("飞书链接", intake)
            self.assertIn("上传文件", intake)
            self.assertIn("粘贴正文", intake)
            self.assertIn("下一步", intake)
            self.assertNotIn("生成提示词", intake)
            self.assertNotIn("MiniMax", intake)
            self.assertIn("生成提示词", prompt)
            self.assertIn("MiniMax", prompt)
            self.assertIn("生成分镜", page)
            self.assertIn("按标题分段", page)
            self.assertIn("让模型分段", page)
            self.assertIn("pulse-flow", page)
            self.assertNotIn("写明哪些要出镜", page)
            self.assertIn("打开所在文件夹", page)
            self.assertIn("重新配音", page)
            self.assertIn("下载全部", page)
            self.assertIn("manjuStudioService", page)
            self.assertIn("window.dex.call", page)
            self.assertIn("window.hub.call", page)
            body = json.dumps(
                {
                    "instruction": "你看一下 https://fcnegd976pzo.feishu.cn/wiki/NWvKwCfy8ihL2ZkVCWScSrOznum",
                    "sections": [{"index": 0, "mode": "shot"}],
                }
            ).encode("utf-8")
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("POST", "/api/jobs", body=body, headers={"Content-Type": "application/json"})
            missed = conn.getresponse()
            missed_body = missed.read().decode("utf-8")
            self.assertEqual(missed.status, 400)
            self.assertIn("请上传脚本", missed_body)
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/media/../.env")
            res = conn.getresponse()
            self.assertEqual(res.status, 400)
            res.read()
        finally:
            httpd.shutdown()


class HubWorkerTests(unittest.TestCase):
    def test_script_text_previews_and_rejects_a_second_source(self) -> None:
        text = load_script(REPO, {"script_text": SCRIPT, "filename": "demo.md"})
        rows = section_choices(text, chat_fn=_preview_script_chat)
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[0]["mode"], "shot")
        with self.assertRaises(ValueError):
            load_script(
                REPO,
                {
                    "script_text": SCRIPT,
                    "feishu_url": "https://example.feishu.cn/wiki/Abcd1234",
                },
            )
        with self.assertRaises(ValueError):
            load_script(REPO, {"script_text": SCRIPT, "filename": "notes.pdf"})

    def test_voice_bytes_roundtrip_as_plain_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "output" / "demo-ep" / "voiceover"
            folder.mkdir(parents=True)
            (folder / "01_owner.mp3").write_bytes(b"ID3fake")
            (folder / "02_advisor.mp3").write_bytes(b"ID3more")
            media = read_voice(root, "demo-ep", "01_owner.mp3")
            self.assertEqual(base64.b64decode(media["base64"]), b"ID3fake")
            self.assertEqual(media["mime"], "audio/mpeg")
            packed = download_zip(root, "demo-ep")
            self.assertEqual(packed["filename"], "demo-ep-voiceover.zip")
            with zipfile.ZipFile(BytesIO(base64.b64decode(packed["base64"]))) as zf:
                self.assertEqual(zf.namelist(), ["01_owner.mp3", "02_advisor.mp3"])
            with self.assertRaises(ValueError):
                read_voice(root, "demo-ep", "../01_owner.mp3")

    def test_create_job_returns_before_pipeline_finishes(self) -> None:
        gate = threading.Event()

        def pipeline(root: Path, job: Job, script: str, selections: list) -> None:
            gate.wait(2)
            job.theme = "demo-ep"
            job.status = "done"

        script = "【钩子】\n企业老板：我们缺的从来不是空间，是资源。\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = StudioSession(root, JobManager(root, pipeline=pipeline))
            started = time.monotonic()
            created = session.dispatch(
                "createJob",
                {
                    "script_text": script,
                    "filename": "hook.md",
                    "sections": [{"index": 0, "mode": "shot"}],
                },
            )
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertEqual(created["status"], "queued")
            followed = session.dispatch("getJob", {"id": created["id"]})
            self.assertEqual(followed["id"], created["id"])
            self.assertNotEqual(followed["status"], "done")
            gate.set()
            for _ in range(40):
                if session.dispatch("getJob", {"id": created["id"]})["status"] == "done":
                    break
                time.sleep(0.05)
            self.assertEqual(session.dispatch("getJob", {"id": created["id"]})["status"], "done")

    def test_worker_answers_one_json_line(self) -> None:
        proc = subprocess.Popen(
            [sys.executable, "-c", _WORKER_PREVIEW],
            cwd=REPO,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        request = json.dumps(
            {
                "id": "1",
                "method": "preview",
                "params": {"script_text": SCRIPT, "filename": "a.md"},
            },
            ensure_ascii=False,
        )
        try:
            out, err = proc.communicate(request + "\n", timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise
        self.assertEqual(proc.returncode, 0, err)
        lines = [line for line in out.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, out)
        message = json.loads(lines[0])
        self.assertEqual(message["id"], "1")
        self.assertTrue(message["ok"], message)
        self.assertGreaterEqual(len(message["result"]["sections"]), 2)
        self.assertIn("【0-20秒·钩子】", message["result"]["script_text"])

    def test_plugin_root_reads_env_file_from_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("MANJU_TEST_ONLY=from-file\n", encoding="utf-8")
            (root / "assets" / "voices" / "demo" ).mkdir(parents=True)
            (root / "assets" / "voices" / "demo" / "voice.json").write_text(
                json.dumps({"voice_id": "DemoVoice"}),
                encoding="utf-8",
            )
            old_root = os.environ.get("MANJU_ROOT")
            old_key = os.environ.pop("MANJU_TEST_ONLY", None)
            os.environ["MANJU_ROOT"] = str(root)
            try:
                self.assertEqual(plugin_root(), root.resolve())
                self.assertEqual(load_dotenv(), (root / ".env").resolve())
                self.assertEqual(os.environ.get("MANJU_TEST_ONLY"), "from-file")
                self.assertEqual(load_voice("demo")["voice_id"], "DemoVoice")
            finally:
                if old_root is None:
                    os.environ.pop("MANJU_ROOT", None)
                else:
                    os.environ["MANJU_ROOT"] = old_root
                os.environ.pop("MANJU_TEST_ONLY", None)
                if old_key is not None:
                    os.environ["MANJU_TEST_ONLY"] = old_key

    def test_resynth_calls_voiceover_in_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            facts = root / "temp" / "studio_facts"
            facts.mkdir(parents=True)
            theme = "demo-ep"
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
            old = os.environ.get("MINIMAX_API_KEY")
            os.environ["MINIMAX_API_KEY"] = "test-key"
            try:
                with patch("src.studio.jobs.synthesize_manifest") as mocked:
                    from src.studio.jobs import resynth_line

                    resynth_line(root, theme, "01", "新的一句口播")
                mocked.assert_called_once()
                kwargs = mocked.call_args.kwargs
                self.assertEqual(kwargs["only"], ["01"])
                self.assertEqual(kwargs["repo_root"], root)
            finally:
                if old is None:
                    os.environ.pop("MINIMAX_API_KEY", None)
                else:
                    os.environ["MINIMAX_API_KEY"] = old

    def test_request_settings_are_not_replaced_by_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("DEEPSEEK_API_KEY=from-file\n", encoding="utf-8")
            old_root = os.environ.get("MANJU_ROOT")
            old_key = os.environ.get("DEEPSEEK_API_KEY")
            os.environ["MANJU_ROOT"] = str(root)
            os.environ["DEEPSEEK_API_KEY"] = "old"
            try:
                apply_plugin_settings(
                    {"DEEPSEEK_API_KEY": "from-settings", "NOT_A_SETTING": "nope"}
                )
                self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "from-settings")
                self.assertNotIn("NOT_A_SETTING", os.environ)
                load_dotenv()
                self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "from-settings")
            finally:
                if old_root is None:
                    os.environ.pop("MANJU_ROOT", None)
                else:
                    os.environ["MANJU_ROOT"] = old_root
                if old_key is None:
                    os.environ.pop("DEEPSEEK_API_KEY", None)
                else:
                    os.environ["DEEPSEEK_API_KEY"] = old_key

    def test_installed_facts_stay_out_of_the_code_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            code = base / "installed"
            data = base / "plugin-data"
            theme = "sample-ep"
            assets = code / "assets" / "episodes"
            assets.mkdir(parents=True)
            (assets / f"{theme}.json").write_text("{}\n", encoding="utf-8")
            (assets / f"{theme}-voiceover.json").write_text("{}\n", encoding="utf-8")
            episode, voice = _fact_paths(data, theme, code_root=code)
            self.assertEqual(episode, assets / f"{theme}.json")
            self.assertEqual(voice, assets / f"{theme}-voiceover.json")
            facts = data / "temp" / "studio_facts"
            facts.mkdir(parents=True)
            (facts / f"{theme}.json").write_text('{"title": "new"}\n', encoding="utf-8")
            (facts / f"{theme}-voiceover.json").write_text("{}\n", encoding="utf-8")
            episode, _voice = _fact_paths(data, theme, code_root=code)
            self.assertEqual(episode, facts / f"{theme}.json")
            written = write_facts(
                data,
                {
                    "slug": "demo-ep",
                    "episode": {"title": "甲"},
                    "voiceover": {"lines": []},
                    "summary": {"shots": [], "voice_only": []},
                },
                [],
            )
            self.assertEqual(written, data / "output" / "demo-ep")
            self.assertEqual(output_dir(data, "demo-ep"), (data / "output" / "demo-ep").resolve())
            self.assertFalse((code / "output").exists())
            self.assertFalse((code / "temp").exists())
            old = os.environ.get("MANJU_DATA_ROOT")
            os.environ["MANJU_DATA_ROOT"] = str(data)
            try:
                self.assertEqual(data_root(), data.resolve())
            finally:
                if old is None:
                    os.environ.pop("MANJU_DATA_ROOT", None)
                else:
                    os.environ["MANJU_DATA_ROOT"] = old

    def test_resolve_worker_uses_host_python(self) -> None:
        proc = subprocess.run(
            ["node", "-e", NODE_RESOLVE],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)


NODE_RESOLVE = r"""
const path = require("path");
const fs = require("fs");
const os = require("os");
const { resolveWorker, workerEnv, prepareDataRoot } = require("./index.js");
const ready = resolveWorker({ python: "/opt/venv/bin/python" });
if (ready.command !== "/opt/venv/bin/python" || ready.args.join(" ") !== "-m src.studio.hub_worker") {
  throw new Error("host python should run the module: " + JSON.stringify(ready));
}
const missing = resolveWorker(null);
if (!missing.error || missing.error.indexOf("运行环境还没准备好") < 0) {
  throw new Error("missing runtime should explain itself: " + JSON.stringify(missing));
}
const empty = resolveWorker({});
if (!empty.error || empty.error.indexOf("运行环境还没准备好") < 0) {
  throw new Error("empty runtime should explain itself: " + JSON.stringify(empty));
}
const merged = workerEnv(
  { DEEPSEEK_API_KEY: "", PATH: "/usr/bin" },
  { DEEPSEEK_API_KEY: "from-settings" },
  "/plugin"
);
if (merged.DEEPSEEK_API_KEY !== "from-settings") {
  throw new Error("settings should replace an empty key");
}
if (merged.MANJU_ROOT !== "/plugin" || merged.PYTHONUNBUFFERED !== "1") {
  throw new Error("worker env should keep MANJU_ROOT");
}
if (merged.MANJU_DATA_ROOT !== "/plugin") {
  throw new Error("data root should follow the code root until set");
}
const split = workerEnv({}, {}, "/code", "/data");
if (split.MANJU_ROOT !== "/code" || split.MANJU_DATA_ROOT !== "/data") {
  throw new Error("data root should be passed separately: " + JSON.stringify(split));
}
if (merged.PATH !== "/usr/bin") {
  throw new Error("unrelated env should stay");
}
const data = fs.mkdtempSync(path.join(os.tmpdir(), "manju-data-"));
const fromDirs = prepareDataRoot({ data: data }, "/unused");
if (fromDirs !== data) {
  throw new Error("data root should come from dirs.data: " + fromDirs);
}
if (!fs.existsSync(path.join(data, "temp")) || !fs.existsSync(path.join(data, "output"))) {
  throw new Error("data root should contain temp and output");
}
const repo = fs.mkdtempSync(path.join(os.tmpdir(), "manju-repo-"));
const fallback = prepareDataRoot(null, repo);
if (fallback !== repo) {
  throw new Error("missing dirs should use the fallback: " + fallback);
}
if (!fs.existsSync(path.join(repo, "temp")) || !fs.existsSync(path.join(repo, "output"))) {
  throw new Error("fallback data root should contain temp and output");
}
"""


if __name__ == "__main__":
    unittest.main()
