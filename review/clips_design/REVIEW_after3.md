# REVIEW_after3 — R71 review (clips mode)

Review time: 2026-10-25 (Asia/Taipei, UTC+8). Method: same as REVIEW_after2.
- Code snapshot at /tmp/r71snap (app/ and tests/ copied, .venv symlinked). app/ and tests/ were not modified; `diff -rq` against the live tree after the review shows no differences.
- Test files: 33 in tests/. Each one ran twice offscreen (run1 + run2). **66/66 exit=0, 0 tracebacks**. Load average was 4–12. test_gui took 125 s and 109 s at load ≈12 and passed both times → after3_audit/tests.txt.
- My own headless flow (/tmp/r71a/audit.py) → after3_audit/audit_results.json and c01–c06 PNGs. perf_500 rerun → after3_audit/perf.txt.
- Viewed all 21 screenshots in after3/.

## Scores
| | Score | R70 |
|---|---|---|
| UI/UX | **91** | 80 |
| Functionality | **94** | 90 |

**Bar: met.** Both scores are ≥90 and there are no must-fix items.

## Claim verification
| Claim | Result | Evidence |
|---|---|---|
| Disabled checked boxes show a grey fill with a tick | ✅ During export, 保留原音 and 依影片建立子資料夾 are isEnabled=False and isChecked=True, and both show a tick | c04_disabled_checkbox.png, c03, after3/20 |
| Drawer stops at the export bar (1200 and 1024) | ✅ Drawer at 1200: y0–672. exp_b: y681. covered=false at both widths. exp_b visible | audit_results drawer1200/1024, c02_drawer_1024.png |
| Done dialog: no h-scrollbar, file name with middle elision, full path in 位置 line and tooltip | ✅ hpolicy=AlwaysOff, hbar hidden. Each item shows only the file name; the tooltip has the full path plus the folder. The long-name case (after3/16) elides in the middle (…) | c05, after3/16 |
| 已截短 label with seconds | ✅ I reproduced it myself: a 2–6 s segment on a 3 s video shows "（已截短）" and "⚠ … 4.0→1.0 秒". In core with audio=False, a 1–5 s segment gives want 4.0 / got 2.0, and ffprobe shows only a 2.0 s video stream (audio really is off). Fully out of range (9999–10004) gives ClipInvalid | c05, audit_results.audio_off_oor |
| Single cancel button | ✅ Only one visible button contains 取消 during export: 「取消匯出」 | exporting.cancels |
| Disabled strategy pills look disabled | ✅ All 7 pills are isEnabled=False and drawn grey with a dashed border | c03, after3/11 |
| Ticks in the strategy panel | ✅ | after3/06 |
| 「剩約」 is wide enough | ✅ (with a caveat) Minimum width is reserved, and test_r71 checks that "120/500 · 剩約 12:34" fits. My check with the stricter "9999/9999 · 剩約 99:99" failed: the width is computed from the font before QSS applies. *Inference:* only extreme counts would be clipped | exporting.prog_fits=false |
| Toast sits inside the export bar | ✅ y=813, inside the export bar, and does not overlap the card area. It also appears in the bar during export without covering the progress | c06, c03 |
| test_gui wait does not depend on load | ✅ Passed twice at load ≈12. *Inference:* 2 runs cannot prove it never flakes | tests.txt |
| Cancel keeps an existing file (AC4) | ✅ over=False and over=True: cancelled, existing file intact, no .part left | cancel_over* |
| 531-clip performance | ⚠ I reproduced it with 531 cards, but test files were running at the same time (load ≈12), so the numbers are higher: load 2.60 s, rebuild 3.01 s, select all 1.29 s, reflow 0.42 s, scroll median 8.5 ms (max 32.5). *Inference:* the gap from the claimed figures is due to load, because the load-to-wall time is identical (2.59 vs 2.60). Usable either way | perf.txt |

## Must-fix
None.

## Suggested
1. When some clips were shortened, the done dialog title still reads「✓ 已匯出 N 個片段」. Use ⚠ or add「（1 段已截短）」to the title so it isn't missed.
2. The failure reason shows the exception class name (「ClipInvalid: 輸出檔沒有聲音」, after3/17). Show only the Chinese reason.
3. The 位置 line's hint text breaks a word across lines in a narrow dialog (after3/21:「完整路／徑」). Put the hint on its own line or shorten it.
4. Compute the 剩約 minimum width after the stylesheet is applied, using the bold/QSS font.

## Optional
- Sort the done list by file name. after3/21 shows _02 before _01.
- The truncation warning breaks inside the file name. Put「4.0→1.0 秒」first, then the file name.
- Run perf_500 again when the machine is idle, to confirm the numbers.

## Representative screenshot
after3_audit/c03_exporting.png: the main screen during export. It shows the locked pills, disabled boxes with ticks, the single 取消匯出 button, the progress, and the toast inside the export bar.
