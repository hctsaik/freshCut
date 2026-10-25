# CHANGELOG v5：對應 REVIEW_v2.md
日期：2026-10-24（Asia/Taipei）。修改前的備份：`review/mockup_v4_before.html`、`review/DESIGN_v4_before.md`。
驗證腳本：`/workspace/mockcheck/check5.js`。結果存在 `review/v5/check_results.json`，截圖在 `review/v5/*.png`。

## 必改
| 項目 | 修改內容 | 實測證據（check_results.json） |
|---|---|---|
| F1 雲端 AI 同意 | 新增 `dConsent` 對話框，使用審核報告的原文，預設焦點在「取消」，Esc 回到設定。新增「測試連線」（`role=status`）和「刪除已儲存的金鑰」。金鑰還沒測試通過前，描述框和按鈕都停用並顯示原因 | `F1_consent`：打開 dConsent 時焦點在「取消」，s14 仍未勾選。`F1_escBack`：Esc 回到 dSet，aiOn=false。`F1_afterConsent`：aiOn=true。`F1_keyStatus`：「✓ 連線成功」。`F1_barNoKey`：輸入框和按鈕停用，並顯示原因 |
| F2 垃圾桶 | 提示列改為「已將 n 個檔案移到垃圾桶」＋「在垃圾桶中顯示」，**不提供復原**。新增 `dPerm`：紅色 SD 卡（E:）警告，要先勾選「我了解無法還原」才能按「永久刪除」，預設焦點在「取消」。**核心**：`trash_supported()`、`delete_plan()["no_trash"]`、`delete_files(allow_permanent=)` | `F2_toast`、`F2_perm`（焦點在取消，勾選前按鈕停用、勾選後啟用）、`F2_permToast`。`test_groups.py`：沒有垃圾桶時拒絕刪除、確認後才永久刪除 |
| F3 AI 結果與錯誤 | 新增各狀態：分析中 12/30＋取消；「AI 相符 n%」標籤＋說明列＋「勾選全部相符（n）」；金鑰無效、額度用完、無法連線三種錯誤橫幅（`role=alert`），各附「重試」和「設定」 | `F3_run/done/key/quota/off` 與截圖 `F3_ai_*.png`。done 狀態有 4 個標籤，對比 0 項不合格 |
| F4 人臉評分說明 | 統一成一種說法：模型隨 App 安裝（約 12 MB），不另外下載。加上隱私說明；Windows ARM 顯示「此裝置不支援笑容偵測…」 | `F4_win`，DESIGN §1.3 |
| N1 hover | hover 改為 #A8A8A8 外框＋brightness(1.08)，勾選圓圈加白色 25% 底。已勾選改為黃框＋1px 外光暈 | `N1`：hover 的外框是 rgb(168,168,168)，已勾選的是 rgb(255,196,0)＋box-shadow |
| N2 停用的次要按鈕 | 新增 `.btn:disabled`：#242424／#8A8A8A／#3A3A3A，游標 not-allowed | `N2_disabled`：delBtn 和 pvBtn 停用時是這組樣式，啟用時是 #2c2c2c／#EEE |
| N3 ⌘↩ 被攔截 | 卡片和片段的 Enter 處理先排除 ⌘／Ctrl | `N3_cardMetaEnter`：開出 dDisk，沒有進入精修。`N3_clipCtrlEnterWin`：開出 dDisk。單按 Enter 仍會進入精修 |
| N4 抽屜焦點 | 關閉時（Esc 或再按一次按鈕）焦點回到 rail 按鈕；Tab 在抽屜和 rail 按鈕之間循環 | `N4_tabStaysInDrawer`：連按 Tab 30 次都在範圍內，結果為 true。`N4_escFocus`：焦點在 rail 且可見。`N4_toggleCloseFocus`：true |
| N5 巢狀互動元件 | 卡片改為 `role=group`，勾選鈕是真正的 32×32 `button[role=checkbox]`，「微調」可用 Tab 到達。清單的 option 只有文字 | `N5`：checkbox／option 內含互動元素的數量為 0，勾選鈕 32×32。`N5_space` 會切換；Tab 會到「微調」；點卡片會切換 |

