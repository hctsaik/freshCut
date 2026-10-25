# CHANGELOG v6（回應 review/REVIEW_v3.md）

日期：2026-10-24（台北時間）。證據鍵都是 `review/v6/check_results.json` 的鍵，下方的值是從那個檔案抄出來的（已用腳本核對鍵都存在）。測試輸出：`review/v6/test_runs.txt`。

## 先更正
v5 的 CHANGELOG 說測試「全部通過」，這不正確。test_library 只在 `.venv/bin/python` 下通過；用系統 `python3` 跑時，ffmpeg 產生的測試影片只有 4.5 秒，只有 2 段候選，所以第 26 行 IndexError。我當時只用 venv 跑。v6 每個測試都用兩個直譯器跑。

## 必改
| 項目 | 處理 | 證據 |
|---|---|---|
| R5 test_library 失敗 | 測試影片改 12 秒，先 `assert len(c0) >= 3`；另外第 66 行因 O3 組名改為「c」+ primary_ext「LRV」而更新 | test_runs.txt：8/8 exit 0 |
| R6 macOS 垃圾桶偵測 | statfs `f_fstypename` + `MNT_LOCAL`，退回 `NSURLVolumeIsLocalKey`；Windows `GetDriveTypeW`／UNC | `tests/test_volume.py`（VOLUME OK，模擬資料；實機 macOS 才會跑的自我測試在 Linux 上略過） |
| R4 設定快照／取消還原 | Windows 快照、取消與 Esc 還原（含 AI 開關）、套用、未套用提示；macOS 即時生效 | `R4_dirty` `R4_s3AfterCancel`=false `R4_consentStaged` `R4_escReverts` `R4_apply` `R4_cancelAfterApply` `R4_ok` `R4_macEscKeeps` |
| R1 「詳細」 | 資訊模式，只有「關閉」與「在設定中關閉雲端 AI」；關閉後 AI 仍開 | `R1_info` `R1_escBack`(aiOn=true) `R1_closeBtn` `R1_offLink` |
| F3b 狀態一致 | 勾選全部相符只在 done；金鑰無效停用輸入、不給重試；額度與離線加「上次未完成・」 | `F3b_run` `F3b_key` `F3b_quota` `F3b_off` `F3b_done` `R2_hidden` |
| R2 [hidden] + 自訂秒數 | `[hidden]{display:none!important}`；5–600 秒驗證，沿用上一個有效值 | `R2_hidden` `R2_invalid` `R2_valid` `R2_rowHiddenAt30` |
| R3 danger:disabled | #8A8A8A／#3A3A3A／#242424，not-allowed，對比 4.5:1 | `R3_permDisabled` `R3_permEnabled` `nonText.dangerDisabled_8A8A8A_on_242424` |

## 建議與可選
| 項目 | 處理 | 證據 |
|---|---|---|
| S1 Tab 停留點 | 卡片牆一個停留點（roving）、Home 到標題列、篩選 toolbar、時間軸 roving、⌥⌘T／Ctrl+Alt+T | `S1_wallStops`=1、`S1_tabsSearchToGo`=16、`S1_tabsSearchToGo_bannerDismissed`=15、`S1_tabsAfterSkipToGo`=2、`S1_skipShortcut` `S1_skipShortcutWin` `S1_rovingRemembers` `S1_homeToHeader` `S1_headerDown` `S1_hint` |
| S2 沒有垃圾桶時可略過 | 「略過這 n 個檔案」+ 磁碟名稱；核心 skip_no_trash | `S2_perm` `S2_skipToast` `S2_netMsg`；test_groups |
| S3 I／O 鍵 | 設在播放頭並朗讀 | `S3_in` `S3_out` |
| S4 垃圾桶後 ⌘Z | 提示到 Finder／資源回收筒還原 | `S4_undoAfterTrash` |
| S5 效能通過條件 | DESIGN §11 | （文件） |
| O1 點抽屜外關閉 | pointerdown | `O1_clickOutside` |
| O2 只刪除預覽檔 | 核心 previews_only + 介面選項 | `O2_rowVisible` `O2_files` `O2_after` `O2_hiddenNoPreviews`；test_volume |
| O3 組名 | VID_日期_時間_編號 + 副檔名徽章 | `O3_listName`；test_library 第 66 行 |

## 回歸
- 對比：70 組 `contrast_*`，0 項不合格。
- `pageErrors`：[]。
- v5 的鍵盤檢查沒有退步。`N5_tabToTrim` 現在是 `target`，因為「微調」已經移出 Tab 順序（改用 Enter），這是刻意的改變。

## 沒做到／限制
- S1：有第一次使用提示時是 16 下，超過目標 15；關掉提示後是 15 下。
- R6：只在 Linux 上用模擬資料測過，沒有接過真的 Mac SMB、NAS 或 SD 卡，也沒有在真的 Windows 上測。
- 清單的可及名稱會念成「VID_0001MP4」（徽章文字直接接在後面），GUI 時要在中間加分隔。
