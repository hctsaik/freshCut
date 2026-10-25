# CHANGELOG v7（回應 REVIEW_v4，2026-10-25，Asia/Taipei）

## 第 1 步：設計修正（mockup.html + DESIGN.md v7）
證據：`review/v7/check_results.json`（由 `/workspace/mockcheck/check7.js` 以 headless Chrome 產生；exit 0、`pageErrors: []`、對比檢查無失敗）。

| 項目 | 修正 | 證據鍵 |
|---|---|---|
| N1（必修）自訂長度錯誤殘留 | 切回非「自訂」長度時隱藏錯誤並移除 aria-invalid；只有選「自訂」才驗證 | `N1_staleErr`、`N1_afterRerender` |
| N2（必修）刪除金鑰的時機 | Windows：刪除只在按「套用」或「確定」時生效，按「取消」會還原；macOS：立即生效 | `N2_afterDelete`、`N2_afterCancel`、`N2_afterApply`、`N2_macImmediate` |
| N3 金鑰測試 | Windows：測試成功也要按「套用」或「確定」才會儲存；狀態列顯示「（按「套用」或「確定」後生效）」 | `N3_testBeforeApply`、`N3_afterOK` |
| N4 Home 鍵 | 在卡片上按 Home 跳到該組的名稱按鈕 | `N4_home` |
| 時間軸快捷鍵 | 改為顯示文字；macOS 為 ⌥⌘T，Windows 為 Ctrl+Alt+T；aria-keyshortcuts 依平台設定 | `Sb` |
| N5（選做） | 錯誤訊息加上 role="alert" | `N5_role` |
| N6（選做） | 點抽屜外面關閉抽屜後，焦點回到側欄按鈕 | `N6_focus` |
| O3（選做） | 清單項目的無障礙名稱改為「VID_0001，MP4」 | `O3_accName` |
| S4 | 「請到 Finder 的…」補上空格 | `S4_text` |

設計就此凍結（DESIGN.md v7 §1.13、§8 第 8 輪、§9）。

## 第 2 步：真正的 PySide6 GUI（`app/gui/`，啟動方式：`python -m app`）

### 新增檔案
- `app/gui/main.py`：主視窗、歡迎頁、匯入（按鈕或拖放）、監看計時器、成品設定、摘要、輸出流程
- `app/gui/widgets.py`：
  - 卡片：QMediaPlayer → QVideoSink → QLabel，**靜音、無限循環**
  - 群組標題（重新推薦、手動新增片段）
  - roving focus 卡片牆
  - 時間軸：拖曳，或用 Ctrl+↑↓ / Alt+←→ 移動，Delete 移除
  - 提示訊息（toast）
- `app/gui/dialogs.py`：
  - 微調（I／O）
  - 移除（預設從清單移除）、移到垃圾桶（可只刪除預覽檔）、永久刪除（勾選確認後才能按）
  - 磁碟空間、進度（取消前先確認）、完成（播放、顯示於 Finder／檔案總管）、錯誤（重試）
  - 設定：一般、推薦、雲端 AI、快取；macOS 立即套用，Windows 按確定／取消／套用，金鑰變更也要套用後才生效
  - 雲端 AI 同意說明
- `app/gui/workers.py`：分析與輸出在 QThreadPool 執行，每個工作自己開 SQLite 連線
- `app/gui/ai.py`：選用的 OpenAI 相容 API，金鑰用 keyring 儲存；401→金鑰、429→額度、斷線→離線
- `app/gui/style.py`：深色調色盤與 QSS，顏色值取自 mockup 的 :root 變數；`INSTA_PF=mac|win` 可覆蓋平台
- 其他：`app/__main__.py`、`run_mac.command`、`run_windows.bat`、`requirements.txt`、`README.md`（zh-TW，含 PyInstaller 步驟與 ARM64 ffmpeg 說明）
- `tests/test_gui.py`：離螢幕煙霧測試

### 測試結果（實際執行）
| 測試 | python3（系統，無 PySide6） | .venv/bin/python（PySide6 6.12.0） |
|---|---|---|
| test_core | 通過 | 通過 |
| test_groups | 通過 | 通過 |
| test_library | 通過 | 通過 |
| test_volume | 通過 | 通過 |
| test_gui | **略過**（沒有 PySide6） | 通過 |

`QT_QPA_PLATFORM=offscreen .venv/bin/python -m app`：啟動後持續執行 8 秒、沒有 traceback，由 timeout 結束（exit 124）。

test_gui 驗證的項目：
1. 空素材庫顯示歡迎頁。
2. 匯入 3 支合成影片（各 20 秒）後在背景分析，產生 11 張卡片，每支預設勾選 2 段，時間軸共 6 段。
3. 11 張卡片全部播出影格，所有播放器都是靜音。
4. 空白鍵可以勾選與取消。
5. 全部取消勾選時，「產生成品」停用並顯示原因。
6. 時間軸用 Ctrl+↓ 改變順序。
7. N1：自訂 5 秒（4 段）會顯示錯誤，切回 15 秒後錯誤消失。
8. 輸出 1920×1080、14.5 秒的成品，與預期長度相符（4 段 × 4 秒，扣掉 3 次 0.5 秒轉場）。
9. Windows 語意：刪除金鑰後按「取消」，金鑰不會被刪除。
10. 從清單移除後可以復原。

截圖：`review/v7/gui_1_welcome … gui_7_trash.png`

## 尚未完成／未驗證（誠實列出）
- **只在 Linux 離螢幕環境測試過**：沒有在真的 macOS 或 Windows 上跑過。以下都還沒驗證：
  - `run_mac.command`、`run_windows.bat`
  - PyInstaller 打包
  - 硬體編碼
  - 原生檔案對話框
  - Finder／檔案總管的「顯示於」
  - 真實磁碟的垃圾桶判斷（DESIGN §11 的 R6 清單）
- **與 mockup 不同、GUI 沒有做的部分**：
  - 窄視窗時的側欄抽屜
  - 首次使用提示
  - 「繼續上次」與「匯入選項」對話框
  - 移到垃圾桶後的「復原」（toast 只會顯示結果）
  - 輸出進度的剩餘時間
  - 卡片的移除動畫
- **雲端 AI**：
  - 沒有對真實服務測試過。
  - .venv 沒有安裝 keyring，所以測試時雲端 AI 處於停用狀態，只驗證了停用時的提示。
  - 搜尋在 UI 執行緒同步執行，最多會卡住 90 秒，之後應改成背景執行。
- **測試沒有覆蓋的流程**：
  - 拖放匯入、微調對話框的 I／O 鍵、手動新增片段
  - 預覽成品、磁碟空間不足的對話框
  - 永久刪除與略過流程（邏輯已在 test_library 中測試，GUI 部分沒有）
  - 取消輸出
- **按鈕順序**：所有對話框的按鈕順序在 Windows 都會反轉（主要按鈕在左）。設定對話框已調整為「確定 取消 套用」，其他對話框沒有逐一核對 Windows 慣例。
- **重新推薦與手動新增片段**：在 UI 執行緒同步執行。一支影片約 1–3 秒，期間介面會卡住。
- **停止分析**：只會在兩支影片之間停下來。
