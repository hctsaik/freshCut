"""R72：截短時標題用 ⚠、失敗原因只有中文、提示行不拆「路徑」、剩約寬度用樣式表字型、清單依檔名排序、
截短警告不在檔名中間換行。離螢幕執行。"""
import faulthandler; faulthandler.dump_traceback_later(600, exit=True)
import os, sys, tempfile, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from app import core
import re
CJK = re.compile(r"[\u3400-\u9fff]")

# ---- 2) 失敗原因：core 直接回中文、不帶類別名
assert core.zh_reason(core.ClipInvalid("輸出檔沒有聲音")) == "輸出檔沒有聲音"
assert core.zh_reason("ClipInvalid: 輸出檔太短（0.2 秒）") == "輸出檔太短（0.2 秒）"
for e in (ValueError("bad"), RuntimeError("boom"), FileNotFoundError(2, "x"), PermissionError(13, "x"),
          subprocess.CalledProcessError(1, "ffmpeg")):
    m = core.zh_reason(e); assert CJK.search(m) and not re.search(r"[A-Za-z]{3,}", m), (e, m)
ff = core.find_ffmpeg(); root = tempfile.mkdtemp()
src = os.path.join(root, "two.mp4")
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=2",
                "-f", "lavfi", "-i", "sine=duration=2", "-shortest", "-pix_fmt", "yuv420p", src], check=True)
co = core.ClipOptions(pattern="time", subfolders=False)
r = core.export_clips([(core.Segment(src, 5.0, 9.0), ["start"])], os.path.join(root, "o"), co)
assert r[0][0] is None and r[0][1] and not re.match(r"^\s*[A-Za-z_]+:", r[0][1]) and CJK.search(r[0][1]), r

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
app = QApplication(sys.argv)
from app.gui import clips as C, style as S
S.apply(app) if hasattr(S, "apply") else app.setStyleSheet(S.QSS)


def mk(name, sub=""):
    d = os.path.join(root, "out", sub); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name); open(p, "wb").write(b"x" * 1000); return p


# ---- 5) 依檔名排序；1) 沒截短 → ✓
ps = [mk(n) for n in ("c_03.mp4", "a_01.mp4", "b_02.mp4")]
d = C.ExportDoneDialog(None, [(p, None) for p in ps], [os.path.basename(p) for p in ps], os.path.join(root, "out"), 3)
assert [d.files.item(i).text() for i in range(3)] == ["a_01.mp4", "b_02.mp4", "c_03.mp4"]
assert d.title.text().startswith("✓") and "截短" not in d.title.text()
d.close()

# ---- 1) 有截短 → ⚠、說出截短；6) 警告裡的檔名不在中間換行
longn = "PRO_LRV_20240825_023257_01_349_" + "很長的檔名" * 7 + "_精彩動作_02.mp4"
pa = core.ClipPath(mk(longn, "PRO_349"), 4.0, 1.0); pb = mk("PRO_349_a.mp4", "PRO_349")
rels = [os.path.relpath(p, os.path.join(root, "out")) for p in (pa, pb)]
d = C.ExportDoneDialog(None, [(pa, None), (pb, None)], rels, os.path.join(root, "out"), 3)
d.resize(560, 420); d.show(); app.processEvents()
t = d.title.text()
assert t.startswith("⚠") and "截短" in t and "✓" not in t, t
assert "截短" in d.windowTitle()
assert not d.trunc_l.wordWrap()
fm = d.trunc_l.fontMetrics()
for ln in d.trunc_lines:
    assert fm.horizontalAdvance(ln) <= d.trunc_l.width() + 1, (ln, fm.horizontalAdvance(ln), d.trunc_l.width())
assert any("4.0→1.0" in ln and ("…" in ln or longn in ln) for ln in d.trunc_lines)
assert longn in d.trunc_l.toolTip()
# 3) 位置提示獨立一行、不換行、「路徑」完整且放得下
assert not d.hint_l.wordWrap() and "完整路徑" in d.hint_l.text() and "路徑" not in d.dir_l.text().replace("位置：", "")[-2:]
assert d.hint_l.sizeHint().width() <= d.width() - 20, (d.hint_l.sizeHint().width(), d.width())
# 5) 排序
names = [d.files.item(i).text() for i in range(d.files.count())]
assert names == sorted(names, key=str.lower), names
d.close()

# ---- 失敗對話框：原因中文、無類別前綴
d = C.ExportDoneDialog(None, [(None, "ClipInvalid: 輸出檔沒有聲音"), (None, "ValueError: something")], ["a.mp4", "b.mp4"],
                       root, 1)
assert "ClipInvalid" not in d.fail_l.text() and "ValueError" not in d.fail_l.text() and "輸出檔沒有聲音" in d.fail_l.text(), d.fail_l.text()
assert not d.fail_l.wordWrap() and all(d.fail_l.fontMetrics().horizontalAdvance(l) <= 372 for l in d.fail_lines)
assert "ClipInvalid" not in d.fail_l.toolTip() and "something" not in d.fail_l.toolTip()
d.close()

# ---- 4) 剩約寬度用樣式表後的實際字型
bar = C.ExportBar(); bar.resize(1024, 56); bar.show(); bar.busy(True); app.processEvents()
bar.prog_l.setText(C.ExportBar.PROG_WORST); app.processEvents()
need = bar.prog_l.fontMetrics().horizontalAdvance(C.ExportBar.PROG_WORST)
assert bar.prog_l.width() >= need, (bar.prog_l.width(), need)
app.setStyleSheet(app.styleSheet() + "\nQLabel{font-size:18px}"); app.processEvents(); bar.busy(True); app.processEvents()
need2 = bar.prog_l.fontMetrics().horizontalAdvance(C.ExportBar.PROG_WORST)
assert need2 > need and bar.prog_l.minimumWidth() >= need2, (need, need2, bar.prog_l.minimumWidth())
print("test_r72 OK")
