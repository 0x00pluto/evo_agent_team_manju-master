#!/usr/bin/env python3
"""本机漫剧操作台：http://127.0.0.1:8767/"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.env_load import load_dotenv  # noqa: E402
from src.studio.dev_reload import (  # noqa: E402
    POLL_SECONDS,
    SETTLE_SECONDS,
    mtime_snapshot,
    python_sources,
    should_reload,
)
from src.studio.server import serve  # noqa: E402

_RELOADED = "STUDIO_RELOADED"


def _watch(httpd, root: Path, reload_requested: threading.Event) -> None:
    """源码变更且没有任务时停掉 serve_forever，由主线程重新拉起进程。"""
    baseline = mtime_snapshot(python_sources(root))
    while not reload_requested.is_set():
        time.sleep(POLL_SECONDS)
        current = mtime_snapshot(python_sources(root))
        if current == baseline:
            continue
        time.sleep(SETTLE_SECONDS)
        current = mtime_snapshot(python_sources(root))
        manager = getattr(httpd, "studio_manager", None)
        busy = manager.is_busy() if manager is not None else False
        if not should_reload(baseline, current, busy=busy):
            continue
        print("检测到代码变更，正在重新加载", flush=True)
        os.environ[_RELOADED] = "1"
        reload_requested.set()
        httpd.shutdown()
        return


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
    reloaded = os.environ.get(_RELOADED) == "1"
    if args.open and not reloaded:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    reload_requested = threading.Event()
    threading.Thread(
        target=_watch,
        args=(httpd, REPO_ROOT, reload_requested),
        daemon=True,
    ).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        httpd.server_close()
        return 0
    httpd.server_close()
    if reload_requested.is_set():
        os.execv(sys.executable, [sys.executable, *sys.argv])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
