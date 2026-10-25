"""R26：手動速度曲線。離散化、atempo 串接、輸出長度符合預估、音訊同步長度、資料庫保存。"""
import os, sys, tempfile, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import core, smart
from app.library import Library
P = smart.curve_pieces(0, 4, [1, 1, 0.4, 1, 1])
assert P[0][2] == 1.0 and min(p[2] for p in P) <= 0.6 and abs(P[-1][1] - 4) < 1e-6, P
assert all(abs(a[1] - b[0]) < 1e-6 for a, b in zip(P, P[1:]))          # 無縫
assert smart.curve_pieces(0, 4, None) == [(0, 4, 1.0)]
assert smart.curve_pieces(0, 4, [2] * 5) == [(0, 4, 2.0)]                # 等速合併成一段
assert smart.atempo_chain(0.25) == "atempo=0.5,atempo=0.5" and smart.atempo_chain(2) == "atempo=2"
assert smart.clamp_speed(10) == 4.0 and smart.clamp_speed(0.01) == 0.25
ff = core.find_ffmpeg(); d = tempfile.mkdtemp(); src = os.path.join(d, "a.mp4")
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=d=8:s=640x360:r=30", "-f", "lavfi", "-i",
                "sine=d=8", "-shortest", "-pix_fmt", "yuv420p", src], check=True)
for curve in ([2.0, 1.0, 0.5, 1.0, 2.0], [0.25] * 5, [4.0] * 5):
    s = core.Segment(src, 1, 5, 1.0); s.curve = curve
    want = smart.curve_length(1, 5, curve)
    out = os.path.join(d, "o.mp4")
    core.export([s], out, core.ExportOptions(resolution="1080p", crossfade=0, fade_out=0))
    got = core.probe(out).duration
    print("curve", curve, "want", round(want, 2), "got", round(got, 2))
    assert abs(got - want) < 0.25, (curve, want, got)
# prepare 不會在有手動曲線的片段上再加自動慢動作
s = core.Segment(src, 1, 5, 1.0); s.curve = [1, 1, 0.5, 1, 1]; s.peak = 3
segs, _ = smart.prepare([s], None, slowmo=0.5); assert getattr(segs[0], "ramp", None) is None
# 資料庫保存
lib = Library(os.path.join(d, "lib")); fid = lib.add_files([src])[0]; lib.analyze(fid, count=1, seg_len=3, proxies=False)
cid = lib.clips(fid)[0]["id"]; lib.set_checked(cid, True)
lib.set_speed(cid, [1, 1, 9, 1, 1]); seg = [x for x in lib.timeline_segments()][0]
assert seg.curve == [1, 1, 4.0, 1, 1], seg.curve
lib.set_speed(cid, None); assert not hasattr(lib.timeline_segments()[0], "curve")
try:
    lib.set_speed(cid, [1, 2]); raise SystemExit("點數不對要報錯")
except ValueError:
    pass
print("SPEED OK")
