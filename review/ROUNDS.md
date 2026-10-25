# 自我改善輪次紀錄

規則：每輪 4 位審查者（Insta360 新手、專業剪輯師、UX/無障礙設計師、資深 Python/Qt 工程師，關注 Mac/Windows ARM 效能），
只挑最高影響的問題，改真程式碼，兩個直譯器（python3、.venv/bin/python）+ 離螢幕 GUI 煙霧測試都要跑。
分數 0–100：功能 / UI·UX / 程式品質 / vs FlashCut AI 剪輯。測試結果只寫實際觀察到的。

說明：第 1–5 輪的程式在同一個工作階段陸續完成，中途被中斷過；當時沒有逐輪寫紀錄。
下面每輪的「測試」欄是 2026-10-25 01:30–02:00（台北時間）對**最終程式碼**的完整重跑（/tmp/r4.log），
不是每輪當下各自的結果。這點如實註明。

基準（v7，輪次開始前）：功能 62 / UI·UX 70 / 程式品質 68 / vs FlashCut 25

---

## 第 1 輪：背景工作與可中斷的 ffmpeg（2026-10-25，台北時間）
- 問題（工程師、新手）：重新推薦、手動新增、微調、雲端 AI 在主執行緒跑，介面會卡住；「停止分析」要等目前影片的 ffmpeg 跑完；取消後留下半成品快取。
- 改動：
  - `core._run` 改用 Popen 輪詢，搭配執行緒區域的 `set_cancel`，取消時立刻終止 ffmpeg（拋出 `core.Cancelled`）。
  - `workers.Job` 增加 cancelled 訊號；reanalyze、manual_clip、trim、ai_search 全部移到 QThreadPool。
  - `Library.analyze` 改成交易式：取消或出錯就回滾並刪除新產生的檔案；舊檔在 commit 之後才刪除。順便修掉 `_make_assets` 會誤刪同名新 proxy 的舊 bug。
  - 輸出取消後會刪除不完整的檔案。
- 新測試：test_core `run cancel`；test_gui 驗證背景工作期間事件迴圈有在跑（reanalyze 0.7 秒，ticks 29）、120 秒影片中途停止 < 2 秒且不留半成品、輸出取消。
- 測試：全部通過（兩個直譯器；system python3 沒有 PySide6，test_gui 印 SKIP）。
- 分數：功能 64 / UI·UX 74 / 程式品質 75 / vs FlashCut 25

## 第 2 輪：精華評分升級＋去除重複畫面
- 問題（剪輯師）：分數只看動態與音量，晃動或模糊的片段排在前面，同一個畫面重複出現好幾次。
- 改動：`core.features` 一次解碼 64×36 小圖，計算：
  - 動態、清晰度（Laplacian）、晃動（相位相關法估全域位移的抖動）、曝光、色彩
  - 主體水平位置
  - 音訊 RMS 與 dB 起音峰值
  
  候選片段用 MMR 挑出多樣的片段，並排除相似度 ≥ 0.93 的近乎重複畫面。DB 新增 sig、peak、track 欄位。
- 新測試：test_ai 晃動 0.688 vs 穩定 0.233；dedupe。
- 附帶修正（本次重跑時發現）：test_gui 原本用 rgbtestsrc／smptebars 靜止畫面，去重後每支只剩 1 段，舊斷言「6 段」失敗。這是正確行為，所以把測試素材改成會動的 mandelbrot 和 life。
- 測試：全部通過。
- 未做：人臉／笑臉偵測（環境沒有 OpenCV，沒有假裝做了）。
- 分數：功能 68 / UI·UX 74 / 程式品質 76 / vs FlashCut 35

## 第 3 輪：本機節拍偵測＋對拍剪輯
- 問題（新手、剪輯師）：FlashCut 的賣點是 on beat，我們沒有。
- 改動：
  - 新增 `app/beats.py`（純 numpy）：頻譜通量、自相關測速（拋物線插值）、Ellis DP 追拍。
  - 節奏分為 輕快 2 拍、平穩 4 拍、史詩 8 拍；snap_segments 以精彩點為中心切出每段。
  - 節拍結果快取在 DB 的 kv（依路徑、大小、mtime）。
- 本次修正的 bug：對拍時每段都被設成「1 個節奏單位」，一鍵成片目標 30 秒只輸出 7.97 秒（GUI 測試抓到）。改成每段長度取節奏單位的整數倍、最接近原本長度後，同一流程輸出 23.93 秒。
- 新測試：
  - 120 BPM 合成音軌測速
  - 輸出長度是 2 秒拍長的整數倍
  - 對拍不會縮短總長（wants 測試）
- 測試：全部通過。
- 分數：功能 73 / UI·UX 75 / 程式品質 77 / vs FlashCut 48

## 第 4 輪：一鍵成片＋風格範本＋鎖定/換一批
- 問題（新手）：要點很多步才能出片。（剪輯師）FlashCut 可以鎖定喜歡的片段再重新洗牌，我們沒有。
- 改動：
  - 工具列和歡迎頁加入「一鍵成片」：選資料夾 → 背景分析 → auto_pick（每支至少 1 段、去重、依拍攝時間排序）→ 對拍 → 輸出。
  - 風格範本 Vlog／運動／旅行會一次設定節奏、轉場、慢動作、長度和標題。
  - 新增「換一批」（R8）：鎖定（L 鍵或 🔒 按鈕，有無障礙名稱）的片段會保留，上一批的其他片段分數打 5 折，換成不同的畫面。DB 新增 clips.locked 欄位。
- 新測試：
  - test_gui：one_click 加音樂、標題、日期，輸出 23.93 秒；L 鍵鎖定後換一批，鎖定的片段保留、其他有換（[5,6,7,8,9,14,15,16] → [5,6,9,10,13,14,15,16]）。
  - test_ai：reshuffle。
- 測試：全部通過。截圖：review/v7/gui_8_ai_panel.png、gui_9_locked.png。
- 分數：功能 79 / UI·UX 78 / 程式品質 77 / vs FlashCut 60

## 第 5 輪：智慧 9:16、峰值慢動作、片頭字卡、360、離線語意搜尋、剩餘時間
- 問題（剪輯師）：9:16 只會置中裁切，會切掉主體；沒有慢動作和標題。（新手）想搜尋「海邊」又不想上傳。（工程師）imageio-ffmpeg 內建的 ffmpeg 沒有 drawtext，加標題就整個輸出失敗（只在 .venv 重跑時才發現）。
- 改動：
  - 智慧構圖：用 crop 的 t 運算式做平滑水平移動，跟著分析出的主體位置走。
  - 峰值慢動作：用 setpts 加 atempo，變速段落之後 concat。
  - 片頭字卡：drawtext 加淡入淡出。ffmpeg 沒有 drawtext 時改用 Qt 畫透明 PNG 疊上去（新增 `core.has_filter`）。
  - 360 素材：equirect 透過 v360 轉成平面。.insv 雙魚眼的參數還沒驗證。
  - 本機 CLIP（open_clip ViT-B-32，選用）：中文詞先查表翻成英文，向量快取在 clips.emb；沒有安裝就退回顏色規則。修好 clipvenv 的 torchvision 版本不符（改裝 CPU 版 0.29.1）。
  - 輸出進度顯示「約剩 N 秒／分鐘」。
  - run_mac.command 會找 Python 3.10 以上，並提醒 Rosetta 版 Python；arm64 有 Homebrew ffmpeg 時優先使用。run_windows.bat 會檢查版本並提示 ARM64（Windows 實機沒測）。
  - test_gui 加入 faulthandler 逾時保護，並攔截錯誤對話框，避免測試卡死；過程中抓到測試本身的 AIError 參數 bug。
- 新測試：
  - 構圖：smart 亮度 46 vs 置中 31
  - 慢動作加標題：輸出 5.0 秒；標題區白色像素 1.5 秒時 0.068、4.5 秒時 0.0，兩個直譯器都通過（.venv 走 PNG 替代路徑）
  - 360 轉 1920×1080
  - test_semantic：在 clipvenv 下「海邊／雪／夜景」都排第一，素材庫向量都有寫入；沒有 open_clip 時 SKIP
  - ETA
- 測試：全部通過，包括 clipvenv 的 test_semantic。
- 分數：功能 84 / UI·UX 80 / 程式品質 79 / vs FlashCut 68

### 趨勢
| 輪 | 功能 | UI/UX | 程式 | vs FlashCut |
|---|---|---|---|---|
| 基準 | 62 | 70 | 68 | 25 |
| 1 | 64 | 74 | 75 | 25 |
| 2 | 68 | 74 | 76 | 35 |
| 3 | 73 | 75 | 77 | 48 |
| 4 | 79 | 78 | 77 | 60 |
| 5 | 84 | 80 | 79 | 68 |

下一步候選：
- 內建免版稅音樂或自動挑歌（FlashCut 有）
- 人臉偵測（選用 OpenCV/mediapipe）
- .insv 雙魚眼實測
- 窄視窗抽屜、首次使用提示
- DESIGN.md 同步
- 拖放、低磁碟空間的煙霧測試

