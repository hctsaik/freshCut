"""R37：MP4＋同名 LRV → 用 LRV 分析/預覽、MP4 輸出（量測加速）；flat/equirect/雙魚眼偵測；只有 LRV 時標低解析來源。"""
import os, sys, tempfile, subprocess, time, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from app import core
from app.library import Library
ff = core.find_ffmpeg(); d = tempfile.mkdtemp(); m = os.path.join(d, "DCIM", "Camera01"); os.makedirs(m)
def mk(src, size, out, dur=10):
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"{src}=d={dur}:s={size}:r=30", "-pix_fmt", "yuv420p", "-f", "mp4", out], check=True)
# 1) 平面 MP4＋LRV 一組
mk("testsrc2", "1920x1080", f"{m}/VID_20261001_100000_00_001.mp4"); mk("testsrc2", "480x270", f"{m}/LRV_20261001_100000_01_001.lrv")
# 2) equirect 2:1 MP4＋LRV
mk("testsrc2", "1920x960", f"{m}/VID_20261001_110000_00_002.mp4"); mk("testsrc2", "512x256", f"{m}/LRV_20261001_110000_01_002.lrv")
# 3) 雙魚眼 MP4：兩個圓形畫面、四角黑
fish = f"{m}/VID_20261001_120000_00_003.mp4"
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=d=10:s=1920x960:r=30", "-vf",
                "geq=lum='if(lt(hypot(mod(X\\,W/2)-W/4\\,Y-H/2)\\,H/2-4)\\,lum(X\\,Y)\\,0)':cb=128:cr=128",
                "-pix_fmt", "yuv420p", "-f", "mp4", fish], check=True)
# 4) 只有 LRV
mk("smptebars", "480x270", f"{m}/LRV_20261001_130000_01_004.lrv")
# 5) LRV 長度不符（不是同一段）→ 不採用
mk("testsrc2", "1280x720", f"{m}/VID_20261001_140000_00_005.mp4", 10); mk("testsrc2", "320x180", f"{m}/LRV_20261001_140000_01_005.lrv", 4)

assert core.classify_projection(1920, 1080) == "" and core.classify_projection(1920, 960) == "equirect"
assert core.detect_projection(f"{m}/VID_20261001_100000_00_001.mp4") == ""
assert core.detect_projection(f"{m}/VID_20261001_110000_00_002.mp4") == "equirect"
assert core.detect_projection(fish) == "dfisheye", core.detect_projection(fish)
assert core.detect_projection("x.insv") == "dfisheye"

lib = Library(os.path.join(d, "lib")); lib.add_folder(os.path.join(d, "DCIM"), watch=False)
F = {os.path.basename(f["path"]): f["id"] for f in lib.files()}
assert len(F) == 5, F
assert set(F) == {"VID_20261001_100000_00_001.mp4", "VID_20261001_110000_00_002.mp4", "VID_20261001_120000_00_003.mp4",
                  "LRV_20261001_130000_01_004.lrv", "VID_20261001_140000_00_005.mp4"}
src = {k: os.path.basename(lib.analysis_source(v)) for k, v in F.items()}
assert src["VID_20261001_100000_00_001.mp4"].startswith("LRV_") and src["VID_20261001_110000_00_002.mp4"].startswith("LRV_")
assert src["VID_20261001_140000_00_005.mp4"].startswith("VID_"), "長度不符的 LRV 不能用"
assert lib.low_res(F["LRV_20261001_130000_01_004.lrv"]) and not lib.low_res(F["VID_20261001_100000_00_001.mp4"])
assert lib.projection(F["VID_20261001_110000_00_002.mp4"]) == "equirect" and lib.projection(F[os.path.basename(fish)]) == "dfisheye"

# 量測：同一支用 MP4 vs LRV 分析
mp4 = f"{m}/VID_20261001_100000_00_001.mp4"; lrv = f"{m}/LRV_20261001_100000_01_001.lrv"
t = time.time(); core.candidates_for_video(mp4, 4, 2.0); t_mp4 = time.time() - t
t = time.time(); core.candidates_for_video(lrv, 4, 2.0); t_lrv = time.time() - t
print(f"analysis 1080p MP4 {t_mp4:.2f}s vs LRV {t_lrv:.2f}s → x{t_mp4 / max(t_lrv, 1e-3):.1f}")
assert t_lrv < t_mp4, "LRV 應該比較快"

lib.analyze_pending(count=2, seg_len=2.0)
fid = F["VID_20261001_100000_00_001.mp4"]
f = next(x for x in lib.files() if x["id"] == fid)
assert (f["width"], f["height"]) == (1920, 1080), "檔案資訊要記 MP4 的原始解析度"
c = next(r for r in lib.clip_rows() if r["file_id"] == fid)
assert core.probe(c["proxy"]).width <= 640 and os.path.exists(c["thumb"])
assert all(r["file_id"] in F.values() for r in lib.clip_rows())
assert any(r["file_id"] == F["LRV_20261001_130000_01_004.lrv"] for r in lib.clip_rows()), "只有 LRV 也要能用"
# 輸出：路徑仍是 MP4（高解析）
seg = core.Segment(c["path"], c["start"], c["end"])
assert c["path"].endswith(".mp4")
out = os.path.join(d, "o.mp4")
core.export([seg], out, core.ExportOptions(aspect="16:9", resolution="1080p", crossfade=0, music="", projection="auto", hw_encode=False))
assert core.probe(out).width == 1920
# equirect：自動 → v360 攤平，9:16 也能輸出
ce = next(r for r in lib.clip_rows() if r["file_id"] == F["VID_20261001_110000_00_002.mp4"])
out2 = os.path.join(d, "e.mp4")
se = core.Segment(ce["path"], ce["start"], ce["end"]); se.track = json.loads(ce["track"] or "null")
core.export([se], out2,
            core.ExportOptions(aspect="9:16", resolution="1080p", crossfade=0, music="", projection="auto", reframe="smart", hw_encode=False))
i2 = core.probe(out2); assert (i2.width, i2.height) == (1080, 1920), (i2.width, i2.height)
print("LRV OK")
