# REPORT v2 — exact in-file ranges (partial: 3 / 95 trimmed picks)

**Status:** the new Drive copy still returns "Quota exceeded" for every mp4 (120 of the 123 Thai_Edited clips are unavailable). Only the 3 clips downloaded earlier could be aligned. Full step 3 (train/val P/R/hit/IoU on exact GT) is **not meaningful with n=3** and was not re-run; the R54 metrics in REPORT.md (uniform-offset expectation) remain current.

## Alignment method
Mapping: Thai_Edited mp4 `creation_time` = source filename time − 9 h − 10 s for all three (consistent rule usable for the other 120), plus length match with rough_cut.json. Exports are 2560×1440 reframed flat views, so pixel hashes vs the 360° LRV don't work directly; used (a) 8 kHz mono audio normalized cross-correlation and (b) 32×32 mean-luma frame-difference cross-correlation at 25 fps. Both agree within 0.04 s.

| clip | source (dur) | user range | audio r | luma r | R54 top cand | IoU |
|---|---|---|---|---|---|---|
| 0124_05 | _341 (13.52 s) | 0.00–5.76 | .987 | .774 | 1.5–8.0 | .53 |
| 018_3 | _004 (13.2 s) | 4.52–12.72 | .952 | .843 | 6.5–13.0 | .73 |
| 019_16 | _099 (37.56 s) | 4.46–12.06 | .983 | .780 | 18.0–24.5 | 0.00 (2nd, optional cand 2–8.5: .40) |

## Observations (n=3, anecdotal)
- Cuts sit in the first third: start offsets 0, 4.5, 4.5 s; user drops the tail (1.5–25 s) more than the head.
- 019_16 (night market, 37 s): kept 4.5–12 s = kid facing camera / pointing at food; dropped part is mostly repetitive browsing. App's top window (18–24.5 s) misses it; its optional 2nd candidate overlaps.
- 018_3 keeps the end of the clip; app's window agrees well.
- Contact sheets: v2/src_<clip>.jpg (source 1 fps, timestamped) and v2/clip_<clip>.jpg (exported pick).

---

# v3 update — all 123 picks aligned (2026-10-25)

**Data:** Full Thai_Edited.zip (4.87 GB, 123 mp4 at 2560×1440 + Insta360 project) downloaded from the Synology share (QuickConnect relay `/fsdownload/<id>/Thai_Edited.zip`, no password). All 123 clips pass ffprobe. Footage stays private and is used only for testing.

**Alignment** (`real_labeled/work/v3/align_all.py`, same method as v2/align.py). Mapping rule: clip creation_time + 9 h 10 s = source filename time. It matched exactly one LRV for all 123 clips.
- 28 untrimmed clips have the same length as their source (0–dur).
- 88 of the 95 trimmed clips: audio and luma-diff offsets agree within 0.2 s (audio r usually >0.95).
- 7 trimmed clips: luma-diff failed (r 0.30–0.54) but audio was strong (r 0.95–0.998). Direct luma correlation at the audio offset beats the luma-diff offset in all 5 clips I checked, so I used the audio offset.
- `ground_truth.json` now has exact start/end for all 123 (`range_method`, `range_confidence`, `thai_edited`). Backup: `ground_truth.backup_pre_v2.json`.

## R54 re-evaluation with exact ranges (`work/r49/metrics_v3.py` on r54.json; burst split seed 49; 240 files; 123 positives: 89 train / 34 val)

| set | P | R | hit | top-cand IoU |
|---|---|---|---|---|
| checked, train | .311 | .434 | .820 | .438 |
| checked, val | .334 | .569 | .853 | .537 |
| kept, train | .330 | .432 | .809 | .427 (top selected cand) |
| kept, val | .343 | .550 | .824 | .508 |
| kept, all (old uniform-offset metric: P .342 R .475 hit .786) | .334 | .464 | .813 | .449 |

The exact ranges hardly change P/R/hit, so the old uniform-offset expectation was a fair stand-in. The new information comes from IoU:

| top-window policy (eval-only) | train IoU (≥.5) | val IoU (≥.5) |
|---|---|---|
| app top candidate | .438 (.43) | .537 (.62) |
| fixed first 6.5 s | .434 (.46) | .479 (.53) |
| **fixed centre 6.5 s** | **.481 (.53)** | **.550 (.59)** |
| whole file if <10 s, else app top | .454 | .555 |
| oracle best of app's cands (~1.6 per file) | .500 | .574 |

**The in-file localisation does no better than a dumb centre window.** Even choosing the best of the app's own candidates every time reaches only about 0.50–0.57, so candidate generation limits IoU as much as ranking does.

## Where the user cuts (95 trimmed)
- **Kept length is nearly constant:** median 6.8 s (P10–P90 5.1–8.8 s), no matter how long the source is. Kept fraction: 0.65 for <10 s sources, 0.46 for 10–20 s, 0.25 for 20–40 s, 0.14 for >40 s.
- **Start:** 27/95 start at 0 s (head kept, tail cut). Median start is 4.5 s, but scaled to source length it is 0.23. Only 6/95 run to the end.
- **Centre position:** median at 0.45 of the source (P25–P75 0.31–0.63). Mid-clip, slightly early. The app's top window centre misses the user's by a median of +1 s, with P25/P75 at −3/+3.5 s.
- **Untrimmed picks** are all short (median 6.4 s, P90 17.6 s). Short clips are kept whole.
- **Kept vs dropped content** (within-file standardised difference of cached features, n=92): kept seconds have more `person` (+0.25, 68% of files) and `near` (+0.27), and less `occ`/occlusion (−0.28) and `motion` (−0.12). The combined `score` barely separates them (+0.11, 61%). `face`/`smile`/`expo` are always 0 in the cached features, so they contribute nothing.
- The contact sheet shows the same pattern. The user drops walk-ups, lens-covered or settling starts, and repetitive browsing tails, and keeps the moment a person or kid is close and facing the camera.

Contact sheet: `v3/contact_cuts.jpg`. 16 trimmed picks sorted by source length; green = user range, red = app top candidate.

## Recommended scoring changes (not applied; app code untouched)
1. **Candidate length:** target about 6.5–7 s. Allow 5–9 s but don't stretch with source length. The current 6.5 s is right.
2. **Short files (<10 s):** propose the whole file, or snap to 0–dur when the window covers more than 60%.
3. **Generate more candidates:** use a 0.5 s stride from t=0 to the end and always include the window that starts at 0. Many picks start at 0, and oracle IoU is capped at about 0.5 today.
4. **Positional prior:** add a mild Gaussian on window centre at about 0.45·dur (σ ≈ 0.25·dur). This prior alone beats the current ranker.
5. **Reweight per-second scores:** raise `person` and `near`, add an `occ` penalty, and lower `motion` within a file. Fix or drop the `face`/`smile` channel, which reads zero everywhere.
6. Make top-candidate IoU (train and val) a tracked metric next to P/R/hit, using `metrics_v3.py`.
