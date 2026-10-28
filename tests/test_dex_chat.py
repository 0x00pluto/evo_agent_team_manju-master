"""dex_chat：模型选择、请求体与缺 Key。不打网关。"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(REPO))

from src.dex_chat import chat, pick_chat_model
from src.env_load import require_dex_buddy_api_key


class FakeCompletions:
    def __init__(self, capture: list, response: dict | None = None) -> None:
        self.capture = capture
        self.response = response or {"choices": [{"message": {"content": "ok"}}]}

    def create(self, body, options=None):
        self.capture.append({"body": body, "options": options})
        return self.response


class FakeModels:
    def __init__(self, listed, capture: list, response: dict | None = None) -> None:
        self._listed = listed
        self.chat = type("Chat", (), {"completions": FakeCompletions(capture, response)})()

    def list(self):
        return self._listed


class PickChatModelTests(unittest.TestCase):
    def test_empty_catalog_falls_back(self) -> None:
        self.assertEqual(pick_chat_model({"data": []}), "dexbuddy-chat")
        self.assertEqual(pick_chat_model({}), "dexbuddy-chat")
        self.assertEqual(pick_chat_model(None), "dexbuddy-chat")

    def test_first_chat_id_wins(self) -> None:
        listed = {
            "data": [
                {"id": "img-1", "kind": "image"},
                {"id": "  ", "kind": "chat"},
                {"id": "chan-chat", "kind": "chat"},
                {"id": "chan-2", "kind": "chat"},
            ]
        }
        self.assertEqual(pick_chat_model(listed), "chan-chat")


class DexChatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_key = os.environ.get("DEX_BUDDY_API_KEY")
        self.old_url = os.environ.get("DEX_BUDDY_MODELS_URL")
        os.environ.pop("DEX_BUDDY_MODELS_URL", None)
        os.environ["DEX_BUDDY_API_KEY"] = "dbh_sk_test"

    def tearDown(self) -> None:
        if self.old_key is None:
            os.environ.pop("DEX_BUDDY_API_KEY", None)
        else:
            os.environ["DEX_BUDDY_API_KEY"] = self.old_key
        if self.old_url is None:
            os.environ.pop("DEX_BUDDY_MODELS_URL", None)
        else:
            os.environ["DEX_BUDDY_MODELS_URL"] = self.old_url

    def test_body_has_only_model_and_messages(self) -> None:
        captured: list = []
        fake = FakeModels({"data": [{"id": "chan-1", "kind": "chat"}]}, captured)
        messages = [{"role": "user", "content": "hi"}]
        with patch("src.dex_chat.bind_models", return_value=fake):
            text = chat(messages)
        self.assertEqual(text, "ok")
        body = captured[0]["body"]
        self.assertEqual(body["model"], "chan-1")
        self.assertEqual(body["messages"], messages)
        self.assertEqual(set(body.keys()), {"model", "messages"})
        self.assertIsNone(captured[0]["options"])

    def test_empty_catalog_uses_fallback_model(self) -> None:
        captured: list = []
        fake = FakeModels({"data": []}, captured)
        with patch("src.dex_chat.bind_models", return_value=fake):
            chat([{"role": "user", "content": "hi"}])
        self.assertEqual(captured[0]["body"]["model"], "dexbuddy-chat")

    def test_empty_content_fails(self) -> None:
        fake = FakeModels(
            {"data": []},
            [],
            {"choices": [{"message": {"content": "  "}}]},
        )
        with patch("src.dex_chat.bind_models", return_value=fake):
            with self.assertRaises(RuntimeError) as ctx:
                chat([{"role": "user", "content": "hi"}])
        self.assertIn("空 content", str(ctx.exception))

    def test_response_format_is_forwarded(self) -> None:
        captured: list = []
        fake = FakeModels({"data": [{"id": "chan-1", "kind": "chat"}]}, captured)
        with patch("src.dex_chat.bind_models", return_value=fake):
            chat(
                [{"role": "user", "content": "hi"}],
                response_format={"type": "json_object"},
            )
        body = captured[0]["body"]
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(set(body.keys()), {"model", "messages", "response_format"})

    def test_max_tokens_is_forwarded(self) -> None:
        captured: list = []
        fake = FakeModels({"data": [{"id": "chan-1", "kind": "chat"}]}, captured)
        with patch("src.dex_chat.bind_models", return_value=fake):
            chat([{"role": "user", "content": "hi"}], max_tokens=8192)
        body = captured[0]["body"]
        self.assertEqual(body["max_tokens"], 8192)
        self.assertEqual(set(body.keys()), {"model", "messages", "max_tokens"})

    def test_list_content_is_joined(self) -> None:
        captured: list = []
        fake = FakeModels(
            {"data": []},
            captured,
            {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": '{"ok": true}'},
                                {"type": "text", "text": "extra"},
                            ]
                        }
                    }
                ]
            },
        )
        with patch("src.dex_chat.bind_models", return_value=fake):
            text = chat([{"role": "user", "content": "hi"}])
        self.assertEqual(text, '{"ok": true}\nextra')


class DexBuddyKeyTests(unittest.TestCase):
    def test_missing_key_points_to_dexbuddy(self) -> None:
        old_key = os.environ.pop("DEX_BUDDY_API_KEY", None)
        old_url = os.environ.pop("DEX_BUDDY_MODELS_URL", None)
        try:
            with patch("src.env_load.load_dotenv", return_value=None):
                with self.assertRaises(RuntimeError) as ctx:
                    require_dex_buddy_api_key()
            msg = str(ctx.exception)
            self.assertIn(".env.example", msg)
            self.assertIn("dexbuddy.app", msg)
            self.assertIn("dbh_sk_", msg)
            self.assertIn("不要放进插件设置", msg)
            self.assertIn("不要打进 zip", msg)
        finally:
            if old_key is not None:
                os.environ["DEX_BUDDY_API_KEY"] = old_key
            if old_url is not None:
                os.environ["DEX_BUDDY_MODELS_URL"] = old_url

    def test_models_url_skips_author_key(self) -> None:
        old_key = os.environ.pop("DEX_BUDDY_API_KEY", None)
        old_url = os.environ.get("DEX_BUDDY_MODELS_URL")
        os.environ["DEX_BUDDY_MODELS_URL"] = "http://127.0.0.1:9"
        try:
            with patch("src.env_load.load_dotenv", return_value=None):
                self.assertEqual(require_dex_buddy_api_key(), "")
        finally:
            if old_key is None:
                os.environ.pop("DEX_BUDDY_API_KEY", None)
            else:
                os.environ["DEX_BUDDY_API_KEY"] = old_key
            if old_url is None:
                os.environ.pop("DEX_BUDDY_MODELS_URL", None)
            else:
                os.environ["DEX_BUDDY_MODELS_URL"] = old_url


if __name__ == "__main__":
    unittest.main()
