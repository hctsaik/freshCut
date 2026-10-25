"""R27：分析速度。單次解碼（評分＋人臉共用）、平行分析多支影片。量測並確認結果和依序分析一致。"""
import os, sys, tempfile, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import core
from app.library import Library
ff = core.find_ffmpeg(); d = tempfile.mkdtemp(); media = os.path.join(d, "m"); os.makedirs(media)
for i, src in enumerate(["testsrc2", "testsrc", "rgbtestsrc", "smptebars"]):
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"{src}=d=20:s=1280x720:r=30", "-f", "lavfi", "-i",
                    "sine=d=20", "-shortest", "-pix_fmt", "yuv420p", "-preset", "ultrafast", f"{media}/v{i}.mp4"], check=True)
# 呼叫 ffmpeg 次數：人臉開著也只解碼影像一次
calls = []; orig = core._run
core._run = lambda a, **k: (calls.append(a), orig(a, **k))[1]
core.features(f"{media}/v0.mp4")
core._run = orig
vids = [a for a in calls if "-vn" not in a and "-f" in a]
assert len(vids) == 1, f"影像解碼 {len(vids)} 次"
def run(workers):
    lib = Library(os.path.join(d, f"lib{workers}")); lib.add_folder(media, watch=False)
    t = time.time(); lib.analyze_pending(workers=workers, count=3, seg_len=2.0, proxies=False); el = time.time() - t
    res = sorted((c["file_id"], c["start"], round(c["score"], 4)) for f in lib.files() for c in lib.clips(f["id"]))
    return el, res
t1, r1 = run(1); t3, r3 = run(3)
print(f"4 支 720p×20 秒：依序 {t1:.1f}s，3 執行緒 {t3:.1f}s（{os.cpu_count()} CPU）")
assert r1 == r3, "平行與依序結果不同"
# 壞檔在平行模式也只記錄錯誤
open(f"{media}/bad.mp4", "wb").write(b"junk" * 50)
lib = Library(os.path.join(d, "libbad")); lib.add_folder(media, watch=False)
lib.analyze_pending(workers=3, count=2, seg_len=2.0, proxies=False)
errs = [f for f in lib.files() if lib.db.execute("SELECT error FROM files WHERE id=?", (f["id"],)).fetchone()[0]]
assert len(errs) == 1, errs
print("PERF OK")
# 硬體解碼失敗時自動改回軟體解碼
core.HWACCEL = "bogus_accel"; core.DECODE_STATS.clear() if hasattr(core.DECODE_STATS, "clear") else None
f = core.features(f"{media}/v1.mp4"); assert f is not None
print("HWACCEL fallback OK", core.DECODE_STATS)
