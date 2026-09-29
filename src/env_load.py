"""从本仓根目录 .env 加载变量；进程环境已有的键不覆盖。"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = REPO_ROOT / ".env"


def load_dotenv(path: Path | None = None) -> Path | None:
    """解析 KEY=VALUE 行写入 os.environ（仅当键尚未存在）。

    返回实际读取的路径；文件不存在则返回 None。
    """
    import os

    env_path = path or DEFAULT_ENV_PATH
    if not env_path.is_file():
        return None

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key not in os.environ:
            os.environ[key] = value
    return env_path


def require_deepseek_api_key() -> str:
    """返回 DEEPSEEK_API_KEY；缺失时抛出带配置指引的 RuntimeError。"""
    import os

    load_dotenv()
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if key:
        return key
    raise RuntimeError(
        "缺少 DEEPSEEK_API_KEY。\n"
        "1. 复制本仓 .env.example 为 .env\n"
        "2. 在 https://platform.deepseek.com/api_keys 申请 key 并填入\n"
        "3. 文档：https://api-docs.deepseek.com/zh-cn/"
    )
