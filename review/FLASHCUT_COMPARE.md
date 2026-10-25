# 精華剪輯 vs Insta360 Auto Edit／FlashCut（誠實對照表，R13 重新校準，R30 更新）

**主要比較對象改為 Insta360 App 的 Auto Edit**（v2.3.0 起合併 AI Edit；官方手冊：https://onlinemanual.insta360.com/app/en-us/operation-tutorial/edit-function/auto-edit ，2026-10-25 Asia/Taipei 查閱）。官方稱五大能力：智慧構圖、精準選段、360 運鏡、場景辨識、配樂匹配；支援 360＋平面混合、最多 100 個素材、總長 20–60 分鐘（依手機效能）、70+ 範本、貼紙與特效。FlashCut 資料保留在下方作參考。


FlashCut 資料來源（2026-10-25 查閱，皆為 Insta360 官方/論壇公開頁）：
- https://www.insta360.com/support/supportcourse?post_id=19659 （What's New with FlashCut）
- https://forums.insta360.com/section/14/post/8518/ （FlashCut 2.0 / AI Trim）
- https://forums.insta360.com/section/16/post/54259/ （App Tutorial）

我沒有實機操作 FlashCut。表中「官方稱」= 官方頁面有寫但我沒驗證；「unverified」= 找不到明確資料。
我方欄位只寫**有自動測試觀察到**的行為（見 tests/ 與 ROUNDS.md），否則標「未驗證」。

| 功能 | FlashCut | 精華剪輯（本專案） | 證據 |
|---|---|---|---|
| 平台 | 手機 App（iOS/Android）官方稱 | 桌面 macOS / Windows（含 ARM，未實機驗證） | — |
| 一鍵成片 | 官方稱：選主題/片段 → 幾秒出片 | ✅ 一鍵成片（選資料夾 → 分析 → 自動挑選 → 對拍 → 輸出） | test_gui one_click |
| 需要網路/帳號 | unverified（App 本身需登入? 未確認） | ✅ 全離線，無 token；雲端 AI 預設關閉 | — |
| 精華偵測 | 官方稱「AI 影像辨識」，細節 unverified | 動態、音量、聲音峰值、清晰度、色彩、曝光、晃動懲罰、近似重複排除、MMR 多樣性 | test_ai shake/dedupe |
| 人臉/笑臉偵測 | unverified | ✅ R6：OpenCV Haar（選用）；R19 修正笑臉在分析解析度下從未觸發的問題：8 張公有領域肖像 TPR 9/12、FPR 0/12 | test_smile；真實影片未驗證，樣本小且同質 |
| 對拍剪輯 | 官方稱 on beat | ✅ 本機節拍偵測（120 BPM 測試音軌誤差 <2 BPM），三種節奏 輕快/平穩/史詩 | test_ai beats |
| 主題範本 | 官方稱 vlog/life/travel/sports，各自轉場與音樂 | ✅ Vlog / 運動 / 旅行（節奏、轉場、慢動作、長度、標題）；❌ 沒有內建音樂庫 | test_gui apply_style |
| 內建音樂庫 / 推薦配樂 | 官方稱有，Auto Edit 依場景配樂、曲庫擴充 | 🟡 R7：4 種氣氛的合成配樂（CC0，音質有限）＋自己的音樂資料夾 | test_music |
| 輸出長度 | 官方稱 短/中/長；主題片 ≤15 秒 | ✅ 15/30/60/自訂秒數 | test_core |
| 長片 AI Trim | 官方稱 ≥1 分鐘單支影片 | ✅ 任何長度，一支影片可出多段 | test_library |
| 360 素材 | **Auto Edit 官方稱支援 360（含 AI 360 運鏡）**；FlashCut 官方稱不支援 | ⚠️ 只有固定視角 equirect→平面 已驗證；沒有 360 自動運鏡；.insv 雙魚眼參數 unverified。**此項 Auto Edit 較強，不再列為我方優勢** | test_ai 360 |
| 9:16 智慧構圖 | Auto Edit 官方稱 smart framing（APEI 演算法）；Editor 另有 Deep Track 物件追蹤 | ✅ 追亮/動區域的平滑水平移動裁切（不是物件辨識） | test_ai reframe |
| 慢動作/變速 | 官方稱可手動調速；主題片不能調速 | ✅ 精彩峰值自動慢動作（R17 漸變）；R26 起有手動速度曲線（5 點、0.25–4 倍、4 種預設；0.5 秒離散，尖點會被平均） | test_reframe、test_ai ramp、test_speed |
| 標題/日期字卡 | 官方稱可加文字貼紙 | ✅ 片頭標題+日期；R16：4 種文字效果、3 種動畫 | test_ai、test_text_fx |
| 語意搜尋（「海邊」「夜景」） | unverified | ✅ 選用離線 CLIP；R15 自動標籤（海/山/雪/夜景/人物/寵物）＋主題優先；R22 改善雪景（4 張較逼真的合成雪景都判對）；R29 標籤器升級後自動重貼 | test_semantic、test_retag（只用合成圖） |
| 手動微調 | 官方稱可替換、鎖定、修剪 | ✅ 卡片牆勾選、I/O 微調、時間軸排序、復原 | test_gui |
| 濾鏡/貼紙/特效 | 官方稱有 | 🟡 6 種濾鏡＋LUT＋自動調色；10 個 emoji 貼圖，可拖曳定位（R24），背景是實際畫面（R28），最多 5 張（R28），有彈跳／浮動動畫；3 種特效（節拍放大／閃白／故障，R23），跟著強拍觸發，有 4 格預覽（R29）。**數量仍遠少於 Auto Edit 的 70+ 範本** | test_looks、test_text_fx、test_effects |
| 鎖定片段後重新洗牌 | FlashCut 官方稱有 | ✅ 卡片鎖頭／L 鍵鎖定，「換一批」保留鎖定片段（舊表此列已過時） | test_gui lock/reshuffle |
| 原始檔安全 | unverified | ✅ 原始檔永不修改；刪除走垃圾桶 | test_library |

| 分享預設 | 手機直接分享（官方稱） | ✅ R11：IG Reels／Shorts／TikTok／YouTube 預設（比例、長度、-14 LUFS） | test_gui R11、test_looks |
| 素材格式穩定性 | 官方稱支援自家相機格式 | 🟡 R25：VFR、HEVC、10-bit、單聲道、5.1、無音訊、4K、旋轉 90° 都能出片（全部是合成檔）；修正直拍旋轉的 bug | test_robust |
| 分析速度 | 手機上，官方未公布數據 | 🟡 R27：只解碼一次＋多支影片平行處理＋（Mac/Win）硬體解碼並可退回軟體。60 秒 1080p：單核 8.4→5.1 秒；4 支在 4 核上 7.2→5.0 秒（Linux 容器）。硬體解碼**未實機驗證** | test_perf |
| LUT | Editor 有調色（官方稱），.cube 匯入 unverified | ✅ R12：.cube 匯入＋即時濾鏡預覽 | test_looks、test_gui R12 |

R30 補充：R21–R29 把特效、貼圖、變速、穩定性、速度都補了基本版本，但都只是「有」的程度，數量和精緻度跟 Auto Edit 還差很遠。所有比較仍然**沒有用真實 Insta360 素材做過並排比較**。

結論（誠實，R13 重新校準）：我們較強的只有「離線免帳號、桌面、長片不限 20/60 分鐘、可控的手動微調、原檔安全」。
Auto Edit（官方稱）在 360 自動運鏡、物件／場景辨識、授權曲庫、範本數量（70+）、貼紙特效、手機分享上較強。兩者都沒有實測對比，品質高下 unverified。
