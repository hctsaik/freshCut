# R63 before（R62 版）截圖索引

拍攝：`QT_QPA_PLATFORM=offscreen`，腳本 `review/uiux_r63/shoot.py`。素材：真實 Insta360 LRV 共 7 支（6 支 ~30 秒來自 /workspace/real_labeled/source，1 支長片來自 /workspace/real_long），全新空素材庫。預設視窗 1360×860。

使用者流程：開啟 App（歡迎頁）→ 匯入資料夾 → 背景分析（橫幅顯示進度）→ 每支影片 2–4 個候選片段卡（迴圈小預覽 + 策略 chip：從頭開始／中段／AI 人物／AI 動作／整支）→ 勾選 → 下方「成品順序」時間軸 → 右側「成品設定」→ 預覽／產生成品 → 完成或錯誤對話框。

| 檔案 | 畫面 | 說明 |
|---|---|---|
| 01_welcome_first_tip.png | 歡迎頁 + 首次提示 toast | 空素材庫第一次開啟 |
| 02_welcome.png | 歡迎頁（空狀態） | 三個按鈕：一鍵成片／匯入影片／匯入資料夾 |
| 03_analyzing.png | 分析中 | 橫幅「正在分析 1/7 支」+ 停止；每組顯示「分析中…」；時間軸空狀態 |
| 04_candidates_1360.png | 分析完成後的候選牆（1360 寬） | **已知問題：分析完成當下卡片牆空白**（要等 resize 才排版）；toast 蓋在牆上 |
| 05_candidates_1024.png | 候選牆（1024 寬，右側設定收成抽屜） | 卡片、策略 chip、「分數偏低」標記；toast 蓋住「預覽成品」按鈕 |
| 06_selected_timeline.png | 勾選後時間軸（1360） | 時間軸只有文字項目 |
| 07_wide_1920.png | 1920×1080 寬螢幕 | 卡片固定 192px 預覽、牆右側大量空白；右側設定面板很長 |
| 08_trim_dialog.png | 微調片段對話框 | 開始／結束、速度曲線、水平校正 |
| 09_remove_dialog.png | 刪除確認（移出清單 vs 丟到垃圾桶） | |
| 10_progress.png | 輸出進度 | |
| 11_done.png | 成品完成 | |
| 12_error.png | 錯誤對話框（友善訊息 + 詳細資料） | |
| 13_settings.png | 設定（一般／推薦／雲端 AI／快取） | |
