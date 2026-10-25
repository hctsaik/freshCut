"""R16：文字效果（霓虹/標籤/電影）、文字動畫（上滑/放大）與貼圖真的出現在輸出畫面的指定位置。"""
import os, sys, tempfile, subprocess
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
try:
    from PySide6.QtGui import QGuiApplication
except ImportError:
    print("SKIP: 沒有 PySide6（文字效果用 Qt 繪製）"); sys.exit(0)
from app import core, smart
app = QGuiApplication([])
ff = core.find_ffmpeg(); d = tempfile.mkdtemp()
src = os.path.join(d, "a.mp4")      # 純灰畫面，任何疊加都容易量到
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x180:d=6:r=30", "-f", "lavfi", "-i",
                "sine=d=6", "-shortest", "-pix_fmt", "yuv420p", src], check=True)


def frame(path, t, W=640, H=360):
    raw = subprocess.run([ff, "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1", "-s", f"{W}x{H}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(int)


st = smart.render_sticker_png("❤️", os.path.join(d, "s.png"))
assert st and os.path.getsize(st) > 500
segs = [core.Segment(src, 0, 6, 1)]
res = {}
for style, anim in (("霓虹", "上滑"), ("標籤", "放大"), ("電影", "淡入")):
    W, H = core.out_size("16:9", "1080p")
    png = smart.render_title_png("墾丁三日", "2026", W, H, os.path.join(d, f"t_{style}.png"), style=style)
    out = os.path.join(d, f"o_{style}.mp4")
    o = core.ExportOptions(crossfade=0, fade_out=0, title="墾丁三日", subtitle="2026", title_png=png,
                           title_style=style, title_anim=anim, stickers=[(st, "右上")])
    core.export(segs, out, o)
    f1, f5 = frame(out, 1.2), frame(out, 5.0)
    res[style] = (f1, f5)
    # 片頭只在前 3 秒：中央在 1.2 秒有變化、5 秒時回到灰
    c1 = np.abs(f1[140:220, 220:420] - 128).mean(); c5 = np.abs(f5[140:220, 220:420] - 128).mean()
    # 貼圖在右上角整片都在
    k5 = np.abs(f5[10:70, 540:630] - 128).mean(); kL = np.abs(f5[10:70, 10:100] - 128).mean()
    print(style, anim, "center@1.2", round(c1, 1), "center@5", round(c5, 1), "sticker TR", round(k5, 1), "TL", round(kL, 1))
    assert c1 > 8 and c5 < 4, (style, c1, c5)
    assert k5 > 10 and kL < 4, (style, k5, kL)
# 各風格長得不一樣：標籤＝黃底（R、G 高 B 低），霓虹＝青色光暈，電影＝上下黑邊
f = res["標籤"][0][140:220, 220:420]; yellow = ((f[..., 0] > 200) & (f[..., 1] > 150) & (f[..., 2] < 80)).mean()
g = res["霓虹"][0][120:240, 150:490]; cyan = ((g[..., 2] - g[..., 0]) > 40).mean()
m = res["電影"][0]; bars = m[:20, :400].mean() < 30 and m[-20:, :400].mean() < 30
print("yellow", round(yellow, 2), "cyan", round(cyan, 2), "bars", bars)
assert yellow > 0.08 and cyan > 0.03 and bars
# 上滑：0.1 秒時文字比 1.2 秒低（重心往下）
W, H = core.out_size("16:9", "1080p")
out = os.path.join(d, "o_up.mp4"); png = smart.render_title_png("ABC", "", W, H, os.path.join(d, "u.png"), style="標籤")
core.export(segs, out, core.ExportOptions(crossfade=0, fade_out=0, title="ABC", title_png=png, title_style="標籤", title_anim="上滑"))
def cy(fr):
    msk = (fr[..., 0] > 180) & (fr[..., 2] < 90); ys = np.nonzero(msk)[0]; return ys.mean() if len(ys) else None
y0, y1 = cy(frame(out, 0.25)), cy(frame(out, 1.2)); print("slide-up centroid", y0, y1)
assert y0 is not None and y1 is not None and y0 > y1 + 3
if os.environ.get("FX_SHOT"):
    subprocess.run([ff, "-y", "-v", "error", "-ss", "1.2", "-i", os.path.join(d, "o_霓虹.mp4"), "-frames:v", "1", os.environ["FX_SHOT"]])
print("TEXT FX OK")