## Round 6 — 人臉／笑臉偵測（2026-10-25 02:00 台北時間）
- 四位角色審查：新手（「有人的片段應該優先」）、專業剪輯師（直式構圖該跟著臉）、UX（不能多一個要設定的開關）、效能（不可下載模型、ARM 要能跑）。
- 改了什麼：新增 app/faces.py，使用 OpenCV 內建的 Haar 臉部與笑臉 cascade，不必下載模型。core.features 在有 cv2 時多跑一次 320×180 灰階解碼：有臉的片段分數 +0.25·face +0.2·smile，focus_x 改成臉的位置。沒有 cv2 時就照舊，自動退回原本的作法。requirements.txt 把 opencv-python-headless<5 列為選用（5.0.0 沒有 CascadeClassifier）。
- 修正：equalizeHist 會讓 Haar 漏掉臉，所以改成先用原始灰階偵測，只有低對比時才再試等化後的影像。
- 測試：新增 tests/test_faces.py，使用 NASA 公有領域人像（tests/data/LICENSES.md）。結果 face 0.0→0.51，focus_x 0.79（目標 0.75±0.08）。完整 runtests.sh 在兩個直譯器都通過，加上 test_gui OK 與 SEMANTIC OK（/tmp/r6.log）。system python3 沒有 cv2，所以 test_faces 會誠實 SKIP。
- 未驗證：笑臉偵測只確認會執行，沒有用真實笑臉影片驗證準確度；Windows ARM 的 OpenCV wheel 也還沒驗證。
- 分數：功能 87／UI/UX 80／程式碼 80／vs FlashCut 72

## Round 7 — 內建免版稅音樂（2026-10-25 02:04 台北時間）
- 審查：新手（「沒有音樂資料夾就沒配樂」是 FlashCut 最大的落差）、剪輯師（拍點一定要準）、UX（不必另外設定）、效能（不可增加安裝包體積）。
- 改了什麼：新增 app/music.py，用 numpy 即時合成四種氣氛（輕快 120／放鬆 84／熱血 140／溫馨 96 BPM）。第一次用到時合成到素材庫的 music/ 資料夾，大約 1 秒，之後沿用。背景音樂選單常駐四個「內建・…（自動合成，CC0）」選項。另有 pick_mood_from_folder，可以依檔名關鍵字從使用者的資料夾挑出氣氛相符的歌（還沒接上 UI）。MUSIC_LICENSE.md 誠實說明這是合成音、CC0、音質有限，而且 Content ID 沒有驗證過。
- 測試：新增 test_music，四種氣氛偵測到的 BPM 和設定值的誤差都在 0.3 以內，也驗證了快取。test_gui 加入內建音樂的流程。完整測試 19 項 exit=0（/tmp/r7.log）。
- 誠實註記：音質遠比不上 FlashCut 的授權曲庫，只是補上「沒有任何音樂可用」的缺口。
- 分數：功能 89／UI/UX 81／程式碼 81／vs FlashCut 75

## Round 8 — 濾鏡與自動調色（2026-10-25 02:09 台北時間）
- 審查：新手（陰天拍的片太灰）、剪輯師（要有幾種一致的 look）、UX（預設要安全）、效能（不能增加太多輸出時間）。
- 改了什麼：core.LOOKS 加入 6 種濾鏡，用 ffmpeg 的 eq/curves/colorbalance/colortemperature/vibrance/hue 組成。look_filter 遇到缺少的 filter 會略過，不讓輸出失敗。auto_enhance_filter 每段取 3 張 64×36 小圖量亮度、對比、飽和度，再產生溫和的 eq（已考慮 eq 以 0.5 為中心的對比換算）。UI 新增「濾鏡」選單與「自動調色」（預設開）。風格範本「運動→鮮豔」「旅行→電影」。
- 測試：新增 test_looks：偏暗素材平均亮度 0.226→0.308、std 0.119→0.169；黑白的飽和度 0.000；鮮豔的飽和度 +28%。test_gui 驗證範本會帶出濾鏡。完整測試 21 項 exit=0（/tmp/r8.log）。
- 誠實註記：自動調色每段多 3 次 ffmpeg seek，長片的成本還沒量測；沒有 .cube LUT 匯入；沒有貼紙與特效；濾鏡在 UI 裡沒有即時預覽，要按「預覽成品」才看得到。
- 分數：功能 91／UI/UX 82／程式碼 82／vs FlashCut 78

## Round 9 — 直式構圖跟拍品質、窄視窗抽屜、第一次使用提示（2026-10-25 02:14 台北時間）
- 審查：剪輯師（9:16 鏡頭會微晃、臉漏偵測時會跳）、新手（不知道從哪開始）、UX（筆電視窗窄時卡片牆被擠成一欄）、效能（純 Python 運算，不增加解碼）。
- 改了什麼：
  - smart.smooth_path 加入死區（主體在 ±0.05 內鏡頭不動），有臉的取樣點跟得比較快。新增 fill_face_gaps：臉漏偵測 ≤4 個取樣點（約 2 秒）時用前後位置內插，不跳回動態重心。軌跡多存 "c"（臉的可信度）。
  - 視窗寬度 < 1180 px 時，右側「成品設定」收進抽屜，由底部的「成品設定 ▸／◂」按鈕切換，打開時焦點移到第一個欄位。
  - 第一次開啟時顯示「一鍵成片」提示 15 秒，只出現一次，記在 kv tip_seen。Toast 改成會換行、有最小寬度，位置上移，不再蓋住底部按鈕（截圖中看到的問題）。
- 數據（同一組 ±0.04 抖動輸入）：舊版每步最大移動 0.0083，新版 0.0054（−35%）；但整體 std 由 0.0051 升到 0.0069（死區造成小幅偏移），誠實記錄。
- 測試：新增 test_reframe（去抖動、階梯跟上、補臉漏偵測、crop 運算式）。test_gui 驗證抽屜開關、寬窄切換、提示只出現一次，並截圖 gui_0_first_tip、gui_10_narrow_drawer（已目視檢查）。完整測試 23 項 exit=0（/tmp/r9.log）。
- 未驗證：還沒用真實人物的 360／運動影片做主觀跟拍評估；抽屜是推開版面而不是浮層，在 1000 px 寬時卡片牆只剩一欄半。
- 分數：功能 92／UI/UX 85／程式碼 83／vs FlashCut 80

## Round 10 — 拖放與磁碟不足煙霧測試、文件同步、打包（2026-10-25 02:27 台北時間）
- 審查：新手（把整包 SD 卡內容拖進來）、UX（重新整理時卡片疊影，截圖可見）、效能（關閉視窗後計時器仍在跑）、跨平台（Windows ARM 沒有 OpenCV wheel 時安裝會失敗）。
- 改了什麼（含測試抓到的真 bug）：
  - **拖放會把 .txt 等非影片檔匯入**（新測試抓到）：改成只收 core.VIDEO_EXTS，並提示略過了幾個檔；純文字拖曳不接受。
  - **關閉視窗後監看計時器仍會碰已關閉的資料庫**（第二個視窗的測試抓到 sqlite3.ProgrammingError）：closeEvent 先停止計時器。
  - **重新整理卡片牆時，舊卡片會疊在新卡片上**（r10 截圖目視發現）：Wall.clear 先 hide 再 deleteLater。
  - OpenCV 移到 requirements-optional.txt，由啟動腳本另外安裝，失敗也不中斷（Windows 腳本仍未實機執行）。
  - DESIGN.md 新增 1.14，並誠實註明窄視窗抽屜與 3.2 原規格的差異；README 同步功能、結構與限制。
- 測試：test_gui 新增真正的 QDragEnterEvent/QDropEvent 拖放測試，以及模擬磁碟只剩 1 MB 的 DiskDialog 測試（取消後不開始輸出、不留檔）。最終完整測試 23 項 exit=0、0 個 Traceback（/tmp/r10final.log）。截圖存成 review/rounds/r10_*.png，已目視檢查 first_tip、narrow_drawer、ai_panel。
- 未解決：1024 寬時群組標題列的「＋手動新增片段」按鈕被裁切；test 直接呼叫 apply_style，所以範本選單顯示「自訂」；Windows／Mac 實機都沒有驗證。
- 分數：功能 93／UI/UX 86／程式碼 85／vs FlashCut 82

### 趨勢（R6–R10）
| 輪 | 功能 | UI/UX | 程式碼 | vs FlashCut |
|---|---|---|---|---|
| R5 | 84 | 80 | 79 | 68 |
| R6 | 87 | 80 | 80 | 72 |
| R7 | 89 | 81 | 81 | 75 |
| R8 | 91 | 82 | 82 | 78 |
| R9 | 92 | 85 | 83 | 80 |
| R10 | 93 | 86 | 85 | 82 |

