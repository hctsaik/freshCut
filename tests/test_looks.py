import os, sys, tempfile, subprocess
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import core

ff = core.find_ffmpeg(); d = tempfile.mkdtemp()
src = os.path.join(d, "dark.mp4")   # 偏暗、低對比、彩色的素材
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=3:r=30",
                "-vf", "eq=brightness=-0.25:contrast=0.5:saturation=0.6", "-pix_fmt", "yuv420p", src], check=True)


def stats(p):
    r = subprocess.run([ff, "-v", "error", "-ss", "1.5", "-i", p, "-frames:v", "1", "-vf", "scale=64:36",
                        "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], capture_output=True)
    px = np.frombuffer(r.stdout, np.uint8).reshape(-1, 3).astype(float) / 255
    y = px @ [0.299, 0.587, 0.114]
    return y.mean(), y.std(), (px.max(1) - px.min(1)).mean()


f = core.auto_enhance_filter(src, 0, 3); print("auto:", f); assert f.startswith("eq=")
seg = [core.Segment(src, 0, 3, 1)]
res = {}
for name, opts in {"orig": None, "auto": dict(auto_enhance=True), "黑白": dict(look="黑白"),
                   "鮮豔": dict(look="鮮豔"), "電影": dict(look="電影"), "暖色": dict(look="暖色")}.items():
    if opts is None:
        res[name] = stats(src); continue
    out = os.path.join(d, f"{name}.mp4")
    core.export(seg, out, core.ExportOptions(crossfade=0, fade_out=0, keep_original_audio=False, **opts))
    res[name] = stats(out)
for k, v in res.items():
    print(k, "mean %.3f std %.3f sat %.3f" % v)
o = res["orig"]
assert res["auto"][0] > o[0] + 0.05 and res["auto"][1] > o[1], "自動優化要讓偏暗素材變亮、對比變高"
assert res["黑白"][2] < 0.03
assert res["鮮豔"][2] > o[2] * 1.1
assert all(core.look_filter(k) or k == "" for k in core.LOOKS)
# 分享預設的音量標準化：量測整合響度應接近 -14 LUFS
asrc = os.path.join(d, "loud.mp4")
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=6:r=30", "-f", "lavfi", "-i",
                "sine=f=440:d=6,volume=0.05", "-shortest", "-pix_fmt", "yuv420p", asrc], check=True)
outl = os.path.join(d, "ln.mp4")
core.export([core.Segment(asrc, 0, 6, 1)], outl, core.ExportOptions(crossfade=0, fade_out=0, loudnorm=True))
r = subprocess.run([ff, "-hide_banner", "-i", outl, "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True)
import re
I = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)[-1]); print("integrated loudness", I)
assert -16 < I < -12, I
# R12：.cube LUT（反轉色）＋濾鏡預覽；路徑含空白與中文
lutd = os.path.join(d, "我的 LUT"); os.makedirs(lutd, exist_ok=True); cube = os.path.join(lutd, "invert.cube")
with open(cube, "w") as f:
    f.write("TITLE \"inv\"\nLUT_3D_SIZE 2\n")
    for b in (0, 1):
        for g in (0, 1):
            for r_ in (0, 1):
                f.write(f"{1-r_} {1-g} {1-b}\n")
assert core.parse_cube(cube) == 2
bad = os.path.join(d, "bad.cube"); open(bad, "w").write("LUT_3D_SIZE 4\n0 0 0\n")
try:
    core.parse_cube(bad); raise SystemExit("bad cube accepted")
except ValueError as e:
    print("bad cube rejected:", e)
red = os.path.join(d, "red.mp4")
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=160x90:d=1", "-pix_fmt", "yuv420p", red], check=True)
import numpy as _np
def _px(png):   # 不依賴 PIL：用 ffmpeg 解成 rgb24
    r = subprocess.run([ff, "-v", "error", "-i", png, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    return _np.frombuffer(r.stdout, _np.uint8).reshape(-1, 3).astype(float)
p0 = core.preview_look(red, 0.5, "", False, os.path.join(d, "p0.png"))
p1 = core.preview_look(red, 0.5, "lut:" + cube, False, os.path.join(d, "p1.png"))
m0 = _px(p0).mean(0); m1 = _px(p1).mean(0)
print("red preview", m0.round(), "-> LUT", m1.round())
assert m0[0] > 200 and m1[0] < 60 and m1[1] > 180, "LUT 沒有作用"
pb = core.preview_look(red, 0.5, "黑白", False, os.path.join(d, "p2.png"))
m2 = _px(pb).std(1).mean(); assert m2 < 3, m2
print("LOOKS OK")
