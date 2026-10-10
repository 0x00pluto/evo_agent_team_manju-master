"""飞书读取：只走 OpenAPI，不访问网络。"""

from __future__ import annotations

import unittest
from pathlib import Path

from src.feishu_doc import FORBIDDEN, MISSING_CREDS, fetch_document

REPO = Path(__file__).resolve().parents[1]
WIKI = "https://example.feishu.cn/wiki/WikiToken1"
DOCX = "https://example.feishu.cn/docx/DocxToken1"
ENV = {"FEISHU_APP_ID": "cli_test", "FEISHU_APP_SECRET": "secret_test"}


class FakeHttp:
    def __init__(self, routes: dict[str, dict]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, body))
        for needle, payload in self.routes.items():
            if needle in url:
                return payload
        raise AssertionError(f"未准备的请求: {method} {url}")


def _token_route() -> dict:
    return {"code": 0, "tenant_access_token": "t-1"}


class FeishuDocTests(unittest.TestCase):
    def test_wiki_resolves_then_reads_docx(self) -> None:
        http = FakeHttp(
            {
                "tenant_access_token": _token_route(),
                "get_node": {
                    "code": 0,
                    "data": {"node": {"obj_type": "docx", "obj_token": "ResolvedDoc"}},
                },
                "raw_content": {"code": 0, "data": {"content": "【钩子】\n企业主：你好。"}},
            }
        )
        text = fetch_document(WIKI, http=http, env=ENV)
        self.assertIn("【钩子】", text)
        urls = [url for _method, url, _body in http.calls]
        self.assertTrue(any("get_node?token=WikiToken1" in url for url in urls))
        self.assertTrue(any("/documents/ResolvedDoc/raw_content" in url for url in urls))
        self.assertEqual(http.calls[0][2], {"app_id": "cli_test", "app_secret": "secret_test"})

    def test_docx_skips_wiki_lookup(self) -> None:
        http = FakeHttp(
            {
                "tenant_access_token": _token_route(),
                "raw_content": {"code": 0, "data": {"content": "【正文】"}},
            }
        )
        self.assertEqual(fetch_document(DOCX, http=http, env=ENV), "【正文】")
        urls = [url for _method, url, _body in http.calls]
        self.assertFalse(any("get_node" in url for url in urls))
        self.assertTrue(any("/documents/DocxToken1/raw_content" in url for url in urls))

    def test_missing_either_credential_raises(self) -> None:
        for env in (
            {},
            {"FEISHU_APP_ID": "cli_test"},
            {"FEISHU_APP_SECRET": "secret_test"},
            {"FEISHU_APP_ID": "  ", "FEISHU_APP_SECRET": ""},
        ):
            with self.assertRaises(RuntimeError) as ctx:
                fetch_document(DOCX, http=FakeHttp({}), env=env)
            self.assertEqual(str(ctx.exception), MISSING_CREDS)

    def test_forbidden_tells_user_to_grant_the_app(self) -> None:
        http = FakeHttp(
            {
                "tenant_access_token": _token_route(),
                "raw_content": {"code": 99991663, "msg": "permission denied"},
            }
        )
        with self.assertRaises(RuntimeError) as ctx:
            fetch_document(DOCX, http=http, env=ENV)
        self.assertIn(FORBIDDEN, str(ctx.exception))

    def test_wiki_non_docx_is_rejected(self) -> None:
        http = FakeHttp(
            {
                "tenant_access_token": _token_route(),
                "get_node": {"code": 0, "data": {"node": {"obj_type": "sheet", "obj_token": "x"}}},
            }
        )
        with self.assertRaises(RuntimeError) as ctx:
            fetch_document(WIKI, http=http, env=ENV)
        self.assertIn("sheet", str(ctx.exception))

    def test_sources_do_not_call_agent_cli(self) -> None:
        roots = [
            REPO / "src",
            REPO / "index.js",
            REPO / "plugin.manifest.json",
            REPO / ".env.example",
            REPO / "docs" / "workflows" / "libtv-studio.md",
            REPO / "docs" / "workflows" / "episode-voiceover.md",
            REPO / "docs" / "workflows" / "minimax-voice-clone-and-tts.md",
        ]
        for path in roots:
            files = [path] if path.is_file() else list(path.rglob("*"))
            for file in files:
                if not file.is_file() or file.suffix not in {".py", ".js", ".json", ".md", ".example"}:
                    if file.name != ".env.example":
                        continue
                text = file.read_text(encoding="utf-8")
                self.assertNotIn("lark-cli", text, file.relative_to(REPO))
                self.assertNotIn("IP_DIGITAL_HUMAN_ROOT", text, file.relative_to(REPO))


if __name__ == "__main__":
    unittest.main()