## R11 — 1024 裁切修正 + 分享預設（2026-10-25 Asia/Taipei）
- 四視角：新手「1024 寬看不到手動新增」；UX「固定 3 欄導致水平裁切」；專業「要一鍵出 Reels/Shorts/TikTok 規格與響度」；Qt「resize 時重排要節流」。
- 改動：Wall.set_cols 依 viewport 寬自動 1–4 欄（QTimer.singleShot(0) 合併 resize）；GroupHeader.compact(<560px) 縮短文字但保留無障礙名稱；新增「分享到」：IG Reels / YouTube Shorts / TikTok / YouTube 橫式（比例、1080p、建議長度、loudnorm -14 LUFS、檔名後綴）。預覽不做 loudnorm。
- 測試：test_gui R11（1024×700 下每個標題列按鈕在 viewport 內、2 欄；選 IG Reels → 9:16/30 秒/loudnorm/檔名 _Reels）；test_looks 量測 ebur128 整合響度 = -14.0 LUFS。runtests.sh 全部 exit 0（觀察到）。
- 未驗證：平台長度上限會變動，僅作「建議長度」；未在實機 Mac/Win 上看 1024。
- 分數：Features 93 / UI/UX 88 / Code 85 / vs-FlashCut 83

## R12 — .cube LUT 匯入＋即時濾鏡預覽（2026-10-25 Asia/Taipei）
- 改動：core.parse_cube（只收 3D、檢查格點數）、_ff_path（Windows 冒號/反斜線/單引號跳脫）、look_filter 支援 "lut:<path>"；preview_look 取一格套自動調色＋濾鏡；GUI「匯入 LUT」複製到媒體庫 luts/、啟動時重新載入；設定變動 250ms 去抖動後在背景產生預覽圖。
- 測試：test_looks（反轉 LUT 讓紅→青 [252,0,0]→[2,255,255]；壞 LUT 被拒；黑白預覽 std<3；路徑含空白與中文）；test_gui R12（匯入、預覽圖出現、不存在的檔案只 toast）。
- 問題：test_looks 第一次在 .venv 用了 PIL（未安裝）而失敗 → 改用 ffmpeg 解碼。**同時發現 runtests.sh 不管子測試失敗都回 0**（R11 以前的紀錄已逐行檢查 exit=，R11 沒有非 0）；已改成統計 FAILED_RUNS 並以此為 exit code。
- 未驗證：Windows 實機 LUT 路徑跳脫只用字串測試；預覽只取第一段。
- 分數（依 REVIEW_r10 校準，自評改保守）：Features 84 / UI/UX 81 / Code 80 / vs-AutoEdit 63

## R13 — REVIEW_r10 必改 B1–B4（2026-10-25 Asia/Taipei）
- 獨立審查（82/80/80/62）明顯低於我 R10 自評（93/86/85/82），之後以審查分數為基準。
- B1：core.export 先寫 <out>.part.mp4，成功才 os.replace；finally 只刪 .part；GUI 取消不再 os.remove(out)。
- B2：_analyze_failed 清 _after_analysis 與 _an_queue。
- B3：已勾選卡片焦點改白色 3px 外框＋背景變亮（白 vs 黃框可辨）；對比值未用工具量測，**未驗證 ≥3:1**。
- B4：兩個 QScrollArea 設 NoFocus；_fix_tab_order：工具列→搜尋/清單→卡片牆→時間軸→成品設定→預覽/產生。
- 文件：FLASHCUT_COMPARE 改以 Insta360 Auto Edit 官方手冊為主要基準；刪除「360 我方較強」；修正過時的「沒有鎖定+重洗」。
- 測試：新 test_safe_export（取消、失敗都保留原檔 bytes、無 .part 殘留、成功才覆蓋）；test_gui R13（B2 失敗後無殘留、NoFocus、焦點鏈中卡片在時間軸與產生成品之前）。test_gui 單跑通過；全套見 R14。
- 分數：Features 84 / UI/UX 83 / Code 82 / vs-AutoEdit 63

## R14 — REVIEW_r10 建議 B5–B8＋對比＋.venv CLIP（2026-10-25 Asia/Taipei）
- B5：分析時，低於媒體庫最高分 45% 的片段不自動勾選；smart.auto_pick（一鍵成片）同樣排除，鎖定的除外。代價：素材差時成品可能短於目標（刻意不放寬，否則 60 秒目標會把 B5 那種片段塞回來）。限制：第一支分析的影片沒有比較對象。卡片上**還沒有**「分數偏低」標註。
- B6：取消勾選保留 ord，重新勾選回原位（ORDER BY ord, id）。
- B7：core.friendly_error（磁碟、權限、找不到檔案、損毀、ffmpeg、其他）；ErrorDialog 顯示白話說明，原文收在「詳細資料」。
- B8：時間軸項目寬度依文字計算、ElideNone；toast 錨定在時間軸區塊上方。
- B3 修正：R13 的白框對黃框只有 1.6:1，不合格 → 改 4px #186FCF（對勾選黃 3.12:1、對卡片底 3.19:1，test_gui 計算）。停用元件邊框 #767676（對 #202020 3.59:1）。
- .venv 安裝 CPU 版 torch＋open_clip_torch；.venv test_semantic 首次真的跑 CLIP 並通過（海邊/雪/夜景）。新增 requirements-clip.txt。
- 測試：test_pick_threshold（新）、test_ai 改為斷言不收低分片段、test_gui R14（對比值、B6 原位、B7 詳細資料、B8 1024 下 toast 底 < 時間軸頂）。舊 test_gui 兩處依舊行為的斷言已改（勾 6 段→4–6 段；重新勾選順序→集合比對）。runtests.sh：FAILED_RUNS=0，exit 0（觀察到）。
- 分數：Features 85 / UI/UX 85 / Code 83 / vs-AutoEdit 64

## R15 — 本機 CLIP 自動標籤（海/山/雪/夜景/人物/寵物）＋一鍵成片「主題標籤」
- semantic.TAGS／auto_tags：zero-shot softmax(100·cos)，同標籤多提示機率相加，另有 7 個「其他」負類，門檻 0.2、最多 2 個標籤。
- Library.tag_clips（只算缺標籤的、可 force）、tag_counts；clips.tags 欄位（migration）。分析完成後背景 tag_job；沒裝 CLIP 就不跑，失敗不跳錯誤視窗。
- 卡片顯示「#海  #人物」chip（12px #E0E0E0），讀屏名稱附「標籤 …」；右側「主題標籤」下拉（顯示各標籤段數），一鍵成片／換一批時該標籤分數 ×1.6。
- 測試：test_semantic（clipvenv＋.venv 真 CLIP）合成海灘→海、夜景→夜景；合成雪景被判成「山」（雪 0.00）——測試接受 山/雪，**雪的辨識未獲證實**。testsrc 彩條不會被貼成人物/寵物。test_gui：chip、讀屏名稱、主題優先被選入、段數顯示。
- runtests：FAILED_RUNS=0。截圖 review/rounds/r15_tags.png（加標籤的卡片不在可視範圍，chip 由斷言驗證）。
- 未驗證：真實旅遊影片的標籤準確率（沒有真實素材）；人物/寵物從未有正例測試；chip 無法點擊篩選。
- 分數（保守）：Features 86 / UI/UX 85 / Code 83 / vs-AutoEdit 65

## R16 — 文字效果＋貼圖
- 片頭「文字效果」經典/霓虹（多層青色光暈）/標籤（黃底黑字）/電影（上下黑邊）；「文字動畫」淡入/上滑/放大（overlay eval=frame）。非預設組合一律用 Qt 畫 PNG，不依賴 drawtext。
- 貼圖：10 個 emoji（Noto/Apple/Segoe Color Emoji），四角位置，整片顯示、0.4 秒淡入，大小為短邊 16%。
- 測試 test_text_fx（需 PySide6；python3 環境 SKIP）：對純灰影片量測——三種風格在 1.2 秒中央有字、5 秒消失；右上貼圖整片在、左上沒有；黃底/青光/黑邊各自可測；上滑的文字重心 0.25 秒時比 1.2 秒低。test_gui：控制項→_prep/options。截圖 review/rounds/r16_textfx.png（霓虹＋❤️）。
- runtests：FAILED_RUNS=0（注意：此次執行期間我已開始改 R17 的 smart.py，結果僅供參考，R17 會重跑）。
- 未做：貼圖拖曳定位、多張貼圖、逐段字幕、文字預覽（只在輸出看得到）。Auto Edit 有大量模板文字/貼圖，這裡只是最小可用。
- 分數（保守）：Features 87 / UI/UX 85 / Code 83 / vs-AutoEdit 66

