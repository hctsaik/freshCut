# Real-user labeled eval (Thai trip, Insta360) — 2026-10-25
Data: /workspace/real_labeled (source/ 240 LRV complete; source_mp4/ 16 full-res originals; Thai_Edited/未命名1 project files)
Ground truth: /workspace/real_labeled/ground_truth.json (123 picks; from Insta360 Studio rough_cut.json + filename)
Eval: /workspace/real_labeled/eval.json (scripts in /workspace/real_labeled/work/)
- 123/240 source files picked. 28 picks use the whole file (exact range). 95 picks are trimmed copies (median 6.7s kept out of a median ~16s source), but the trimmed media were not shared, so the offset is unknown. Metrics give lower, upper, and expected values under a uniform-offset assumption.
- App candidates_for_video(count=4, seg_len=4): recommended-second precision is 0.19–0.32 (expected 0.25; random baseline 0.18). Recall is 0.44–0.77 (expected 0.61). Range hit rate is 0.83–1.0 (expected 0.96). On the exact subset, recall is 0.68 and hits are 1.0.
- 41% of recommended seconds land in files the user dropped. File-level AUC is 0.59 for the AI max score and 0.69 for plain duration.
- BUG: features() crashes on clips under about 2.5s (core.py:376: the smoothing convolve 'same' with k=5 is longer than n). It fails on 7 files, including picked 002.
