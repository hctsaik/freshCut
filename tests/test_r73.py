"""R73：失敗清單長原因不擠壓檔名（檔名一行、原因下一行可換行）、截短＋失敗並存時標題兩者都寫。離螢幕執行。"""
import faulthandler; faulthandler.dump_traceback_later(600, exit=True)
import os, sys, tempfile, subprocess, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from app import core
root = tempfile.mkdtemp()
# 超出長度的原因夠短、只有中文
ff = core.find_ffmpeg(); src = os.path.join(root, "a.mp4")
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=2",
                "-f", "lavfi", "-i", "sine=duration=2", "-shortest", "-pix_fmt", "yuv420p", src], check=True)
r = core.export_clips([(core.Segment(src, 9999.0, 10003.0), ["start"])], os.path.join(root, "o"),
                      core.ClipOptions(pattern="time", subfolders=False))
assert r[0][0] is None and "超出素材長度" in r[0][1] and len(r[0][1]) <= 24 and "9999" not in r[0][1], r

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from app.gui import clips as C, style as S
S.apply(app)
out = os.path.join(root, "out"); os.makedirs(out)


def mk(n):
    p = os.path.join(out, n); open(p, "wb").write(b"x" * 1000); return p


longreason = "入點／出點超出素材長度（素材 6.00 秒，片段 9999.00–10003.00 秒），而且這是一段刻意寫得很長很長的中文原因用來測試換行"
names = ["VID_20240825_023257_349_精彩動作_01.mp4", "VID_20240825_040617_374_場景變換_02.mp4"]
d = C.ExportDoneDialog(None, [(None, "ClipInvalid: " + longreason), (None, "輸出檔沒有聲音")], names, out, 1)
d.resize(560, 500); d.show(); app.processEvents()
for (nl, rl), n in zip(d.fail_rows, names):
    assert nl.text() == "• " + n, (nl.text(), n)               # 完整檔名，沒有被擠成 VID_2…2.mp4
    assert not nl.wordWrap() and nl.fontMetrics().horizontalAdvance(nl.text()) <= nl.width() + 1
    assert rl.wordWrap() and "ClipInvalid" not in rl.text()
assert "這是一段刻意寫得很長" in d.fail_rows[0][1].text() and "換行" in d.fail_rows[0][1].text()   # 原因沒被截掉
rl = d.fail_rows[0][1]
assert rl.height() > rl.fontMetrics().height() * 1.5, "長原因要換成多行"
assert rl.geometry().right() <= d.width(), (rl.geometry(), d.width())
d.close()
# 超長檔名才中間省略
ln = "VID_" + "很長的檔名" * 14 + "_02.mp4"
d = C.ExportDoneDialog(None, [(None, longreason)], [ln], out, 1); d.resize(560, 400); d.show(); app.processEvents()
nl = d.fail_rows[0][0]; assert "…" in nl.text() and nl.text().endswith("_02.mp4") and ln in nl.toolTip()
d.close()
# 截短＋失敗並存：標題兩者都寫
pa = core.ClipPath(mk("a_01.mp4"), 4.0, 1.0); pb = core.ClipPath(mk("b_01.mp4"), 4.0, 2.0); pc = mk("c_01.mp4")
d = C.ExportDoneDialog(None, [(pa, None), (pb, None), (pc, None), (None, "輸出檔沒有聲音")],
                       ["a_01.mp4", "b_01.mp4", "c_01.mp4", "d_01.mp4"], out, 2)
t = d.title.text()
assert t == "⚠ 已匯出 3 個片段，1 個失敗、2 段被截短", t
assert d.windowTitle() == "匯出未完成" and not d.retry_b.isHidden()
print("test_r73 OK")