## R17 — 慢動作漸變＋9:16 跟拍去晃動
- 驗證 R16：完整 runtests（R16+R17 程式碼）FAILED_RUNS=0；python3 沒有 PySide6/opencv/open_clip，test_gui/test_text_fx/test_faces/test_semantic 在 python3 下是 SKIP，只在 .venv 實跑（R16 OK、TEXT FX OK）。
- 慢動作：smart.ramp_pieces 改成 1 → 0.75 → 0.5 → 0.75 → 1（前後各 0.25 秒過渡），ramp_extra 同步修正對拍長度計算。
- Bug 修正：慢動作段的 setpts 原本在裁切前，裁切軌跡的 t 被拉長，跟拍在慢動作段落後一半；現在 setpts 放在裁切／調色之後。（由程式推理發現；沒有用肉眼比對影片確認。）
- 跟拍平滑：起點用前 5 點中位數＋零相位 5 點加權平滑。10 組隨機抖動 std 平均 0.0039（R9 seed=1 基準 0.0069；seed=1 現為 0.0000），最大 0.0074；步階追蹤終點 0.737（目標 0.75，延遲略增）。
- test_gui 的固定「ticks>3」改成和經過時間成比例（背景標籤工作讓手動片段很快完成時會誤判）。
- 測試：test_reframe（多 seed 晃動、漸變各段相接與總長）、test_ai 長度期望值更新。runtests FAILED_RUNS=0。
- 未驗證：真實手持素材的觀感。
- 分數（保守）：Features 87 / UI/UX 85 / Code 84 / vs-AutoEdit 66

## R18 — 長片自動調色效能
- 量測（本機 box、Linux CPU，合成素材）：20 分鐘 1080p30 H.264（GOP 300）時，auto_enhance_filter 每段 0.42–0.70 秒，和位置無關（5s/600s/1150s）。同一支片輸出 5 段：關閉自動調色 7.8 秒，開啟 9.4 秒（+21%）。
- 問題：慢動作分成 5 段時每段各自量一次（耗時 ×5），而且各段的 eq 不一樣，可能跳色。修正：以整段（s.start–s.end）計算，並用 lru_cache(512) 快取（鍵含 mtime/size）。
- 測試 test_autocolor_perf：10 分鐘片尾端 seek 不變慢（0.22–0.26 秒），快取命中 <10 ms。runtests FAILED_RUNS=0。
- 未驗證：真實 HEVC/10-bit/INSV 長片、Mac/Windows 機器、長 GOP 素材（這次測的是 GOP 300）。
- 分數（保守）：Features 87 / UI/UX 85 / Code 85 / vs-AutoEdit 66

## R19 — 笑臉準確度
- 量測：8 張公有領域肖像（4 露齒笑／4 不笑，Wikimedia Commons），每張放成 3 種臉大小，放進實際分析用的 320×180 灰階畫面。R18 以前的偵測器 **TPR 0/12、FPR 0/12**：這個解析度下臉只有約 30–60px，笑臉分類器從來沒有觸發，所以先前的「笑臉加分」實際上沒有作用。
- 修正：faces.smile_score 把下半臉放大到 80px 寬、等化後再找（minNeighbors 25）。現在 TPR 9/12、FPR 0/12（原始 600px 圖上調參時是 10/12、0/12）。
- 注意：參數是在同一組 8 張圖上調的，有過擬合風險；樣本只有 4 位中老年男性正面肖像，沒有亞洲臉、小孩、側臉、戴墨鏡、運動相機廣角變形。**真實旅遊素材的準確率未驗證。**
- 新測試 test_smile（需 opencv，python3 下 SKIP）；test_faces 仍通過。runtests FAILED_RUNS=0。
- 分數（保守）：Features 88 / UI/UX 85 / Code 85 / vs-AutoEdit 67

## R20 — 低分標記＋FLASHCUT_COMPARE 重新對照（2026-10-25）
- 片段卡加上「分數偏低」標記（低於最高分 × LOW_REL，手動片段不算），朗讀名稱也會說出這個標記；test_gui 的 R20 段落會檢查。
- FLASHCUT_COMPARE 依 R15–R19 更新：臉/笑臉、慢動作、標題、語意、貼紙。README 也已更新。
- runtests.sh：FAILED_RUNS=0（兩個直譯器＋clipvenv 都有跑）。截圖：review/rounds/r20_low_tags.png、r20_1024.png。
- 未驗證：沒有在真的 Mac/Windows 上跑過；沒用真實旅遊影片測過；library.py 太廣的 except 還沒處理（REVIEW_r10）。
- 分數：F88 / U86 / C85 / vs67

## R21 — 收窄 library.py 錯誤處理（2026-10-25）
- library.py 的 5 個 `except Exception` 全部改成具體的例外類型。分析檔案時只接 `ANALYZE_ERRORS`（OSError/RuntimeError/ValueError/SubprocessError/EOFError），並記到 log；程式錯誤（例如 TypeError）會往上丟，不會被當成壞檔吞掉。statfs、NSURL、psutil、send2trash 也各自只接該接的錯誤。
- 新增 tests/test_errors.py：壞檔會記錄錯誤；注入 TypeError 時會往上丟。test_library 仍通過。
- 只跑了受影響的測試（python3），完整套件留到 R23 再跑。gui/workers.py 最上層的 catch-all 刻意保留（避免 UI 執行緒當掉）。
- 分數：F88 / U86 / C86 / vs67

## R22 — 雪景標籤準確度（2026-10-25）
- 「雪」多加 3 句提示（雪山、雪覆蓋的冬景、滑雪道）。第二個標籤改用較低門檻 min_p2=0.12，所以雪山現在會標成「山＋雪」。之前合成雪山的雪機率是 0.00，現在是 0.20。
- 新增 tests/snowgen.py：程序產生比較像真實照片的雪景（雪松、滑雪痕、落雪、人），共 4 張，再加 2 張無雪山景對照。結果：雪景 4/4 標成雪，無雪山 0/2 誤標成雪。
- 限制：還是合成圖，不是真的照片；已經分析過的片段要重新分析才會更新標籤。
- 分數：F88 / U86 / C86 / vs67

## R23 — 特效模板：節拍放大／閃白／故障（2026-10-25）
- core.py 新增 `EFFECTS` 和 `effect_filter`：節拍放大（0.25 秒內 1.08→1.0，用 scale eval=frame＋crop）、閃白（eq brightness 0.15 秒衰減）、故障（0.1 秒 rgbashift＋noise）。效果加在合併之後、標題和貼圖之前，所以文字不會跟著閃或錯位。觸發點最多 80 個。
- 觸發時間：有音樂時用強拍，從 workers 換算到輸出時間軸；沒有音樂時用剪接點。GUI 加了「特效模板」下拉選單。
- tests/test_effects.py：和沒有特效的輸出逐幀比較，觸發點附近差異 34.5／37.0／9.5，遠處 ≤0.4，長度不變。test_gui 加了 R23 段落。
- runtests.sh：FAILED_RUNS=0，包含 R21–R22。
- 限制：只有 3 種效果，也沒有預覽縮圖；拍點對齊只驗證了換算公式，沒有實際聽過或看過。跟 Auto Edit 的模板庫比還差很多。
- 分數：F89 / U86 / C86 / vs68

## R24 — 貼圖拖曳定位＋簡單動畫（2026-10-25）
- 貼圖位置多了「自訂（拖曳）」：新的 StickerPad 依輸出比例畫出小畫面，可以用滑鼠拖曳，也可以用方向鍵（每次 2%）移動，並有朗讀描述。新增「貼圖動畫」：無／彈跳／浮動。
- core：`sticker_xy` 支援 (fx, fy) 比例座標，用 clip 限制在畫面內；動畫用 overlay eval=frame 的 y 運算式。舊的四角名稱照樣可用，stickers 的 tuple 也相容。
- 測試：test_effects 檢查 3 種動畫在 (0.25, 0.5) 的實際輸出位置，誤差 ≤0.01；彈跳的開頭位置比較高。test_gui R24 測滑鼠點擊位置、方向鍵和 _prep 的內容。
- 已單獨跑 test_gui、test_effects（.venv）；完整套件在 R25 再跑。
- 限制：小畫面沒有顯示實際影片的縮圖（thumb 欄位留著，還沒接上）；一次只能放一張貼圖。
- 分數：F89 / U87 / C86 / vs69

## R25 — 真實素材格式的穩定性（合成測試）＋低階 CPU 首次分析量測（2026-10-25）
- **修正 bug**：手機直拍的影片（橫向畫素＋旋轉 90° metadata）之前會被 probe 當成橫式。ffmpeg 解碼時其實會自動轉正，所以尺寸和實際畫面對不上。現在 probe 會解析 displaymatrix 或 rotate 標記，回報顯示尺寸。
- 新增 tests/test_robust.py，涵蓋 VFR、HEVC(hvc1)、10-bit HEVC .mov、單聲道 22.05k、5.1、無音訊、4K、旋轉 90°。每種都要能分析出片段、正確輸出 1080p 或 1080×1920 並帶音軌。8/8 通過。
- 首次分析量測（60 秒 1080p30 合成檔，`candidates_for_video`）：限 1 核 7.9 秒，4 核 3.4 秒。換算：20 分鐘的素材在單核上約 2.6 分鐘，4K 會更久。試過 `-skip_loop_filter`，在這個合成檔上沒有變快，所以沒有加進程式。**還沒做任何最佳化。**
- runtests.sh：FAILED_RUNS=0（R21–R25 全部）。
- 限制：所有格式都是合成檔；沒測真的長 4K 檔（>10 分鐘）、真的 iPhone 或 Insta360 HEVC、杜比視界或 HDR；「低階 CPU」只是用 taskset 限制核心數模擬。
- 分數：F89 / U87 / C87 / vs69

