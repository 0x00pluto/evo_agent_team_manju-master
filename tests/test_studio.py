"""操作台：事实校验、提示词切块、本机路径。不打外网。"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from http.client import HTTPConnection
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.studio.bench import load_bench, parse_shots, validate_theme  # noqa: E402
from src.studio.compile_episode import (  # noqa: E402
    build_locked,
    compile_bundle,
    extract_json,
    parse_sections,
    split_sections,
    validate_bundle,
)
from src.generate_episode import render_shot  # noqa: E402
from src.studio.jobs import Job, JobManager, stamp_slug, write_facts  # noqa: E402
from src.studio.server import explicit_feishu_url, serve  # noqa: E402

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
        self.assertEqual(out["voiceover"]["lines"][0]["speaker"], "企业主")
        self.assertEqual(out["voiceover"]["lines"][0]["voice_slug"], "ai-enterprise-owner")
        self.assertEqual(out["voiceover"]["lines"][1]["speaker"], "招商顾问")
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
        self.assertIn("招商顾问", speakers)
        self.assertNotIn("招商人员", speakers)

    def test_model_anchors_split_when_brackets_are_missing(self) -> None:
        def chat(_messages: list) -> str:
            return json.dumps(
                {
                    "sections": [
                        {"title": "钩子", "start": "0-18秒钩子"},
                        {"title": "价值", "start": "18-52秒价值"},
                    ]
                },
                ensure_ascii=False,
            )

        sections = split_sections(PLAIN_BEATS, chat_fn=chat)
        self.assertEqual([row["title"] for row in sections], ["钩子", "价值"])
        self.assertEqual([row["mode"] for row in sections], ["shot", "voice"])
        self.assertTrue(
            any("我这厂房是真不够用了" in item["text"] for item in sections[0]["items"])
        )
        self.assertTrue(any(item["text"].startswith("有！") for item in sections[1]["items"]))

    def test_bad_anchors_keep_local_sections(self) -> None:
        def chat(_messages: list) -> str:
            return json.dumps(
                {
                    "sections": [
                        {"title": "钩子", "start": "这段不在脚本里"},
                        {"title": "价值", "start": "这句也不在"},
                    ]
                },
                ensure_ascii=False,
            )

        script = "【0-18秒·钩子】\n企业主：我这厂房是真不够用了。\n\n18-52秒\n有！园区一次性帮你搞定。\n"
        sections = split_sections(script, chat_fn=chat)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["title"], "0-18秒·钩子")

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
            self.assertIn("飞书文档", page)
            self.assertIn("上传脚本", page)
            self.assertIn("分镜演绎", page)
            self.assertNotIn("写明哪些要出镜", page)
            self.assertIn("在访达中打开", page)
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


if __name__ == "__main__":
    unittest.main()