## 部分修好的項目
| 項目 | 修改內容 | 證據 |
|---|---|---|
| 必改7 清單動作 | 清單列內的按鈕移到 `.listfoot` 動作列（`role=toolbar`），內容依選取而變；右鍵會選取該列並把焦點移到動作列 | `must7_actions`：選取錯誤項目時顯示「說明」「移除…」 |
| 必改8 窄視窗抽屜 | 同 N4 | 同 N4；1024 寬時 scrollW=1024，卡片 3 欄 |
| U10 hover | 同 N1 | 同 N1 |
| F6 ARM／硬體編碼 | **還是沒有實機驗證**（這個環境沒有這些硬體）。已在 DESIGN §11 寫好測試計畫和結果表（標「待測」）。核心已有硬體編碼失敗時退回 libx264 的邏輯 | DESIGN §11 |

## 建議
| 項目 | 修改內容 | 證據 |
|---|---|---|
| F5 成組檔案 | **在核心實作**：`group_key`、`group_files`、`files.companions` 欄位（含 migration）、`group_members`。匯入時一組只算一支，主檔優先順序 MP4 → LRV → INSV；只匯入單一檔案時會自動找同組檔；rescan 不會把附屬檔當成新影片。刪除時整組一起刪。介面上用組列出，例如「VID_0002 共 3 個檔案，4.9 GB」 | `tests/test_groups.py`（Insta360 insv+lrv+thm、mp4+lrv、GoPro GX+GL+THM、孤兒 thm、整組刪除）。`F5_groupList` |
| F6 監看 | `watch_interval()`：用電池時 300 秒。`status()` 和 `watched_status()` 回報「已中斷連線」；rescan 跳過不存在的資料夾，也不移除裡面的影片。介面加上灰色虛線卡，設定裡也標示 | `test_groups.py`（拔出 → 已中斷連線 → 插回 → 恢復）。`F6_card`、`F6_settings` |
| F7 實機時間 | 只完成測試計畫（DESIGN §11）。**沒有數字**，照實註明 | — |
| N6 上傳提示 | 移到描述框下方獨立一行，13px #EEE，加雲朵圖示和「詳細」連結 | `N6`：13px、rgb(238,238,238)、有圖示、有連結 |
| N7 把手 | 點擊區 24×84，視覺寬度維持 12px（::before） | `N7`：[24,84] |
| N8 清單選取 | 底色 #3d3520，左側 3px #FFC400 直條（7.61:1） | `N8`、`nonText` |
| N9 設定按鈕 | Windows：確定／取消／套用。Mac：完成，並註明「變更會立即生效」 | `N9_win`、`N9_mac` |

## 可選
| 項目 | 修改內容 | 證據 |
|---|---|---|
| F8 自訂長度 | 新增 5–600 秒的輸入框。`core.fit_to_target()` 依比例縮短，每段最短 1.5 秒，縮完仍超過時回報剩餘秒數；`suggest_drop_count()` 算出建議取消勾選幾段 | `F8_sum`：「縮到每段 1.5 秒仍超過 4.0 秒，建議取消勾選 3 段」。`test_groups.py` |
| N10 框線 | ghost 按鈕框線 #767676（3.5:1；審核建議的 #6A6A6A 實算只有 2.94，所以改用較亮的顏色），次要按鈕框線 #7A7A7A（3.25:1） | `nonText` |

## 驗證摘要
- 測試全部通過：`tests/test_groups.py`（新增）、`test_library.py`（delete_summary 斷言已更新）、`test_core.py`。
- 對比：16 個畫面／對話框 × mac／win × 1440／1024，再加 5 個 AI 狀態，文字對比 0 項不合格，最小字級 12px。
- 頁面上沒有任何 JS 錯誤。
- v4 的鍵盤測試全部重跑，仍然通過：卡片 Space 後焦點保留、方向鍵、清單、radiogroup、時間軸移動、對話框焦點陷阱與 Esc、焦點歸還、進度 Esc、移除 + ⌘Z。
