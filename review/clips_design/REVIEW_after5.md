# REVIEW_after5 — R73 review (clips mode)

Reviewed: 2026-10-25 22:43–22:55 (Asia/Taipei, UTC+8).

Method:
- Took a code snapshot at /tmp/r73snap and kept it.
- Did not modify app/ or tests/. `diff -rq` shows no difference between the snapshot and the live tree.
- Ran all 35 test files twice, offscreen: **70/70 exit=0** → after5_audit/tests.txt.
- Ran my own headless flow (/tmp/r73a/audit.py) on a mixed case: 2 shortened clips plus 1 real out-of-range clip (9999–10004 s) → audit_results.json, c01–c06.
- Viewed screenshots after5/17, 24 and 25.

## Scores
| | Score | R72 |
|---|---|---|
| UI/UX | **92** | 88 |
| Functionality | **95** | 93 |

**Bar: met.** Both scores are ≥90 and there are no must-fix items.

## Claim verification
| Claim | Result | Evidence |
|---|---|---|
| Each failed file name gets its own line, shown in full | ✅ In my real case the full name 「VID_20240827_111111_002_從頭開始_02.mp4」 is shown. Middle elision for very long names and the hover tooltip are covered by test_r73, which passed twice; I did not reproduce the overlong-name case myself | c05_done_dialog.png |
| Reason on the next line, indented, wraps | ✅ after5/24: a long reason wraps over two lines and nothing is cut off | after5/24 |
| Retry on its own row | ✅ | c05, 24 |
| Out-of-range reason is short | ✅ Core returns 「片段超出素材長度（素材只有 3.0 秒）」 | audio_off_oor |
| Title shows failures and shortened clips together | ✅ 「⚠ 已匯出 5 個片段，1 個失敗、2 段被截短」. Window title: 匯出未完成 | done.title |

Regression check (all re-run this round, no regressions):
- Drawer at 1200 and 1024 does not cover the export bar.
- Disabled checkboxes keep their tick.
- A single cancel button.
- Pills are disabled during export.
- Progress label: worst case is 179 px, within the 191 px minimum width.
- Toast stays inside the export bar.
- File list is sorted.
- No horizontal scrollbar.
- AC4 cancel keeps the existing file and leaves no .part file.
- Audio off produces a video-only output.
- Shortened clips are labelled 4.0→1.0 and 10.0→5.0.

## Must-fix
None.

## Suggested
None.

## Optional
- When every clip fails (after5/24), 「開啟資料夾」 is still the yellow primary button, and the line 「滑鼠移到檔名可看完整路徑」 has no file names to point to. Make 「重試失敗的 N 個」 the primary action and hide the hint.
- after5/24 uses an old-format long reason. If that format can still appear, consider shortening those reasons as well.
- Colour 「（已截短）」 orange in the file list.

## Representative screenshot
after5_audit/c05_done_dialog.png: the mixed case, showing the title with both counts, the shortened-clip list, the failure name on its own line with the reason indented below it, and retry on its own row.
