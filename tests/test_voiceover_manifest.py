"""voiceover 清单：脚本顺序 id + 引号样本（无网、不调 TTS）。"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HAN_VO = REPO / "assets" / "episodes" / "hanyangzao-hook-cta-voiceover.json"
ID_RE = re.compile(r"^\d{2}$")


class VoiceoverManifestTests(unittest.TestCase):
    def test_hanyangzao_ids_strictly_increasing(self) -> None:
        data = json.loads(HAN_VO.read_text(encoding="utf-8"))
        lines = data["lines"]
        self.assertGreaterEqual(len(lines), 1)
        ids = [line["id"] for line in lines]
        for i, lid in enumerate(ids):
            self.assertRegex(lid, ID_RE, f"id 须为两位数字，禁止 H/M/C 前缀: {lid!r}")
            self.assertEqual(lid, f"{i + 1:02d}", f"lines[{i}] id 须与顺序一致")
        nums = [int(x) for x in ids]
        self.assertEqual(nums, sorted(nums))
        self.assertEqual(nums, list(range(1, len(nums) + 1)))

    def test_hanyangzao_spec_line_keeps_quote_marks(self) -> None:
        data = json.loads(HAN_VO.read_text(encoding="utf-8"))
        spec = next(x for x in data["lines"] if x.get("segment") == "mid-spec")
        text = spec["text"]
        for sample in ('"五分钟"', '"七点二"', '"十五分钟"', '"八百公斤"'):
            self.assertIn(sample, text, f"规格句须保留读法引号: {sample}")


if __name__ == "__main__":
    unittest.main()
