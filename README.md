# 精華剪輯（Insta Editor）

把一堆旅行／運動影片（含 Insta360 的 .insv／.lrv）丟進來，自動挑出精彩片段，用循環播放的靜音小預覽勾選、微調、排序，一鍵產生 15／30／60 秒或自訂長度的成品（16:9、9:16、1:1，1080p／4K）。原始檔永遠不會被修改。

設計規格見 `DESIGN.md`（v7，已凍結），互動原型見 `mockup.html`。

## 快速開始

| 系統 | 做法 |
|---|---|
| macOS | 在 Finder 雙擊 `run_mac.command`（第一次若被擋，按右鍵 →「打開」）。 |
| Windows | 雙擊 `run_windows.bat`。 |
| 手動 | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python -m app` |

第一次執行會建立 `.venv` 並安裝套件，需要網路與 Python 3.10 以上版本。

## 功能

- **匯入**：拖放檔案或資料夾，也可以用工具列按鈕匯入。資料夾會被監看：插上 SD 卡時自動加入新檔；拔掉時顯示「已中斷連線」，不會把影片標成遺失。
- **群組**：同一段拍攝的 .insv／.lrv／.thm 會合併成一支。主檔優先順序為 MP4 > LRV > INSV。
- **素材庫快取**：分析結果、預覽 proxy、縮圖都存在系統的應用程式資料夾。重開不會重新分析，勾選與微調也會保留；檔案內容改變時才重算。到「設定 → 快取」可以清除快取。
- **卡片牆**：每段推薦片段都是一張循環、靜音的迷你預覽。
  - 空白鍵：勾選或取消
  - Enter：微調（I／O 設定入點與出點）
  - Home：跳到影片名稱
  - 方向鍵：在卡片間移動；整面卡片牆只佔一個 Tab 停留點
- **時間軸**：可拖曳排序，也可用鍵盤操作。
  - `⌘↑↓`（Windows 為 `Ctrl+↑↓`）：移動片段
  - Delete：移除片段
  - `⌥⌘T`（Windows 為 `Ctrl+Alt+T`）：從任何地方跳到時間軸
- **長度控制**：成品超過目標長度時，各段會等比例縮短（每段最短 1.5 秒）。仍然超過時，會建議取消勾選幾段。
- **移除與刪除**：在左側清單按 Delete，預設只會「從清單移除」，可以用 `⌘Z`／`Ctrl+Z` 復原。
  - 「刪除原始檔…」會把整組檔案移到垃圾桶／資源回收筒，也可以只刪除 .lrv／.thm 預覽檔。
  - 網路磁碟或記憶卡沒有垃圾桶時，可以選擇略過，或勾選「我了解無法還原」後永久刪除。
- **輸出**：
  - 背景執行，有進度與取消確認，並會先檢查磁碟空間。
  - 完成後可直接播放，或在 Finder／檔案總管中顯示。
  - 可選背景音樂（設定中指定音樂資料夾）、結尾淡出，以及硬體編碼（VideoToolbox／Media Foundation；失敗會自動退回 libx264）。
- **AI 剪輯（離線，不需金鑰）**：
  - 「一鍵成片」：選一個資料夾，自動完成挑片、去重、對拍與輸出。
  - 「換一批」：保留鎖定（🔒／L 鍵）的片段，其餘重新挑選。
  - 也提供風格範本、精彩瞬間慢動作、9:16 主體跟拍（有臉時跟著臉）。
  - 本機的 CLIP 語意搜尋是選用功能，需要另外安裝 open_clip。
- **人臉／笑臉偵測（選用）**：啟動腳本會嘗試安裝 `requirements-optional.txt`（opencv-python-headless<5），裝不上也不影響使用，不必下載模型；沒有安裝也能正常使用。
- **內建音樂**：有四種氣氛的合成配樂（CC0，見 `MUSIC_LICENSE.md`），音質有限。想要更好的音樂，可以在設定中指定自己的音樂資料夾。
- **濾鏡**：鮮豔、電影、暖色、冷色、復古、黑白，可匯入 .cube LUT，右側即時預覽；另有「自動調色」（預設開，每段只量一次並快取）。
- **分享預設**：IG Reels／YouTube Shorts／TikTok／YouTube 橫式，一次設定比例、長度與 -14 LUFS 音量。
- **片頭文字與貼圖**：文字效果（經典／霓虹／標籤／電影）、動畫（淡入／上滑／放大）。emoji 貼圖可放四角，也可以在實際畫面上拖曳或用方向鍵定位，有彈跳／浮動動畫，一次最多 5 張。
- **特效模板**：節拍放大、閃白、故障（輕微）。有音樂時跟著強拍觸發，沒有音樂時在剪接點觸發；選了之後會顯示 4 格預覽。
- **速度曲線**：在微調視窗用 5 個控制點畫出速度變化（0.25–4 倍），也有中段慢動作、蒙太奇、漸慢、快轉等預設，並即時顯示輸出長度。
- **分析速度**：每支影片只解碼一次；多支影片會平行分析（最多 3 個執行緒）。macOS／Windows 預設先試硬體解碼，失敗會自動改用軟體解碼；設 `IE_HWACCEL=` 可以關閉，設 `IE_ANALYZE_WORKERS=1` 可以改回依序分析。
- **自動標籤（選用，需本機 CLIP）**：分析後自動貼上 海／山／雪／夜景／人物／寵物，顯示在卡片上；「主題標籤」讓一鍵成片優先挑該主題。標籤規則更新後，開啟 App 時會在背景自動重貼舊標籤。
- **低分標註**：明顯比最佳片段差（<45%）的片段標「分數偏低」，不會自動勾選。
- **窄視窗**：寬度不到 1180 px 時，右側設定改由底部「成品設定 ▸」開合。
- **雲端 AI 搜尋（選用、預設關閉）**：
  - 須在設定中同意後才會開啟。只上傳每段 1 張縮圖與你輸入的文字，可使用任何 OpenAI 相容 API。
  - 金鑰存在系統鑰匙圈（`keyring`）。macOS 的設定即時生效；Windows 的金鑰測試與刪除要按「套用」或「確定」後才生效。

## 測試

```bash
for py in python3 .venv/bin/python; do
  for t in tests/test_*.py; do $py -u $t || echo "FAIL $py $t"; done
