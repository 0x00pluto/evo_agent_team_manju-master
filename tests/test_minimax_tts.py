"""MiniMax 同步合成：不访问网络。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.episode_voiceover import synthesize_manifest
from src.minimax_tts import SYNC_CHAR_LIMIT, synthesize_to_mp3


class MiniMaxTtsTests(unittest.TestCase):
    def test_url_audio_is_downloaded(self) -> None:
        seen = {}

        def post(url, body, headers):
            seen["url"] = url
            seen["body"] = body
            seen["headers"] = headers
            return {
                "base_resp": {"status_code": 0},
                "data": {"audio": "https://cdn.example/a.mp3"},
                "extra_info": {"usage_characters": 4},
            }

        def fetch(url):
            seen["download"] = url
            return b"mp3-bytes"

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "voice" / "01.mp3"
            result = synthesize_to_mp3(
                voice_id="AiEnterpriseOwner",
                text='说"五分钟"',
                out_path=out,
                api_key="test-key",
                post_json=post,
                fetch_bytes=fetch,
            )
            self.assertEqual(out.read_bytes(), b"mp3-bytes")
            self.assertEqual(seen["download"], "https://cdn.example/a.mp3")
            self.assertEqual(seen["url"], "https://api.minimax.io/v1/t2a_v2")
            self.assertEqual(seen["headers"]["Authorization"], "Bearer test-key")
            self.assertEqual(seen["body"]["text"], '说"五分钟"')
            self.assertEqual(seen["body"]["model"], "speech-2.8-hd")
            self.assertEqual(seen["body"]["voice_setting"]["voice_id"], "AiEnterpriseOwner")
            self.assertEqual(seen["body"]["audio_setting"]["format"], "mp3")
            self.assertFalse(seen["body"]["stream"])
            self.assertEqual(result["mode"], "sync")
            self.assertEqual(result["usageCharacters"], 4)

    def test_hex_audio_is_decoded(self) -> None:
        def post(_url, _body, _headers):
            return {"base_resp": {"status_code": 0}, "data": {"audio": "6869"}}

        def fetch(_url):
            raise AssertionError("hex 音频不应再下载")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "01.mp3"
            synthesize_to_mp3(
                voice_id="Voice1",
                text="你好",
                out_path=out,
                model="speech-2.8-hd",
                api_key="test-key",
                post_json=post,
                fetch_bytes=fetch,
            )
            self.assertEqual(out.read_bytes(), b"hi")

    def test_over_sync_limit_does_not_call_api(self) -> None:
        def post(*_args):
            raise AssertionError("超长文本不应请求")

        with self.assertRaises(RuntimeError) as ctx:
            synthesize_to_mp3(
                voice_id="Voice1",
                text="字" * (SYNC_CHAR_LIMIT + 1),
                out_path=Path("/tmp/should-not-write.mp3"),
                api_key="test-key",
                post_json=post,
            )
        self.assertIn("5000", str(ctx.exception))

    def test_dry_run_manifest_has_no_sibling_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voice = root / "assets" / "voices" / "owner"
            voice.mkdir(parents=True)
            (voice / "voice.json").write_text(
                json.dumps({"voice_id": "AiEnterpriseOwner", "model": "speech-2.8-hd"}),
                encoding="utf-8",
            )
            manifest = root / "lines.json"
            spoken = '不到"五分钟"。'
            manifest.write_text(
                json.dumps(
                    {
                        "title": "试",
                        "lines": [
                            {
                                "id": "01",
                                "speaker": "企业主",
                                "text": spoken,
                                "voice_slug": "owner",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            out = root / "output" / "voiceover"
            synthesize_manifest(manifest, out, dry_run=True, repo_root=root)
            txt = (out / "01_owner.txt").read_text(encoding="utf-8")
            self.assertEqual(txt, spoken)
            raw = (out / "manifest-out.json").read_text(encoding="utf-8")
            saved = json.loads(raw)
            draft = json.dumps(saved["lines"][0]["tts"], ensure_ascii=False)
            self.assertNotIn("IP数字人", raw)
            self.assertNotIn("node", draft)
            self.assertNotIn("sibling", draft)
            self.assertTrue(saved["lines"][0]["tts"]["dry_run"])
            self.assertFalse((out / "01_owner.mp3").exists())


if __name__ == "__main__":
    unittest.main()
