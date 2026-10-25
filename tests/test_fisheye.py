"""R38：單一圓形魚眼（方形畫面＋黑角）偵測、攤平、雜湊檔名的 LRV/MP4 配對、真實樣本（沒有就跳過）。"""
import os, sys, tempfile, time, subprocess
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import core, library

A = "/home/box/agent-data/agents/e27dc066-7cf9-49b2-abe8-59a8c1fc56ba/attachments/"
REAL_LRV = os.environ.get("IE_REAL_LRV", A + "d28fe8b6da433c5288adde4cea491e77828763ca8316773aac3a4606f9a7a1d3.lrv")
REAL_MP4 = os.environ.get("IE_REAL_MP4", A + "067029c71dffa4e13e0612d5754e0925979bb0b03b4e0f69b4903e64f160e53d.mp4")


def disc(n=64, r=0.48, bright=180):
    yy, xx = np.mgrid[0:n, 0:n]
    return np.where(np.hypot((xx + .5) / n - .5, (yy + .5) / n - .5) < r, bright, 5).astype(np.uint8)


def test_classify():
    assert core.is_circular_fisheye(disc())
    assert core.classify_projection(640, 640, disc()) == "fisheye"
    assert core.classify_projection(640, 640, np.full((64, 64), 150, np.uint8)) == ""   # 一般方形影片
    assert core.classify_projection(1920, 1080, disc()) == ""


def test_view_and_clamp():
    v = core.fisheye_view(1920, 1080, 0.5, 0.5, fov=190, view=125)
    assert "input=fisheye" in v and "h_fov=125.0" in v and "yaw=0.0" in v
    far = core.fisheye_view(1080, 1920, 1.0, 0.0, fov=190, view=125)   # 主體在最邊緣：yaw/pitch 被限制
    yaw = float(far.split("yaw=")[1].split(":")[0]); pitch = float(far.split("pitch=")[1].split(":")[0])
    assert 0 < yaw <= 190 / 2 and pitch > 0 and pitch <= 190 / 2 - 125 / 2


def test_same_recording():
    a = {"dur": 5.92, "w": 640, "h": 640, "fps": 25.0, "ctime": "2025-02-02T07:48:06.000000Z"}
    b = dict(a, w=2688, h=2688, ctime="2025-02-02T07:48:05.000000Z")
    assert core.same_recording(a, b)
    assert not core.same_recording(a, dict(b, dur=6.5))
    assert not core.same_recording(a, dict(b, ctime="2025-02-02T08:00:00Z"))
    assert not core.same_recording(a, dict(b, w=3840, h=1920))
    assert not core.same_recording(a, dict(b, ctime=None))
    assert not core.same_recording(a, dict(a))   # 同解析度不是代理檔


def _mk(path, size, ct):
    ff = core.find_ffmpeg()
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=s={size}:r=25:d=3",
                    "-vf", "format=yuv420p,geq=lum='if(lt(hypot(X-W/2,Y-H/2),W*0.47),lum(X,Y),0)':cb=128:cr=128",
                    "-metadata", f"creation_time={ct}", "-c:v", "libx264", "-preset", "ultrafast", "-f", "mp4", path], check=True)


def test_hashed_pairing_and_dewarp():
    d = tempfile.mkdtemp()
    lrv, mp4 = os.path.join(d, "aa11.lrv"), os.path.join(d, "ff99.mp4")
    _mk(lrv, "320x320", "2025-02-02T07:48:06Z"); _mk(mp4, "960x960", "2025-02-02T07:48:05Z")
    other = os.path.join(d, "zz.lrv"); _mk(other, "320x320", "2024-01-01T00:00:00Z")   # 別段錄影：不能併
    lib = library.Library(tempfile.mkdtemp())
    ids = lib.add_files([lrv, mp4, other], find_siblings=False)
    paths = sorted(lib.db.execute("SELECT path FROM files WHERE id=?", (i,)).fetchone()[0] for i in ids)
    assert paths == sorted([mp4, other]), paths
    fid = [i for i in ids if lib.db.execute("SELECT path FROM files WHERE id=?", (i,)).fetchone()[0] == mp4][0]
    assert lib.analysis_source(fid) == lrv
    assert lib.projection(fid) == "fisheye"
    lib.analyze(fid, proxies=True)
    c = lib.timeline() or [dict(r) for r in lib.db.execute("SELECT * FROM clips WHERE file_id=?", (fid,))]
    pr = [x["proxy"] for x in c if x.get("proxy")]
    if pr:
        i = core.probe(pr[0]); assert abs(i.width / i.height - 16 / 9) < 0.05   # 預覽已攤平成 16:9


def test_real_sample():
    if not (os.path.exists(REAL_LRV) and os.path.exists(REAL_MP4)):
        print("SKIP real sample (檔案不在)"); return
    d = tempfile.mkdtemp()
    os.symlink(REAL_LRV, os.path.join(d, "x.lrv")); os.symlink(REAL_MP4, os.path.join(d, "y.mp4"))
    lib = library.Library(tempfile.mkdtemp())
    ids = lib.add_files([os.path.join(d, "x.lrv"), os.path.join(d, "y.mp4")], find_siblings=False)
    assert len(ids) == 1 and lib.projection(ids[0]) == "fisheye"
    t = time.time(); lib.analyze(ids[0], proxies=False); t1 = time.time() - t
    lib.auto_pick(target=6); segs = lib.timeline_segments()
    assert segs and segs[0].path.endswith("y.mp4")
    o = os.path.join(d, "o.mp4")
    core.export(segs, o, core.ExportOptions(aspect="9:16", projection="auto", crossfade=0))
    i = core.probe(o); assert (i.width, i.height) == (1080, 1920)
    print(f"real sample: LRV 分析 {t1:.2f}s")


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("ok", k)
