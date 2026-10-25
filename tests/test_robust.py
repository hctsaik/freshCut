"""R25：真實素材常見的怪格式（合成）：VFR、HEVC、旋轉 metadata、10-bit、單聲道 22.05k、5.1、無音訊、4K。
每種都要能分析出片段並輸出正確尺寸/長度。"""
import os, sys, tempfile, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import core
ff = core.find_ffmpeg(); d = tempfile.mkdtemp()
def mk(name, vargs, aargs=("-f", "lavfi", "-i", "sine=d=8"), size="640x360", rate=30, post=()):
    p = os.path.join(d, name)
    cmd = [ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=d=8:s={size}:r={rate}", *aargs,
           *vargs, *(["-shortest"] if aargs else []), *post, p]
    subprocess.run(cmd, check=True); return p
cases = {
    "vfr": mk("vfr.mp4", ["-vf", "setpts='if(lt(N,60),PTS,PTS*1.7)'", "-fps_mode", "vfr", "-pix_fmt", "yuv420p"]),
    "hevc": mk("hevc.mp4", ["-c:v", "libx265", "-x265-params", "log-level=error", "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]),
    "10bit": mk("10bit.mov", ["-c:v", "libx265", "-x265-params", "log-level=error", "-pix_fmt", "yuv420p10le"]),
    "mono22k": mk("mono.mp4", ["-pix_fmt", "yuv420p", "-ar", "22050", "-ac", "1"]),
    "surround": mk("51.mp4", ["-pix_fmt", "yuv420p", "-ac", "6", "-c:a", "aac"]),
    "noaudio": mk("na.mp4", ["-pix_fmt", "yuv420p"], aargs=()),
    "4k": mk("4k.mp4", ["-pix_fmt", "yuv420p", "-preset", "ultrafast"], size="3840x2160"),
}
rot = os.path.join(d, "rot.mp4")   # 直拍手機：存成 640x360＋旋轉 90°（顯示為 360x640）
subprocess.run([ff, "-y", "-v", "error", "-display_rotation", "90", "-i", cases["mono22k"], "-c", "copy", rot], check=True)
cases["rotate"] = rot
for k, p in cases.items():
    t = time.time()
    info = core.probe(p)
    if k == "rotate":
        assert (info.width, info.height) == (360, 640), ("旋轉後應是直式", info)
    if k == "noaudio":
        assert not info.has_audio
    segs = core.candidates_for_video(p, 2, 2.0)
    assert segs and all(0 <= s.start < s.end <= info.duration + 0.05 for s in segs), (k, segs)
    out = os.path.join(d, f"o_{k}.mp4")
    core.export(segs, out, core.ExportOptions(resolution="1080p", aspect="9:16" if k == "rotate" else "16:9",
                                              crossfade=0.3, fade_out=0))
    oi = core.probe(out)
    want = (1080, 1920) if k == "rotate" else (1920, 1080)
    assert (oi.width, oi.height) == want and oi.has_audio, (k, oi)
    print(f"{k:9s} probe {info.width}x{info.height} dur {info.duration:.2f} → out {oi.duration:.2f}s  {time.time() - t:.1f}s")
print("ROBUST OK")
