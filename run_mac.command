#!/bin/bash
# 在 Finder 雙擊即可啟動。第一次會建立 .venv 並安裝套件（需要網路，約 1–3 分鐘）。
cd "$(dirname "$0")" || exit 1
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ ! -x .venv/bin/python ]; then
  if [ -z "$PY" ]; then
    echo "找不到 Python 3.10 以上。請到 https://www.python.org/downloads/macos/ 安裝（選 universal2 版），裝好後再雙擊一次。"
    read -r; exit 1
  fi
  if [ "$(uname -m)" = "arm64" ] && [ "$("$PY" -c 'import platform; print(platform.machine())')" != "arm64" ]; then
    echo "提醒：這台是 Apple Silicon，但 $PY 是 Intel 版（透過 Rosetta 執行，會比較慢）。建議改裝 universal2 版 Python。"
  fi
  echo "第一次執行：用 $PY 建立虛擬環境並安裝套件…"
  "$PY" -m venv .venv || { echo "建立虛擬環境失敗"; read -r; exit 1; }
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt || { echo "安裝失敗（請確認網路）"; read -r; exit 1; }
  .venv/bin/python -m pip install -r requirements-optional.txt || echo "（選用的人臉偵測沒裝上，不影響使用）"
fi
if [ -z "$FFMPEG_BINARY" ] && [ "$(uname -m)" = "arm64" ] && [ -x /opt/homebrew/bin/ffmpeg ]; then
  export FFMPEG_BINARY=/opt/homebrew/bin/ffmpeg   # 原生 arm64，比 Rosetta 版快
fi
exec .venv/bin/python -m app
