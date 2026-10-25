@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
REM 雙擊即可啟動。第一次會建立 .venv 並安裝套件（需要網路）。
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  set "PY="
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=py -3"
  if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
  if not defined PY (
    echo 找不到 Python 3.10 以上。請到 https://www.python.org/downloads/windows/ 安裝（Windows ARM 電腦請選 ARM64 版），並勾選 "Add python.exe to PATH"。
    pause & exit /b 1
  )
  if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" echo 提醒：Windows ARM 上若 PySide6 沒有 ARM64 版本，請改裝 x64 版 Python（以模擬執行）。
  echo 第一次執行：建立虛擬環境並安裝套件…
  !PY! -m venv .venv || (echo 建立虛擬環境失敗 & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo 安裝失敗（請確認網路） & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install -r requirements-optional.txt || echo （選用的人臉偵測沒裝上，不影響使用）
)
start "" ".venv\Scripts\pythonw.exe" -m app
