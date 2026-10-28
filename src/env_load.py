"""从本仓根目录 .env 加载变量；进程环境已有的键不覆盖。"""

from __future__ import annotations

import os
from pathlib import Path

# 源码布局下的本仓根。冻结二进制不能用这个找 output / .env，见 plugin_root()。
REPO_ROOT = Path(__file__).resolve().parents[1]
SETTING_KEYS = (
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "MINIMAX_API_KEY",
)


def plugin_root() -> Path:
    """代码根。index.js 启动 worker 时传入 MANJU_ROOT，用来读 assets 和开发时的 .env。"""
    override = (os.environ.get("MANJU_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return REPO_ROOT


def data_root() -> Path:
    """temp 与 output 的根。装进 Dex Buddy 后由 MANJU_DATA_ROOT 指向用户数据目录。"""
    override = (os.environ.get("MANJU_DATA_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return plugin_root()


def apply_plugin_settings(settings: dict | None) -> None:
    """把设置页传来的键写入环境。只接受清单里声明过的名字。"""
    if not isinstance(settings, dict):
        return
    for key in SETTING_KEYS:
        if key not in settings or settings[key] is None:
            continue
        os.environ[key] = str(settings[key])


def load_dotenv(path: Path | None = None) -> Path | None:
    """解析 KEY=VALUE 行写入 os.environ（仅当键尚未存在）。

    返回实际读取的路径；文件不存在则返回 None。
    """
    env_path = path or (plugin_root() / ".env")
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


def require_dex_buddy_api_key() -> str:
    """独立运行返回 DEX_BUDDY_API_KEY；工作台有代理地址时不要求作者 Key。"""
    load_dotenv()
    if (os.environ.get("DEX_BUDDY_MODELS_URL") or "").strip():
        return ""
    key = (os.environ.get("DEX_BUDDY_API_KEY") or "").strip()
    if key:
        return key
    raise RuntimeError(
        "缺少 DEX_BUDDY_API_KEY。\n"
        "1. 复制本仓 .env.example 为 .env\n"
        "2. 在 https://www.dexbuddy.app 创建用户 Key（dbh_sk_ 开头）并填入\n"
        "3. 不要放进插件设置，也不要打进 zip"
    )