done
```

缺少 PySide6、OpenCV 或 open_clip 的直譯器，會在對應的測試印出 SKIP。

`tests/test_gui.py` 會在離螢幕模式（`QT_QPA_PLATFORM=offscreen`）實際操作 GUI：匯入 → 推薦 → 勾選 → 輸出，並把截圖存到 `review/v7/gui_*.png`。沒有安裝 PySide6 的直譯器會印出 SKIP 並略過。

## 用 PyInstaller 打包

### macOS（.app）

```bash
.venv/bin/pip install pyinstaller
# 建議放入原生架構的 ffmpeg（見下方說明），放在 vendor/ffmpeg
.venv/bin/pyinstaller --noconfirm --windowed --name "精華剪輯" \
  --add-binary "vendor/ffmpeg:bin" \
  --collect-submodules app app/__main__.py
# 產出：dist/精華剪輯.app
# 要發佈給他人時，還需要 codesign 與 notarize（xcrun notarytool）
```

### Windows（.exe）

```bat
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller --noconfirm --windowed --name InstaEditor ^
  --add-binary "vendor\ffmpeg.exe;bin" ^
  --collect-submodules app app\__main__.py
REM 產出：dist\InstaEditor\InstaEditor.exe
```

程式尋找 ffmpeg 的順序如下（`app/core.py: find_ffmpeg`）：

1. 環境變數 `FFMPEG_BINARY`
2. 打包時放在 `bin/` 的檔案
3. `imageio-ffmpeg` 內建的版本
4. 系統 PATH 或 Homebrew

### 關於 Apple Silicon（ARM64）的 ffmpeg

`imageio-ffmpeg` 在 macOS 上提供的 ffmpeg 可能是 **x86_64** 版。在 M 系列晶片上，它要透過 Rosetta 2 執行，分析與輸出會明顯變慢，而且沒有 Rosetta 時根本無法執行。打包 ARM64 版 .app 時，請放入**原生 arm64 的 ffmpeg**，做法有兩種：

- 執行 `brew install ffmpeg`，再把 `/opt/homebrew/bin/ffmpeg` 複製到 `vendor/ffmpeg`。注意：Homebrew 版會動態連結 dylib，打包前要用 `otool -L` 確認相依的函式庫，或改用靜態編譯版。
- 使用可信來源提供的靜態 arm64 版本。

確認方式：執行 `file vendor/ffmpeg`，結果應顯示 `Mach-O 64-bit executable arm64`。開發時也可以直接設定 `export FFMPEG_BINARY=/opt/homebrew/bin/ffmpeg`。

## 專案結構

```
app/core.py        ffmpeg：分析、候選片段、縮圖、proxy、輸出
app/smart.py       自動挑片、範本、跟拍平滑、標題 PNG
app/beats.py       音樂節拍偵測與對拍長度
app/faces.py       OpenCV 人臉／笑臉（選用）
app/music.py       內建合成配樂（CC0）
app/semantic.py    本機 CLIP 語意搜尋（選用）
app/library.py     SQLite 素材庫：匯入、監看、群組、快取、勾選、刪除
app/gui/           PySide6 介面（main、widgets、dialogs、workers、ai、style）
tests/             測試（純 Python 腳本，可直接執行）
review/            審查紀錄、變更紀錄、截圖
```

## 已知限制

請見 `review/CHANGELOG_v7.md` 的「尚未完成／未驗證」一節、`review/ROUNDS.md` 各輪的「未驗證」，以及 `review/FLASHCUT_COMPARE.md`。
目前已知的限制：
- Windows（含 ARM64）與實機 macOS 都還沒有實際跑過。
- 笑臉偵測只在 8 張公有領域肖像上量過（TPR 9/12、FPR 0/12），還沒有用真實旅遊影片驗證。
- 自動標籤只用合成圖測過（R22 後合成雪景可以判成「雪」），沒有用真實照片驗證。
- 內建音樂是簡單的合成音。
- 特效只有 3 種，預覽是靜態 4 格；已加入的貼圖不能再拖曳，只能刪掉重加；沒有逐段字幕。
- 速度曲線以 0.5 秒為單位，尖點會被平均掉；對拍時沒有把手動曲線算進去。
- 硬體解碼（VideoToolbox／D3D11）和平行分析的記憶體用量，都沒有在真實 Mac 或 Windows ARM 上量過。
- 所有格式穩定性測試用的都是合成檔，不是真的 Insta360／iPhone 素材。

## R31–R38：更方便的自動剪輯＋LRV/魚眼
- 插入記憶卡會自動跳出匯入提示；可以依日期/旅程分組，按「用這組做影片」；可以輸入一句話需求（例如「30 秒 直式 滑雪 輕快」）；剪完後可以按「短一點／換首歌／刪這段」；會記住偏好，也能存成「我的範本」；可以一次輸出 16:9、9:16、1:1。
- MP4 旁邊有 LRV 時，分析用 LRV、輸出用 MP4（實測快 3–5 倍）。檔名被改掉時，用長度、fps、拍攝時間（±2 秒）配對。
- 方形的單一圓形魚眼會自動攤平（v360 fisheye，預設 FOV 190°，可用 `IE_FISHEYE_FOV` 調整；視角用 `IE_FISHEYE_VIEW` 調整）。目前限制：每段是固定視角，不會水平校正。

## R39–R41：魚眼跟拍、水平校正、構圖
- 單一圓形魚眼（例如 Insta360 GO 3）輸出時會在 LRV 上找人（NanoDet-Plus，Apache-2.0），逐格平滑跟拍（deadzone＋easing），並依相機重力感測自動水平。
- 微調片段 →「水平校正（魚眼）」：自動或手動角度（每段）。
- 環境變數：IE_FISHEYE_FOLLOW=0 關閉跟拍；IE_ROLL_LINES=1 沒有 IMU 時試用直線法估水平。

## R43–R47：遮擋偵測、加速、記憶體
- 手套/手擋鏡頭（魚眼圓內暗或膚色的低紋理大區塊）與「下半部都是手」的畫面會大幅降分（IE_OCC_T、IE_OCC_W 可調）。
- 跟拍輸出：減少不必要的鏡頭指令、依來源解析度計算再放大、片段平行輸出（IE_JOBS）。約快 2–2.7 倍。
- 分析長檔時記憶體不再隨長度暴增（分塊處理＋memmap）。19 分鐘檔峰值約 284 MB。
- 人物偵測門檻 0.3（IE_DET_T）。
