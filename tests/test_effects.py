"""R23：特效模板（節拍放大／閃白／故障）。輸出後在觸發點附近取幀，確認畫面真的有變化，而且離觸發點遠的地方不變。"""
import os, sys, tempfile, subprocess
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import core

ff = core.find_ffmpeg(); root = tempfile.mkdtemp(); src = os.path.join(root, "src.mp4")
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=duration=6:size=640x360:rate=30",
                "-f", "lavfi", "-i", "sine=duration=6", "-shortest", "-pix_fmt", "yuv420p", src], check=True)

def frame(path, t):
    r = subprocess.run([ff, "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-s", "160x90",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(90, 160, 3).astype(float)

assert core.effect_filter("", [1], 640, 360) == "" and core.effect_filter("閃白", [], 640, 360) == ""
assert len(core.effect_filter("故障", list(range(500)), 640, 360)) < 20000   # 觸發點有上限
try:
    core.effect_filter("不存在", [1], 640, 360); raise SystemExit("未知特效要報錯")
except ValueError:
    pass
seg = [core.Segment(src, 0, 4, 1.0)]
base = os.path.join(root, "base.mp4")
o = dict(resolution="1080p", aspect="16:9", crossfade=0, fade_out=0)
core.export(seg, base, core.ExportOptions(**o, look=""))
T = 2.0
for name in core.EFFECTS[1:]:
    out = os.path.join(root, f"{name}.mp4")
    core.export(seg, out, core.ExportOptions(**o, effect=name, effect_times=[T]))
    assert abs(core.probe(out).duration - 4.0) < 0.15, name
    near = np.abs(frame(out, T + 0.034) - frame(base, T + 0.034)).mean()
    far = np.abs(frame(out, 3.5) - frame(base, 3.5)).mean()
    print(name, "diff near", round(near, 1), "far", round(far, 1))
    assert near > 6 and far < 2.5, (name, near, far)
# 沒給拍點時用剪接點；兩段 → 應能正常輸出
out = os.path.join(root, "cuts.mp4")
core.export([core.Segment(src, 0, 2, 1), core.Segment(src, 3, 5, 1)], out,
            core.ExportOptions(**o, effect="閃白"))
print("EFFECTS OK")

# R24：貼圖自訂位置＋動畫
from app import smart
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtGui import QGuiApplication; _qapp = QGuiApplication([])
except ImportError:
    _qapp = None
png = smart.render_sticker_png("⭐", os.path.join(root, "st.png")) if hasattr(smart, "render_sticker_png") else None
assert core.sticker_xy((0.3, 0.6))[0].startswith("clip(W*0.3000")
assert "exp(-5*t)" in core.sticker_xy("右上", "彈跳")[1] and "sin(" in core.sticker_xy((2, -1), "浮動")[1]
if png:   # 需要 Qt 才畫得出貼圖
    for anim in core.STICKER_ANIMS:
        out = os.path.join(root, f"st_{anim}.mp4")
        core.export(seg, out, core.ExportOptions(**o, stickers=[(png, (0.25, 0.5), anim)]))
        d = np.abs(frame(out, 3.0) - frame(base, 3.0)).mean(axis=2)
        ys, xs = np.nonzero(d > 40)
        cx, cy = xs.mean() / 160, ys.mean() / 90
        print("sticker", anim, round(cx, 2), round(cy, 2))
        assert abs(cx - 0.25) < 0.05 and abs(cy - 0.5) < 0.06, (anim, cx, cy)
    # 彈跳：開頭貼圖在較高位置
    d = np.abs(frame(os.path.join(root, "st_彈跳.mp4"), 0.05) - frame(base, 0.05)).mean(axis=2)
    ys, _ = np.nonzero(d > 40); assert len(ys) == 0 or ys.mean() / 90 < 0.42, ys.mean() / 90
    print("STICKER POS OK")
    # R28：兩張貼圖同時出現在各自位置
    out = os.path.join(root, "st_two.mp4")
    core.export(seg, out, core.ExportOptions(**o, stickers=[(png, (0.2, 0.3), "無"), (png, (0.8, 0.7), "無")]))
    d = np.abs(frame(out, 3.0) - frame(base, 3.0)).mean(axis=2)
    ys, xs = np.nonzero(d > 40); L = xs < 80
    assert L.any() and (~L).any()
    assert abs(xs[L].mean() / 160 - 0.2) < 0.05 and abs(ys[L].mean() / 90 - 0.3) < 0.06
    assert abs(xs[~L].mean() / 160 - 0.8) < 0.05 and abs(ys[~L].mean() / 90 - 0.7) < 0.06
    print("TWO STICKERS OK")
else:
    print("SKIP sticker render (no Qt)")

# R29：特效預覽條（4 格），觸發格要和前一格明顯不同
import subprocess as _sp
assert core.effect_preview("", os.path.join(root, "x.png")) is None
still = os.path.join(root, "still.png")
_sp.run([core.find_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360", "-frames:v", "1", still], check=True)
for name in [e for e in core.EFFECTS if e]:
    pv = core.effect_preview(name, os.path.join(root, f"pv_{name}.png"), img=still)   # 靜止畫面：差異只來自特效
    raw = _sp.run([core.find_ffmpeg(), "-v", "error", "-i", pv, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.uint8)
    h = 108; w4 = a.size // 3 // h; a = a.reshape(h, w4, 3).astype(float)
    cells = [a[:, i * 194:i * 194 + 192] for i in range(4)]   # 每格 192 寬＋2 間隔
    diff = np.abs(cells[1] - cells[0]).mean()
    late = np.abs(cells[3] - cells[0]).mean()   # 0.15 秒後正在減弱
    print("preview", name, w4, round(diff, 1), round(late, 1))
    assert w4 >= 192 * 4 and diff > 3 and late < diff * 0.6, (name, diff, late)
print("EFFECT PREVIEW OK")
