"""R39–R41：魚眼跟拍路徑、水平（IMU）、構圖、sendcmd。真實樣本不在就略過那幾項。"""
import os, sys, tempfile, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from app import fisheye as F, core, library

def test_plan():
    tr = [(t / 5, 10.0 + (0.5 if t % 2 else -0.5), 20.0, -40.0, 0.8) for t in range(20)]
    pts = F.plan(tr, 1080, 1920, 190, 125, 4.0)
    ys = [p[1] for p in pts]
    assert len(pts) == 41 and max(ys) - min(ys) < 1e-6, "deadzone should ignore ±0.5° jitter"
    tr = [(t / 5, 0.0 if t < 10 else 30.0, 20.0, -40.0, 0.8) for t in range(20)]
    ys = [p[1] for p in F.plan(tr, 1080, 1920, 190, 125, 4.0)]
    assert max(abs(b - a) for a, b in zip(ys, ys[1:])) < 8, "eased, no jump"
    assert ys[-1] > 15
    ys = [p[1] for p in F.plan([], 1080, 1920, 190, 125, 2.0, fallback=(5.0, -3.0))]
    assert all(abs(y - 5.0) < 1e-6 for y in ys)

def test_frame_target():
    vf = 100.0
    p = F.frame_target(20, -20, vf)            # 小的人：置中偏上留頭頂
    assert -5 < p < 5
    p = F.frame_target(40, -80, vf)            # 太高：頭留在畫面內
    assert 40 <= p + vf / 2 + 1e-6

def test_sendcmd():
    t = F.sendcmd_text([(0.0, 1, 2, 3), (0.1, 4, 5, 6)])
    lines = t.strip().split("\n")
    assert len(lines) == 2 and lines[0].endswith("reset_rot 1;") and "roll 3.00" in lines[0]

def test_no_imu():
    d = tempfile.mkdtemp(); p = os.path.join(d, "x.mp4")
    subprocess.run([core.find_ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "testsrc=s=320x320:d=1", p], check=True)
    assert F.read_imu(p) is None and F.roll_series(p, 0, 1) is None

def test_roll_manual_kv():
    lib = library.Library(tempfile.mkdtemp())
    lib.set_roll(7, 12.5); assert lib.get("roll:7") == 12.5
    lib.set_roll(7, None); assert lib.get("roll:7") is None

REAL = "/tmp/real/a1.lrv"
def test_real_imu():
    if not os.path.exists(REAL):
        print("skip real"); return
    imu = F.read_imu(REAL); assert imu is not None
    rs = F.roll_series(REAL, 1.92, 4.0)
    assert 10 < float(np.median(rs)) < 25, rs
    cam, info = F.camera_path(REAL, 1.92, 4.0, 1080, 1920, 190, 125)
    assert info["roll"] == "imu" and len(cam) == 41

if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("ok", k)
    print("ALL OK")
