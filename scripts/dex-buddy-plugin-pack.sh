#!/bin/sh
# 给 Dex Buddy 的 Publish Plugin 在编译机上调用。只把本机 worker 放到 bin/，不打 zip、不上传。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT"

os_name="${DEX_BUDDY_OS:-}"
if [ -z "$os_name" ]; then
  case "$(uname -s)" in
    Darwin) os_name=darwin ;;
    Linux) os_name=linux ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT) os_name=win32 ;;
    *)
      echo "无法识别的系统：$(uname -s)" >&2
      exit 1
      ;;
  esac
fi

case "$os_name" in
  darwin|linux)
    bin_name=manju-studio-worker
    data_sep=":"
    ;;
  win32)
    bin_name=manju-studio-worker.exe
    data_sep=";"
    # 关掉 Git Bash 的自动改路径，改由 cygpath 交给 Windows 版 Python。
    export MSYS_NO_PATHCONV=1
    ;;
  *)
    echo "DEX_BUDDY_OS 必须是 darwin、win32 或 linux：$os_name" >&2
    exit 1
    ;;
esac

to_native() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$1"
  else
    printf '%s\n' "$1"
  fi
}

if command -v python3 >/dev/null 2>&1; then
  boot=python3
elif command -v python >/dev/null 2>&1; then
  boot=python
else
  echo "找不到 python3" >&2
  exit 1
fi

venv="$ROOT/temp/dex-buddy-pack-venv"
dist="$ROOT/temp/dex-buddy-pack-dist"
work="$ROOT/temp/pyinstaller-work"
spec="$ROOT/temp/pyinstaller-spec"
rm -rf "$venv" "$dist" "$work" "$spec"
mkdir -p "$ROOT/temp"
"$boot" -m venv "$(to_native "$venv")"

if [ -x "$venv/bin/python" ]; then
  py="$venv/bin/python"
elif [ -x "$venv/Scripts/python.exe" ]; then
  py="$venv/Scripts/python.exe"
else
  echo "虚拟环境里没有 Python" >&2
  exit 1
fi

"$py" -m pip install -r "$(to_native "$ROOT/requirements.txt")" pyinstaller
"$py" -m PyInstaller \
  --onefile \
  --name manju-studio-worker \
  --distpath "$(to_native "$dist")" \
  --workpath "$(to_native "$work")" \
  --specpath "$(to_native "$spec")" \
  --paths "$(to_native "$ROOT")" \
  --add-data "$(to_native "$ROOT/src/prompt_templates")${data_sep}src/prompt_templates" \
  --noconfirm \
  --clean \
  "$(to_native "$ROOT/src/studio/hub_worker.py")"

built="$dist/$bin_name"
if [ ! -f "$built" ]; then
  echo "没有生成 $bin_name" >&2
  exit 1
fi
mkdir -p "$ROOT/bin"
cp "$built" "$ROOT/bin/$bin_name"
if [ "$bin_name" = "manju-studio-worker" ]; then
  chmod +x "$ROOT/bin/$bin_name"
fi

"$py" - "$(to_native "$ROOT/bin/$bin_name")" "$(to_native "$ROOT")" <<'PY'
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

rm -rf "$venv" "$dist" "$work" "$spec"
echo "已写入 bin/$bin_name"
