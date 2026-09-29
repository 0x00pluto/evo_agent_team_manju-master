#!/usr/bin/env python3
"""本机漫剧操作台：http://127.0.0.1:8767/"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.env_load import load_dotenv  # noqa: E402
from src.studio.server import serve  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="漫剧操作台（本机）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    args = parser.parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("拒绝非本机绑定：请使用 127.0.0.1", file=sys.stderr)
        return 2
    httpd = serve(REPO_ROOT, host=args.host, port=args.port)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"漫剧操作台 → {url}")
    print("Ctrl+C 停止。")
    if args.open:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