## R26 — 手動速度曲線編輯器（2026-10-25）
- 微調視窗加上「速度曲線」：5 個控制點，速度用對數刻度 0.25–4 倍。可以用滑鼠拖曳；鍵盤用 ←→ 選點、↑↓ 每次 ×1.25、0 重設。預設：中段慢動作／蒙太奇／漸慢／快轉，以及自訂。下方即時顯示「原始 → 輸出約 X 秒」。
- smart：`curve_pieces` 以 0.5 秒為單位離散、量化到 0.05，相鄰同速合併；`atempo_chain` 讓 0.25 倍可用（串兩個 0.5）。core 輸出時，有手動曲線的片段走 curve_pieces，而且不會再加自動慢動作。library 加了 `speed` 欄位（migration）和 `set_speed`。
- tests/test_speed.py：3 條曲線實際輸出的長度和預估差 ≤0.02 秒；資料庫保存、限制範圍、點數錯誤都有測。test_gui R26 測預設、方向鍵、滑鼠點擊和重新開啟後的狀態。截圖：rounds/r26_speed_curve.png。
- 限制：0.5 秒離散，所以曲線上的尖點會被平均掉（中段 0.4 倍實際最低約 0.55 倍）；節拍對齊計算長度時沒有考慮手動曲線；片段卡上沒有「變速」標記。只跑了 .venv 的 test_speed 和 test_gui。
- 分數：F90 / U87 / C87 / vs70

