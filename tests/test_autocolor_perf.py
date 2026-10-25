"""R18：自動調色在長片的耗時與快取；慢動作分段使用同一組調色。"""
import os, sys, time, tempfile, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import core
ff = core.find_ffmpeg(); d = tempfile.mkdtemp(); src = os.path.join(d, "long.mp4")
# 10 分鐘 低解析 (g=300)：測尾端 seek 不會變慢
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=600", "-c:v", "libx264",
                "-preset", "ultrafast", "-g", "300", "-pix_fmt", "yuv420p", src], check=True)
ts = {}
for t in (5, 300, 590):
    t0 = time.time(); core.auto_enhance_filter(src, t, t + 4); ts[t] = time.time() - t0
t0 = time.time(); core.auto_enhance_filter(src, 590, 594); hit = time.time() - t0
print("auto colour s", {k: round(v, 2) for k, v in ts.items()}, "cached", round(hit, 4))
assert ts[590] < max(1.5, ts[5] * 3), ts      # 尾端不會因長度變慢
assert hit < 0.01
print("AUTOCOLOR PERF OK")
