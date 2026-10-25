# REVIEW_after4 — R72 review (clips mode)

Review date: 2026-10-25, 22:02–22:15 (Taipei time, UTC+8)

Method:
- Code snapshot kept at /tmp/r72snap: app/ and tests/ copied, .venv symlinked.
- app/ and tests/ unchanged. After the review, `diff -rq` against the live tree shows no differences.
- All 34 test files run twice offscreen. **68/68 runs exit=0, 0 tracebacks.** Load average was 6–11. The test_gui_clips segfault mentioned in ROUNDS.md did not reproduce.
- My own headless flow: /tmp/r72a/audit.py, results in after4_audit/audit_results.json and c01–c06.
- I looked at after4/12, 17, 21, 22 and 23.
- My flow deliberately builds a **mixed case** that R72's own screenshots don't cover: 2 shortened clips plus 1 fully out-of-range clip (9999–10004 s, a realistic failure with a long reason).

## Scores
| | Score | R71 |
|---|---|---|
| UI/UX | **88** | 91 |
| Functionality | **93** | 94 |

**Bar: not met.** There is 1 must-fix item, and UI/UX is below 90.

## Claim verification
| # | Claim | Result | Evidence |
|---|---|---|---|
| 1 | Shortened clips: title reads 「⚠ …，其中 K 段被截短」 | ✅ Holds when there are only shortened clips (after4/21). ⚠ **When a failure is also present, the title becomes 「⚠ 已匯出 5 個片段，1 個失敗」 and the shortened count disappears.** The orange section below still lists them. | c05, done.title |
| 2 | Failure reason is Chinese only | ✅ core returns 「入點／出點超出素材長度（…）」 with no ClipInvalid. The class name appears only in the stderr log. Note: test_r70 lines 28 and 56 were updated to match the new behaviour (this is a reasonable test adjustment). | audio_off_oor, audit.log |
| 3 | 「位置：」 on its own line, hint on its own line with no wrap | ✅ | c05, after4/12 |
| 4 | 「剩約」 width uses the real font | ✅ After polish: worst-case text is 179 px, minimum width is 191 px. after4/22 and 23 show it fully. | exporting.prog_fits |
| 5 | Completion list sorted by file name | ✅ sorted_ok=true | done.items |
| 6 | Shortened warning and failure list: one line per file, no wrap | ✅ Shortened list is fine. ❌ **Failure list breaks with a long reason**: the file name is squeezed to 「VID_2…2.mp4」, and the reason itself is also cut off (「片段 9999.00–10…」). You can't tell from the dialog which clip failed. after4/17 used a short reason, so the problem didn't show. | c05_done_dialog.png |

Other checks with no regressions (all re-run this round):
- Drawer stops at the export bar at both 1200 and 1024 wide.
- Disabled checkboxes keep their tick.
- Only one cancel button.
- Pills are disabled during export.
- Toast stays inside the export bar.
- AC4 cancel keeps the pre-existing file, and no .part file is left.
- Export with audio off contains a video stream only.

## Must-fix
1. **Failure list readability**: when the reason is long, the file name collapses to a few characters. Possible fixes:
   - Elide the reason first, or shorten it (e.g. 「超出影片長度」, with details in the tooltip), so the file name always keeps a readable width. For example, keep the strategy name and sequence number at the end and elide only the middle of the video name.
   - Or put the reason on a second, indented line.
   - Add a test with a long reason (the out-of-range case).

## Suggested
1. When a failure and shortened clips occur together, the title should show both, e.g. 「⚠ 已匯出 5 個片段，1 個失敗，2 段被截短」.

## Optional
- The 「（已截短）」 marker in the list could be orange to match the warning section.

## Representative screenshot
after4_audit/c05_done_dialog.png shows the mixed case. It includes the fixes (sorting, position line on its own, truncation list, Chinese reason) and the must-fix (unreadable failure line).