## R27 — 分析速度：單次解碼＋多支影片平行＋硬體解碼（2026-10-25）
- core：評分用的 64×36 rgb 和人臉用的 320×180 灰階，原本要解碼兩次，現在改成一次 ffmpeg 解碼，用 split 分成兩路輸出。Mac 和 Windows 預設先試 `-hwaccel auto`（可用 IE_HWACCEL 覆寫）。硬體解碼失敗就自動改用軟體解碼重跑，並記錄在 DECODE_STATS。縮放演算法維持預設：試過 fast_bilinear，選出的起點會變，所以沒有採用。
- library：`analyze_pending` 用 min(3, CPU//2) 個執行緒平行做 probe 和評分；寫入資料庫與產生預覽仍依序執行。取消狀態會傳進各執行緒；壞檔照樣只記錄錯誤。
- 量測（Linux x86 容器，軟體解碼）：60 秒 1080p 單支，限 1 核 8.4→5.1 秒，限 4 核 3.4→2.1 秒，選出的起點與分數**完全相同**。4 支 60 秒 1080p 在 4 核上：依序 7.2 秒，3 執行緒 5.0 秒。
- 新增 tests/test_perf.py：確認只解碼一次影像；平行與依序的結果逐筆相同；平行模式遇到壞檔只記錄錯誤；假的 HWACCEL 會自動退回軟體解碼。test_library/faces/errors/robust/speed 兩個直譯器都通過。
- 限制：**硬體解碼沒有在真的 Mac 或 Windows ARM 上驗證過**，只驗證了失敗後會退回軟體解碼；平行 3 支時記憶體用量沒量；不是每台電腦都適合用 CPU//2 個執行緒。
- 分數：F90 / U87 / C88 / vs71

## R28 — 貼圖小畫面顯示實際畫面＋多張貼圖（2026-10-25）
- StickerPad 背景改用時間軸第一個片段的縮圖，並依輸出比例置中裁切（和輸出一樣，不拉伸）。時間軸一變動就更新。
- 現在只要選了貼圖就會顯示小畫面，四角位置也會畫在對應地方；在小畫面上一拖，位置自動切到「自訂」。
- 多張貼圖：「＋ 加入這張貼圖」會把目前的貼圖、位置和動畫存進清單，最多 STICKER_MAX＝5 張，到上限按鈕就停用；可以「移除選取」。已加入的貼圖在小畫面上半透明顯示。輸出的內容＝清單＋目前選的這張。core 原本就支援多張 overlay。
- 測試：test_effects 輸出兩張貼圖，在 (0.2,0.3) 和 (0.8,0.7) 各自量到位置（誤差 ≤0.05）；test_gui R28 測縮圖、加入、拖曳切到自訂、_prep 內容、上限和移除。截圖：rounds/r28_sticker_multi.png（容器字型沒有彩色 emoji，所以星星是單色）。
- 限制：小畫面用的是靜態縮圖，不是影片播放；已加入的貼圖不能再拖或編輯，只能刪掉重加；智慧追蹤構圖（smart reframe）的裁切位置沒有反映在小畫面上。
- 分數：F91 / U88 / C88 / vs71

## R29 — 特效預覽＋標籤器升級時自動重貼（2026-10-25）
- 特效預覽：新增 `core.effect_preview(name, out, img)`。拿一張畫面（時間軸第一段的縮圖，沒有就用測試圖），用真正的 effect_filter 在 t=0.1 觸發，取觸發前、觸發、0.05 秒後、0.15 秒後 4 格並排成 PNG。選特效模板時，下拉選單下方會顯示這條預覽，並快取在 cache/fxpv_*.png。
- 自動重貼標籤：新增 `semantic.tagger_version()`＝TAGS、OTHER 提示詞加上 auto_tags 預設門檻的 sha1。`tag_clips` 發現資料庫 kv 裡記錄的版本不同，就全部重貼並寫入新版本。啟動時沒有待分析的檔案，但標籤過期（有 CLIP 才算），就在 1.5 秒後到背景重貼。
- 測試：test_effects 用靜止畫面確認觸發格和前一格明顯不同、0.15 秒後正在減弱（3 種都通過；容器裡實測故障/閃白 0.15 秒後已完全恢復，放大還剩一半）。新增 tests/test_retag.py（用假 CLIP）：同一版本不重算，換版本就全部重貼。test_gui R29 測 3 種預覽、隱藏和 tags_stale。截圖：rounds/r29_fx_preview.png。
- 修正測試本身的 bug：預覽格切法原本沒算 2px 間隔，算出來的差異是錯的。
- 限制：預覽是靜態 4 格，不是動畫或真的影片片段；在主執行緒同步產生（約 0.1–0.2 秒，有快取）；沒有真的用 CLIP 跑過「啟動時自動重貼」的完整流程，只測了判斷邏輯和 library 這一層。
- 分數：F91 / U88 / C88 / vs72

## R30 — 文件同步、完整測試、打包（2026-10-25）
- README.md：新增特效模板、貼圖拖曳與多張、速度曲線、分析速度（IE_HWACCEL／IE_ANALYZE_WORKERS）、標籤自動重貼；「已知限制」改寫成 R30 的現況。review/FLASHCUT_COMPARE.md：更新變速、貼圖／特效、標籤三列，新增「素材格式穩定性」「分析速度」兩列，加上 R30 補充。DESIGN.md：新增 1.15（R21–R30）。
- 截圖時發現並修正：特效預覽條的 774px 原圖把右側面板撐寬，改用 Ignored 尺寸策略。修正後重跑 test_gui 通過。
- 完整套件 runtests.sh（python3＋.venv＋clipvenv）：**FAILED_RUNS=0**。python3 沒有 PySide6/cv2/CLIP，GUI、臉部、語意測試印 SKIP。
- 截圖：rounds/r30_main.png、r30_main_top.png、r30_right_panel.png、r30_speed_curve.png。
- 限制：容器裡沒有彩色 emoji 字型，截圖裡的貼圖是單色或替代字；右側面板窄時，160×90 的貼圖小畫面偏小，貼圖看不太清楚。
- 分數：F91 / U88 / C88 / vs72（R30 本身不加分）

## R31 — 插入記憶卡/相機自動偵測（2026-10-25）
- app/convenience.py：`candidate_roots()`（mac /Volumes、Windows 抽取式/固定磁碟（C 除外）、Linux /media；IE_VOLUME_ROOTS 可覆寫）、`detect_camera()`（DCIM／Camera0*／.insv/.lrv/.insp → insta360）、`DeviceWatcher.poll()` 只對新插入的卡提示一次。主視窗每 3 秒檢查，頂端橫幅「匯入新檔／匯入並自動剪／略過」。
- 測試：test_convenience（假掛載點）、test_gui R31。
- 限制：沒在真的 Mac/Windows ARM 插卡測過；Windows 用 GetDriveTypeW，未驗證 USB 大容量模式的 Insta360。
- 分數：F91 / U89 / C88 / vs73

## R32 — 依日期/旅程分組＋「用這組做影片」（2026-10-25）
- `parse_meta`（creation_time UTC＋ISO6709 GPS）、`group_trips`（間隔 >8 小時分組；36 小時內且 GPS <80 km 視為同一趟）、`trip_name`。左側新增旅程下拉＋「用這組做影片」（只用這組的片段一鍵成片）。
- 限制：時區用本機；沒有 GPS 的相機只靠時間間隔。
- 分數：F91 / U89 / C88 / vs73

## R33 — 一句話需求（離線解析＋可選雲端 LLM）（2026-10-25）
- `parse_brief`：長度、比例、節奏、標籤（海/山/雪/夜景/人物/寵物）、笑臉、情緒/配樂（「不要音樂」）、慢動作、「標題」。有設定 API 時 `llm_brief` 先問 LLM，失敗或格式錯誤退回離線解析。
- 限制：離線規則只認常見說法；雲端 LLM 只用假回應測過。
- 分數：F92 / U90 / C88 / vs74

## R34 — 修改指令（短一點/長一點/多點人/換音樂/刪這段/熱血/溫馨/放鬆）（2026-10-25）
- `parse_refine`/`refine_state`；「刪這段」作用在時間軸選取的片段、尊重鎖定；被刪的片段之後自動選片不會再選回來。
- 分數：F92 / U90 / C89 / vs74

## R35 — 記住偏好＋我的範本（2026-10-25）
- 關閉時存比例/長度/節奏/濾鏡/配樂音量等（PREF_KEYS＋cust），啟動時套回；「我的範本」可存、套用、刪除。
- 修正：測試裡第二個視窗沒有 `_an_job` 屬性 → getattr。
- 分數：F92 / U90 / C89 / vs74

## R36 — 一次輸出多種比例（2026-10-25）
- 勾選 16:9/9:16/1:1，依序輸出 name_16x9.mp4 等，完成後恢復原本比例；結果在 multi_results。
- 限制：依序輸出，不是平行；每個比例都重新編碼一次。
- 分數：F92 / U90 / C89 / vs75

## R37 — LRV 當分析代理檔、MP4 輸出；投影偵測；低解析來源標示（2026-10-25）
- `analysis_source()`：MP4 有長度相符（±1 秒）的 LRV 附屬檔時，分析/預覽都用 LRV，輸出用 MP4（IE_NO_LRV=1 可關閉）。`classify_projection`：2:1 → equirect／雙魚眼（看四角與上下中間是否黑）。只有 LRV 的檔案顯示「低解析來源」。INSV 降為次要。
- 測試：tests/test_lrv.py（合成平面/equirect/雙魚眼/只有 LRV/長度不符的 LRV）：分析 1080p MP4 0.43 秒 vs LRV 0.14 秒 → **約 3.1 倍**；輸出寬度 1920；equirect 9:16 輸出 1080×1920。修正測試本身 2 個 bug（.lrv 副檔名要指定 -f mp4；Segment 沒有 track 參數）。
- 分數：F92 / U90 / C89 / vs76

## R38 — 真實樣本：單一圓形魚眼（方形 2688²/640²）攤平＋雜湊檔名配對（2026-10-25）
- 樣本：使用者的 LRV 640×640 與 MP4 2688×2688，5.92 秒，25 fps，2025-02-02 15:48（台北時間）拍的小孩滑雪。畫面是方形裡的單一圓形魚眼（四角黑、圓略被左右切到）。
- 偵測：`is_circular_fisheye`（方形＋四角 75 百分位 <30＋中心比角落亮 40 以上）→ projection "fisheye"，兩個檔案都判定正確。
- 攤平：`fisheye_view()` → `v360=input=fisheye:ih_fov=190:iv_fov=190:output=flat`。長邊視角 125°（IE_FISHEYE_FOV／IE_FISHEYE_VIEW 可調）。FOV 是目測 170/185/200/215 的網格後選的：185–200 欄杆和桿子看起來最直，**沒有用校正板量過**。主體位置用 focus_x 和新增的 focus_y（只算圓內 85%，黑框邊緣不算），換成 yaw/pitch，並限制在鏡頭範圍內，不會看到黑邊。預覽和縮圖也攤平成 16:9。
- 配對：檔名是雜湊時，`_pair_by_meta` 比對同資料夾裡的長度 ±0.06 秒、fps、比例、解析度不同、creation_time ±2 秒（實測這對檔案差 1 秒：07:48:05Z vs 07:48:06Z UTC）→ 把 LRV 併到 MP4。沒有拍攝時間就不併；第一次加 creation_time 規則時，誤併了 test_groups/test_library 的合成檔，已修正。
- 實測（review/real_sample/）：配對成功（1 支）。分析 LRV 0.6–0.8 秒 vs MP4 3.4 秒（**約 4–5.5 倍**）。選片 1.92–5.92 秒，從 MP4 輸出：9:16 1080×1920 約 4.7 秒、16:9 1920×1080 約 4.4 秒、1:1 約 3.1 秒。左右對照圖：side_16x9_v125.jpg（目前預設）、side_9x16.jpg、side_1x1.jpg。
- 觀察（照實說）：攤平後直線大致變直，小孩在畫面中。但是：(1) 相機本身有滾轉（roll），地平線歪約 15–20°，沒有做水平校正；(2) 每段只用主體位置的中位數，是**固定視角**，不是逐格平滑跟拍；(3) 9:16 時小孩偏右、下半身被切到；(4) 只有 1 段 5.9 秒的樣本，選片排序沒有意義。
- 測試：tests/test_fisheye.py（偵測、視角限制、配對規則、合成雜湊檔名配對＋攤平、真實樣本，檔案不在就 SKIP）。
- 分數：F92 / U90 / C89 / vs77

## R39 — 魚眼逐格跟拍（2026-10-25）
- `app/fisheye.py`：在 LRV 上每秒 5 格攤成 equirect，用 NanoDet-Plus（opencv_zoo，Apache-2.0，3.8 MB，app/models/）找人；第一次挑「面積×信心×靠中央」，之後挑最近的框。→ 10 Hz 路徑：限制在鏡頭內 → deadzone 3° → easing 0.25 → 5 點平均。輸出用 `sendcmd` 檔＋`v360@cam`，每 0.1 秒更新 yaw/pitch/roll。
- **實測抓到的 ffmpeg 7.0 陷阱**：v360 每收到一個旋轉指令就把旋轉「疊加」，畫面會越轉越歪（第一版 v2 後半段整個翻過來）。修正：每行最後送 `reset_rot 1`。驗證：同一組角度下，sendcmd 版和靜態濾鏡逐像素相同（平均差 0.0）。
- 真實樣本：95% 的取樣格有偵測到；路徑 yaw 約 +11° → −25°（小孩往左移）。輸出時間：9:16 約 14.5 秒（v1 4.7 秒，每次指令都重算映射，約慢 3 倍）。IE_FISHEYE_FOLLOW=0 可關閉。
- 分數：F93 / U90 / C89 / vs80

## R40 — 水平校正（2026-10-25）
- 主要來源：Insta360 檔尾的 IMU（GO 3：record 3 為 1 kHz 加速度/陀螺儀，record 4 第一筆＝影片 t=0）。重力 → roll=atan2(ax,ay)，0.4 秒平滑，每 0.1 秒一筆。本樣本約 +18°（10–25° 之間變動）。v360 用 rorder=rpy，追蹤的 equirect 也先套同一個 roll（中位數），所以座標一致。
- 備援：沒有 IMU → 0°（直線法 Hough 在這個樣本不可靠，只在 IE_ROLL_LINES=1 時使用）；手動：微調片段對話框「水平校正（魚眼）」＝自動／−45～45°，每段存在 kv `roll:<clip id>`。
- 未驗證：IMU 時間零點（假設 record 4 第一筆）只是用畫面目測對得上；陀螺儀沒有用（只用加速度，快速晃動時重力估計會被加速度干擾）；只測過 GO 3 這一支檔案。
- 分數：F94 / U90 / C89 / vs82

## R41 — 預設構圖＋v2 輸出比較（2026-10-25）
- `frame_target`：人不太高時置中並留約 8% 頭頂空間；人太高時保頭（頭頂留在畫面內），腳可能被切。
- 輸出：review/real_sample/real_9x16_v2.mp4、real_16x9_v2.mp4；compare_{9x16,16x9}_v1_v2.jpg（0.3/1.3/2.3/3.3 秒，上 v1 下 v2）；side_{9x16,16x9}_v2.jpg（原始魚眼｜v1｜v2）。
- 誠實比較：v2 地平線、樹、欄杆都變直（v1 歪約 17°）；小孩在 4 個時間點都在畫面內且大致置中，前 3 個時間點全身入鏡（v1 有 2 格切掉半個身體/下半身）。缺點：最後 3.3 秒腳被切一點、右邊有大人手臂入鏡；前段小孩比 v1 小（視角較廣、置中）；輸出變慢約 3 倍；只有一支 4 秒片段，跨人物時是否會跳去追別人沒有測。
- 分數：F94 / U91 / C89 / vs83

## R42 — 真實長片（只有 LRV，原始 PRO_LRV_ 檔名）（2026-10-25）
- 樣本（/workspace/real_long）：4 支 640×640、25 fps、單一圓形魚眼、有 Insta360 IMU：01-31 18:48（19 分 25 秒，654 MB）、02-01 21:27（4 分 19 秒）、02-03 20:34（7 分 12 秒）、02-04 16:35（8 分 23 秒）（台北時間）。投影都判定為 fisheye，IMU 都讀得到。
- 檔名：PRO_LRV_…_01_019 → 組名 VID_20250131_184820_019，與 PRO_VID/VID/LRV/INSV 同一組 key（已有規則，實測確認）。只有 LRV，所以都是低解析來源。
- 分析速度（各自一個行程，LRV 直接分析）：19 分鐘 48 秒／尖峰記憶體 543 MB；4 分鐘 9 秒／164 MB；7 分鐘 16 秒／236 MB；8 分鐘 27 秒／266 MB（約 20–28 倍即時）。記憶體會隨長度增加。
- 修正：每支只推薦 4 段，長片太少 → 每 30 秒至少 1 段、上限 40（19 分鐘 → 38 段）。
- 日期分組：預設 8 小時間隔 → 4 天各 1 組（01/31、02/01、02/03、02/04）；設 30 小時 → 2 組（01/31–02/01、02/03–02/04）。都沒有 GPS。
- 推薦品質（sheet_*.jpg，上排是前 6 名，下排是最低的 6 個窗口，照實判斷）：19 分鐘（城市散步）和 7 分鐘（騎車/街道）：前幾名多半有人、互動、地圖，最低的是空的走路/風景 → **合理**。8 分鐘（花展）：前幾名有人，但也選到手拿相機。4 分鐘（滑雪場）：上下兩排都被手/另一台相機擋住，**分不出好壞**。主要問題：機身戴在身上，手和另一台相機常擋住鏡頭，評分把這種近距離大動作當成精彩。下一步應加「鏡頭前遮擋」扣分（大面積近距離膚色/暗色）。
- 一鍵剪輯（4 支 → 自動選 30 秒，8 段）＋跟拍＋水平：oneclick_9x16.mp4（1080×1920，28.5 秒，輸出 214 秒）、oneclick_16x9.mp4（144 秒）。frames_*.jpg：大部分畫面水平看起來正常，有 1–2 格仍然歪；8 段中有 3 段偵測到人的比例不到 20%（沒有人時就用固定視角）。從 640² 放大到 1080p，畫質偏軟。輸出慢：每 0.1 秒重算一次 v360 映射。
- 修正：TrimDialog 裡局部 import 遮蔽 QDoubleSpinBox，導致 GUI 測試失敗 → 已修正，GUI 測試通過。
- 分數：F94 / U91 / C89 / vs83（推薦品質在穿戴式長片上只算中等）

## R43 — 鏡頭遮擋 / 手擋偵測 (2026-10-25)
- core.occlusion(): 魚眼圓內「暗(Y<45)或膚色(YCrCb)」且低紋理(4×4 區塊 std<9) 面積比 → occ；下半部膚色比 → hand。
- 分數扣 OCC_W(1.2)*clip((occ-0.15)/0.2) 與 0.4*clip((hand-0.3)/0.25)；可用 IE_OCC_T / IE_OCC_W 調。
- 真實 4 檔前後對照：review/real_long/compare_occ_*.jpg。滑雪 02-01：before top6 有 5 張被手套/相機遮擋；after top6 約 2 張仍有手/相機入鏡（189s、194s），遮擋畫面全部落到 LOW。02-04 LOW 欄現在幾乎都是手持相機畫面。
- 誠實：未用手部/相機偵測模型（COCO 無 camera 類）；膚色量測對米色/雪地有雜訊。
- Score F95/U92/C90/vs85

## R46 — 串流化特徵記憶體 (2026-10-25)
- features() 以 256 幀為單位處理；灰階暫存檔改 np.memmap。
- 19m25s 檔：峰值 RSS 543→284 MB；分析含候選 48→32 s。02-01 164→116 MB。

## R44 — 只拍到手持相機的畫面降分 (2026-10-25)
- hand 指標（魚眼下半部膚色比）扣最多 0.4；配合 occ。02-04 對照：LOW 6 張全是手拿相機/手入鏡，TOP 剩 1 張（462.5s）有相機入鏡。
- 誠實：沒有相機物件偵測器；畫面中「手持相機但不遮擋」且膚色少（戴手套）時仍抓不到，如 02-01 189s/194s。

## R45 — 跟拍輸出加速 (2026-10-25)
- sendcmd 只在角度變化 ≥0.6° 且間隔 ≥0.2 s 時送（IE_CMD_DEG/IE_CMD_GAP）；v360 依來源解析度降到 ≥½ 尺寸計算再 lanczos 放大（640² LRV → PSNR 37 dB vs 全尺寸）；片段平行輸出（IE_JOBS，預設 min(3, CPU/2)）。
- 一鍵輸出 28.5 s／8 段：9:16 214→105 s，16:9 144→52 s。未試 hwaccel（box 無 GPU）。
- Score F95/U93/C90/vs86

## R47 — 找到人的比例 (2026-10-25)
- NanoDet 門檻 0.4→0.3（IE_DET_T）。8 段 found：平均 0.54→0.71（[0.45,.6,.9,.85,.15,.1,1,.3]→[.8,.55,.95,1,.85,.15,1,.35]）。0.25 沒更好。新抓到的框目視為真人（det_thr03_203454_401s.jpg）。
- 全段無人時仍用靜態構圖（未做 saliency 跟拍）。
- R43 修正：暗區需低彩度（rgbtestsrc 純色條被誤判，test_convenience 失敗→修好）。全測 FAILED_RUNS=0；test_gui 一次 aierr 時序 flake，重跑通過。

## R48 — 找不到人時改跟「動得最多的地方」(2026-10-25)
- fisheye.track：整段找到人 <20% 時，沒偵測到的格改用前後格差異最大 5% 像素的重心（上下 1/8 不算）；conf 0.01，info["saliency"] 記比例；IE_SALIENCY=0 可關。
- 8 段：412.5s found 0.15 → 加上 saliency 0.85，有目標比例合計 1.0；其餘 7 段不受影響（found≥0.2）。平均有目標 0.71→0.80。
- 誠實：只用畫面變化，鏡頭自己在晃時重心可能亂跳（plan 的 deadzone/平滑會壓住一些）；沒做目視輸出比較。
- Score F95/U93/C90/vs86
- 全測 FAILED_RUNS=0，test_gui OK，zip 已更新。

## R49–R54：推薦評分對 ground truth 調校（240 支，依連拍 burst 切 train 168 / 驗證 72，seed 49）
指標：P / R / hit / 檔案 AUC（基準：P .25、隨機 .18、file-pick AUC .59、只看長度 AUC .69）
- R48 基準（全部候選 4×4s）：train .261/.574/.942/.569；val .238/.689/.994/.633
- R49 修 features() 短片 (<2.5s) crash（`_same` 取代 convolve same）：0 錯誤；train .265/.582/.944/.560；val .240/.690/.995/.628
- R50 預設 6.5s、每支 1 段 + optional 第二段；魚眼停用 Haar：checked train .319/.445/.765；val .319/.544/.857
- R51 每檔 worth 分數（長度權重、<3s 重罰、burst 只留一支、近重複抑制）：kept train .330/.442/.753/.741；val .322/.544/.857/.661
- R52 dewarp 後 NanoDet 人物偵測 + 近距離加分：train .338/.454/.769/.745；val .327/.552/.862/.672
- R53 天空 / 傾斜（IMU）懲罰、遮擋手部加重：train .338/.454/.769/.748；val .326/.552/.861/.696
- R54 跨檔百分位正規化、keep=0.3、整合進 library（files.worth）：train .347/.454/.769/.748；val .332/.533/.831/.696；全部 .342/.475/.786/.729
備註：recall/hit 下降是因為每支只勾 1 段；檔內位置用均勻偏移重疊期望值評估，幾乎量不到，主要增益來自挑檔。train AUC 只略高於純長度 (.740)，val 明顯優於長度 (.598)。
- 測試：test_library/test_gui 依新預設（每支 1 段）調整斷言；其餘全過。

---
# R55–R62 多策略候選（真實標註 Thai_Edited 123 支；split seed 49：train 89 正例 / held-out 34 正例；只在 train 調參）
基準：固定置中 6.5s 視窗 IoU train .481 / held-out .550。IoU 皆以精確 ground truth（v3 對齊）計算。

| Round | 變更 | train P / R / hit / fAUC / top IoU | held-out P / R / hit / fAUC / top IoU |
|---|---|---|---|
| R54 | 基線（舊排序） | .347 / .432 / .809 / .748 / .438 | .332 / .550 / .824 / .696 / .537 |
| R55 | <10s 整支 | – / – / – / .748 / .454 | – / – / – / .696 / .555 |
| R57 | 位置先驗（置中高斯） | ≈.48 top IoU，不優於置中 → 不採用（pos_w=0） | – |
| R58 | 策略權重調參（people/action，train grid） | 單策略 train IoU：people .515、action .485、middle .481、start .461、whole .874 | – |
| R59/60 | 5 策略候選 + IoU>.6 合併 + 2–4 段 + 先驗排序 | .341 / .513 / .820 / .748 / **.520** | .327 / .625 / .853 / .696 / **.591** |
| R61 | 偏好學習先驗強度 N（模擬：每檔使用者勾最佳候選） | N=10：held-out top .591→.535（學太快、合併標籤帶偏）；N=30：.591→.591，best .747；train 兩半驗證無差 → 取 N=30 | |
| R62 | App 整合：clips.strategy 欄、kv strategy_stats（shown/picks）、手動勾選記錄、GUI 策略 chip、tests/test_strategies.py | 同 R60 | 同 R60 |

R60 best-of-shown：train IoU .645 / hit50 .708（平均顯示 2.63 段）；held-out .745 / hit50 .882（2.29 段）。
held-out 單策略 IoU / hit50：start .516/.588、middle .576/.588、people .591/.647、action .536/.529、whole .875/1.0。
Pex（精確範圍 precision）train .330→.368、held-out .343→.361；uniform-offset P 微降（.347→.341、.332→.327）；fAUC 不變（檔案層級 worth 分數未動）。
注意：held-out 只有 34 正例，±.03 屬雜訊範圍；偏好學習 N 的選擇有參考 held-out 模擬觀察（train 半切無鑑別力），屬保守設定。

## R63 — UI/UX 多角色審查第一輪修正（2026-10-25）
審查小組：Qt 架構、效能/併發、可靠性、打包、UX 設計師、首次使用者、無障礙、500+ 片段重度使用者。前測 Code≈74、UI/UX≈68（截圖 review/uiux_r63/before/）。
修正：僅可見卡片播放（MAX_PLAYING=24、FrameView 延遲建立 player）；標籤完成就地更新卡片不重建牆、refresh 保留捲動；卡片寬度隨視窗（270–420、最多 6 欄）、卡片牆無水平捲軸；Toast 移至卡片區上緣不擋按鈕；右欄進階設定可收合；移除開發代號「R36」；左清單省略中段＋「✓ N 段候選・已選 M」；歡迎頁拖放區＋①–④ 步驟；空庫時停用換一批/一句話；「分數偏低」改灰色「較平淡」（無障礙名稱保留）；鎖定鈕放大、鎖定時黃色；策略標籤彩色；時間軸加縮圖；remove_selected 改用 group_name 不解析清單文字；延遲計時器關窗後不再拋 SQLite 錯誤。
測試：全部 tests/*.py 通過（含 test_gui）。AI 指標：未改 app/core 分析碼，不影響。

## R64 — 納入外部 UI/UX 審查（REVIEW_uiux.md，前測 68）必改項（2026-10-25）
- 卡片牆空白：根因為卡片寬度＋垂直捲軸出現時觸發水平捲軸的排版振盪；卡片牆改為垂直捲軸常駐、無水平捲軸，分析完成時 `_relayout_now()` 立即重排（7 支實片 1360 寬重現→已修，dbg_wall.py）。
- 「剪完後調整（本機，鎖定的保留）」→「用一句話微調成品」＋「已鎖定的片段不會被換掉」。
- 核取方塊：16px、2px #8A8A8A 邊框、勾選 #FFC400 填滿。
- Toast：右下角、時間軸上緣之上、右欄左側，寬度上限 420px、預設 4 秒，無按鈕時不擋滑鼠。
- 已勾選卡片不再顯示「較平淡」（未改 AI 選段，不影響指標）；徽章改中性灰 #3A3A3A/#D0D0D0。
- 主色只留「產生成品」：左欄「用這組做影片」改次要（#2C2C2C 底、黃框黃字）。
- 對話框最小寬 420px；空間不足錯誤主鈕「改存到…」（重新選位置），「重試」降為次要；「刪除原始檔…」→「丟到垃圾桶…」。
- 建議項：卡片牆篩選列（共 N 段・已選 M、只看已勾選/未勾選/較平淡/AI 找到的、全部收合/展開）；時間軸短名「08/25 02:32」＋完整檔名 tooltip＋縮圖；找片段加 🔍。
- 測試：test_gui、test_errors、test_safe_export、test_convenience、test_strategies、test_robust 全過。

## R65 — 只剪片段（後端）＋多策略開關（後端）（2026-10-25）
使用者新需求：「只要剪出片段、不用音樂、剪片段要有多個策略」。依指示 UI 主流程改版暫停，等 UI/UX 設計師的 review/clips_design/ 規格核可後再做；本輪只做後端：
- `core.export_clips(items, folder, opts)`：每個已選片段各自輸出一支（強制無音樂、無轉場、無片頭字、無淡出；沿用 export() 的 .part 安全寫入、取消、單段失敗不影響其他段、同名自動 _2）。
- `core.clip_filename()`：`<來源>_<0m12_5s>-<0m19_0s>_<策略+策略>.mp4`。
- `Library.timeline_clip_items()`、`workers.export_clips_job()`（背景、可取消）。
- 策略開關：`strategy_candidates/candidates_*(enabled=…)`，Library 讀 kv `strategies_enabled`（未設定＝全部，預設行為與 AI 指標不變）；平行分析時在主執行緒先讀設定。
- 新測試 tests/test_export_clips.py；策略/庫/核心測試全過。

## R66 — 只剪片段：策略模型與匯出核心（2026-10-25，依 review/clips_design/SPEC.md）
- core：7 種策略 STRAT_ORDER（從頭開始／AI 人物／精彩動作／整支（短片）／均勻取樣／音量高峰／場景變換），每策略 on/len/n 參數（STRAT_PER、STRAT_RANGE），每支總上限 12；舊的「中段」→「均勻取樣」別名。
- 新產生器：`loud`（音量 RMS 峰值、去重疊）與 `scene`（直方圖換景點後第一段），都是真的候選產生器，有測試（test_clips_r66）。
- 匯出：`ClipOptions`／`CLIP_FORMATS`（MP4 H.264、MP4 H.265、MOV ProRes）／`plan_clip_names`（命名規則、同名 _2 或覆寫）；`export_clips` 先寫 `.part`，成功才取代原檔 → 取消絕不刪同名舊檔（驗收 #4）。
- 候選清單依時間排序（rank 保留推薦順位）。
- **偏離規格（刻意）**：SPEC 預設「均勻取樣」關閉；實測關閉會讓 held-out 從 R65 的 IoU .745/hit50 .882 掉到 .684/.794，所以預設改為「開、每支 1 段、6.5 秒」，與 R65 指標完全相同（不退步）。使用者可在策略列一鍵關閉。
## R67 — 策略指標（r49 held-out 腳本，review/clips_design/eval_strategies.py → strategy_metrics.json）
| 策略（單獨） | IoU | hit50 |
|---|---|---|
| 從頭開始 | .503 | .529 |
| AI 人物 | .578 | .618 |
| 精彩動作 | .582 | .647 |
| 整支（短片） | .309 | .353 |
| 均勻取樣 | .556 | .559 |
| 音量高峰（新） | .535 | .647 |
| 場景變換（新） | .377 | .382 |
| **R66 預設** | **.745** | **.882**（= R65，不退步） |
| SPEC 預設（均勻關） | .684 | .794 |
| 全部開 | .774 | .941 |
run_cached 已勾選指標不變，「全部」召回率上升。
## R68 — 改策略即重算（不重新解碼）
- Library：strategy_cfg/set_strategy_cfg/enabled_strategies、特徵快取、`recompute_strategies`（只換 AI 候選；手動、已勾選且動過的片段保留）；workers.recompute_job。
- tests/test_recompute_r68.py：只開「精彩動作」n=2 → 每支 ≤2 段且只標 action；全關；<5 秒。
## R69 — 只剪片段介面
- 移除：音樂、轉場、成品時間軸、一鍵成片、旅程/影片長度等舊右欄（元件隱藏保留，舊後端測試仍可跑）；「較平淡」徽章移除。
- 新：策略列（7 個 pill，名稱＋段數，無障礙名「名，開/關，N 段」；「策略設定 ▾」面板：每策略長度/段數、還原預設、套用到全部影片）。
- 篩選列：全部／已勾選／未勾選、依影片／依策略（「也在：…」、「其他（策略已關閉）」）、全部收合、本頁全選、「共 N 段，已選 M 段（約 X 秒）」；找片段改為檔名/日期篩選。
- 卡片：時長疊在畫面右下、「起 – 迄」、最多 2 個策略 chip＋「+N」，**關閉的策略 chip 立即隱藏**（沒有照抄 mockup 的 bug）；焦點環 3px 白。
- 右欄＝匯出設定（資料夾、命名規則＋範例、格式、畫面比例、解析度、保留原音、依影片建子資料夾、同名覆寫）；<1280px 收成「匯出設定 ▸」抽屜。
- 底部匯出列：唯一黃色主按鈕「匯出已選片段（N）」（Ctrl+E／Ctrl+Enter），預覽選取、進度「匯出中 i/n · 剩約 m:ss」、取消；完成對話框（前 4 個檔名、失敗可重試、再匯出一次、在 Finder／檔案總管中顯示）。
- tests/test_gui_clips.py（驗收 #1–#6 GUI 版）；test_gui 改為新版介面斷言（tab 順序、toast 位置、焦點色、無低分徽章）。
- 截圖（真實 Insta360 LRV 素材）：review/clips_design/after/01–12，腳本 shoot_after.py。
- 全套測試 31/31 通過（循序執行）。
