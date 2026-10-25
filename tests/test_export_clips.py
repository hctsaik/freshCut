"""R65：已選片段各自匯出（不合併、不加音樂）＋策略開關。"""
import os, sys, tempfile, subprocess, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from app import core

ff = core.find_ffmpeg(); d = tempfile.mkdtemp()
src = os.path.join(d, "VID_20240825_023257_349.mp4")
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=8:r=30", "-f", "lavfi", "-i",
                "sine=d=8", "-shortest", "-pix_fmt", "yuv420p", src], check=True)
# 檔名
n = core.clip_filename(src, 12.5, 19.0, ["people", "action"])
assert n == "VID_20240825_023257_349_0m12_5s-0m19_0s_people+action.mp4", n
assert core.clip_filename("a:b.mp4", 0, 1, None).endswith("_manual.mp4")
out = os.path.join(d, "out")
items = [(core.Segment(src, 0, 3, 1), ["start"]), (core.Segment(src, 4, 7, 1), ["middle"]),
         (core.Segment(os.path.join(d, "nope.mp4"), 0, 2, 1), ["action"])]
opts = core.ExportOptions(); opts.music = "/nonexistent.mp3"; opts.crossfade = 0.5
prog = []
res = core.export_clips(items, out, opts, progress=lambda f, m: prog.append(f))
assert res[0][0] and res[1][0] and res[2][0] is None and res[2][1], res
assert opts.music == "/nonexistent.mp3", "不可改到呼叫者的 opts"
for p, _ in res[:2]:
    du = core.probe(p).duration
    assert 2.5 < du < 3.6, (p, du)
assert not glob.glob(os.path.join(out, "*.part*")), "不可留下 .part"
assert prog and prog[-1] == 1.0
# 同名不覆蓋
res2 = core.export_clips(items[:1], out, None)
assert res2[0][0].endswith("_start_2.mp4"), res2
# 取消：丟 Cancelled、已完成的保留
k = {"n": 0}
def cancel():
    k["n"] += 1; return k["n"] > 1
try:
    core.export_clips(items[:2], os.path.join(d, "c"), None, cancel=cancel); raise SystemExit("no cancel")
except core.Cancelled:
    pass
assert not glob.glob(os.path.join(d, "c", "*.part*"))
# 策略開關：只開 people 時只會有 people 候選
class F: pass
f = F(); T = 40; f.times = np.arange(T) * 0.5
for a in ("person", "near", "shake", "motion", "sharp", "peak", "audio"):
    setattr(f, a, np.random.RandomState(1).rand(T))
f.score = np.random.RandomState(2).rand(T); f.focus_x = np.full(T, .5); f.thumbs = []
c_all = core.strategy_candidates(f, src, 20.0)
c_p = core.strategy_candidates(f, src, 20.0, enabled=["people"])
assert len(c_all) >= 2 and len(c_p) == 1 and c_p[0].strategies[0] == "people", ([c.strategies for c in c_all], [c.strategies for c in c_p])
print("test_export_clips OK")
