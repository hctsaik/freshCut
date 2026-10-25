"""人臉偵測（選用 OpenCV）：有臉的片段分數較高，直式構圖跟著臉走；沒有 OpenCV 就 SKIP。"""
import os, sys, tempfile, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from app import core, faces
if not faces.has_cv():
    print("SKIP test_faces：沒有安裝 opencv-python-headless"); sys.exit(0)
ff = core.find_ffmpeg(); d = tempfile.mkdtemp(); v = os.path.join(d, "f.mp4")
img = os.path.join(os.path.dirname(__file__), "data", "face_pd.jpg")
# 0–6 秒：只有背景；6–12 秒：右側出現人臉（x≈0.75）
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x507090:s=640x360:d=12:r=30", "-loop", "1", "-i", img,
                "-filter_complex", "[1:v]scale=-2:300[f];[0:v][f]overlay=x=480-overlay_w/2:y=30:enable='gte(t,6)'",
                "-t", "12", "-pix_fmt", "yuv420p", v], check=True)
f = core.features(v, 0.5)
fa, fb = f.face[:12].mean(), f.face[12:].mean()
print("face", round(float(fa), 2), round(float(fb), 2), "focus_x", round(float(np.median(f.focus_x[13:])), 2))
assert fa == 0 and fb > 0.3, (fa, fb)
assert f.score[13:].mean() > f.score[:11].mean()
assert abs(np.median(f.focus_x[13:]) - 0.75) < 0.08
g = core.features(v, 0.5, use_faces=False); assert not g.face.any()
print("FACES OK")
