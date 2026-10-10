#!/bin/sh
# 打出不含 .env / .venv 的插件目录，并用一条 preview 确认二进制能回 JSON。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
if ! "$PY" -c "import PyInstaller" >/dev/null 2>&1; then
  echo "请先执行: uv pip install pyinstaller" >&2
  exit 1
fi

case "$(uname -s)" in
  Darwin) pack_os=darwin ;;
  Linux) pack_os=linux ;;
  MINGW*|MSYS*|CYGWIN*|Windows_NT) pack_os=win32 ;;
  *)
    echo "无法识别的系统：$(uname -s)" >&2
    exit 1
    ;;
esac
bin_name=manju-studio-worker
if [ "$pack_os" = "win32" ]; then
  bin_name=manju-studio-worker.exe
fi

DIST="$ROOT/temp/plugin-dist"
STAGE="$DIST/manju-studio"
rm -rf "$DIST"
"$PY" -m PyInstaller \
  --onefile \
  --name manju-studio-worker \
  --distpath "$DIST/bin" \
  --workpath "$ROOT/temp/pyinstaller-work" \
  --specpath "$ROOT/temp/pyinstaller-spec" \
  --paths "$ROOT" \
  --add-data "$ROOT/src/prompt_templates:src/prompt_templates" \
  --noconfirm \
  --clean \
  src/studio/hub_worker.py

mkdir -p "$STAGE/bin/$pack_os" "$STAGE/src/studio/static"
cp "$DIST/bin/$bin_name" "$STAGE/bin/$pack_os/"
cp "$ROOT/plugin.manifest.json" "$ROOT/index.js" "$ROOT/icon.svg" "$STAGE/"
cp "$ROOT/src/studio/static/index.html" "$STAGE/src/studio/static/"
cp -R "$ROOT/assets" "$STAGE/assets"
rm -f "$STAGE/assets/.env" "$STAGE/.env"

"$PY" - "$DIST/bin/$bin_name" "$ROOT" <<'PY'
import json
import os
import subprocess
import sys

binary, root = sys.argv[1], sys.argv[2]
req = {
    "id": "1",
    "method": "preview",
    "params": {
        "script_text": "【钩子】\n\n企业老板：入驻产业园以后，除了厂房，园区还能提供什么？\n",
        "filename": "a.md",
    },
}
env = os.environ.copy()
env["MANJU_ROOT"] = root
env["PYTHONUNBUFFERED"] = "1"
env.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
proc = subprocess.run(
    [binary],
    input=json.dumps(req, ensure_ascii=False) + "\n",
    text=True,
    capture_output=True,
    env=env,
    timeout=60,
)
lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
if proc.returncode != 0 or len(lines) != 1:
    sys.stderr.write(proc.stderr or "")
    sys.stderr.write(proc.stdout or "")
    raise SystemExit(f"冒烟失败，退出码 {proc.returncode}")
message = json.loads(lines[0])
if not message.get("ok") or len(message.get("result", {}).get("sections") or []) < 1:
    raise SystemExit(f"冒烟失败: {message}")
print("冒烟通过")
PY

VER=$("$PY" -c "import json; print(json.load(open('plugin.manifest.json'))['version'])")
(
  cd "$DIST"
  zip -r "manju-studio-v${VER}.zip" manju-studio \
    -x '*.DS_Store' \
    -x '*/.git/*' \
    -x '*/.venv/*' \
    -x '*/.env' \
    -x '*/node_modules/*' \
    -x '*/cache/*' \
    -x '*/output/*' \
    -x '*/.cursor/*'
)
echo "发布包: $DIST/manju-studio-v${VER}.zip"
