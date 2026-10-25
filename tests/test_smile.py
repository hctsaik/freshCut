"""R19：笑臉偵測在分析解析度（320×180）下的準確度。s_* = 露齒笑，n_* = 不笑；每張 3 種臉大小。"""
import os, sys, glob, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from app import core, faces
if not faces.has_cv():
    print("SKIP test_smile：沒有安裝 opencv-python-headless"); sys.exit(0)
ff = core.find_ffmpeg()
def load(p, scale):
    raw = subprocess.run([ff, "-v", "error", "-i", p, "-vf", f"scale=-2:{int(180 * scale)},pad=320:180:(ow-iw)/2:(oh-ih)/2:color=gray,"
                          "format=gray", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(180, 320)
tp = fp = P = N = 0
for p in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "data", "smile", "*.jpg"))):
    lab = os.path.basename(p).startswith("s_")
    for sc in (1.0, 0.8, 0.6):
        f, s, _ = faces.detect(load(p, sc)[None]); hit = s[0] > 0.5
        P += lab; N += not lab; tp += lab and hit; fp += (not lab) and hit
print(f"smile TPR {tp}/{P}  FPR {fp}/{N}")
assert P == 12 and N == 12
assert tp >= 9 and fp <= 1, (tp, fp)      # R18 以前：TPR 0/12（320×180 下從未偵測到）
print("SMILE OK")
