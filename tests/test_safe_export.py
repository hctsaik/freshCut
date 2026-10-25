"""REVIEW_r10 B1：輸出取消或失敗時，原本同名的檔案必須原封不動；不留 .part 暫存檔。"""
import os, sys, tempfile, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import core

ff = core.find_ffmpeg(); d = tempfile.mkdtemp()
src = os.path.join(d, "a.mp4")
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=8:r=30", "-f", "lavfi", "-i",
                "sine=d=8", "-shortest", "-pix_fmt", "yuv420p", src], check=True)
out = os.path.join(d, "existing.mp4"); data = b"USER DATA " * 1000
open(out, "wb").write(data)
segs = [core.Segment(src, 0, 4, 1), core.Segment(src, 4, 8, 1)]
# 1) 中途取消
n = {"c": 0}
def cancel():
    n["c"] += 1
    return n["c"] > 3
try:
    core.export(segs, out, core.ExportOptions(), cancel=cancel); raise SystemExit("cancel not raised")
except core.Cancelled:
    pass
assert open(out, "rb").read() == data, "取消後原檔被改動"
# 2) 失敗（來源不存在）
try:
    core.export([core.Segment(os.path.join(d, "nope.mp4"), 0, 2, 1)], out, core.ExportOptions())
    raise SystemExit("bad export succeeded")
except Exception as e:  # noqa: BLE001
    if isinstance(e, SystemExit):
        raise
assert open(out, "rb").read() == data, "失敗後原檔被改動"
assert not [f for f in os.listdir(d) if ".part" in f], os.listdir(d)
# 3) 成功才覆蓋
core.export(segs, out, core.ExportOptions(crossfade=0))
assert open(out, "rb").read(4) != data[:4] and core.probe(out).duration > 7
print("SAFE EXPORT OK")
