"""R71：停用時勾選框保留勾號、抽屜不蓋匯出列、完成對話框中段省略＋已截短、單一取消鍵、
策略 pill 停用外觀、剩約文字不截斷、toast 不蓋卡片。離螢幕執行。"""
import faulthandler; faulthandler.dump_traceback_later(900, exit=True)
import os, sys, tempfile, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from app import core

ff = core.find_ffmpeg(); root = tempfile.mkdtemp()
src = os.path.join(root, "two.mp4")
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=2",
                "-f", "lavfi", "-i", "sine=duration=2", "-shortest", "-pix_fmt", "yuv420p", src], check=True)
co = core.ClipOptions(pattern="time", subfolders=False)
# ---- 部分超出 → 成功但標 truncated
r = core.export_clips([(core.Segment(src, 1.0, 5.0), ["start"]), (core.Segment(src, 0.0, 1.5), ["start"])], os.path.join(root, "o"), co)
p0, p1 = r[0][0], r[1][0]
assert p0 and p0.truncated and abs(p0.want - 4.0) < 1e-6 and abs(p0.got - 1.0) < 0.05, (p0, p0.want, p0.got)
assert p1 and not p1.truncated

from PySide6.QtWidgets import QApplication, QStyleOptionButton, QStyle
from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtGui import QImage, QColor
app = QApplication(sys.argv)
from app.gui.main import Main
from app.gui import clips as C, style as S
FAILS = []
Main._job_failed = lambda self, m: FAILS.append(m)


def spin(cond, timeout=300):
    t = time.time()
    while not cond():
        app.processEvents(QEventLoop.AllEvents, 50)
        if time.time() - t > timeout:
            raise AssertionError("逾時")
        time.sleep(0.02)


def indicator_pixels(cb):
    """抓勾選框指示器那一塊，回傳 (平均亮度, 不同顏色數)：空框只有 1~2 種顏色，有勾號會多。"""
    img = cb.grab().toImage(); h = img.height()
    cols = set(); lum = []
    for x in range(2, min(20, img.width())):
        for y in range(max(0, h // 2 - 8), min(h, h // 2 + 8)):
            c = QColor(img.pixel(x, y)); cols.add(c.rgb()); lum.append(c.lightness())
    return sum(lum) / len(lum), len(cols)


# 勾號圖檔存在、QSS 有 checked:disabled
assert os.path.exists(S.CHK) and os.path.exists(S.CHK_DIS)
assert "QCheckBox::indicator:checked:disabled" in S.QSS and "image:url(" in S.QSS

media = os.path.join(root, "media"); os.makedirs(media)
for n, s_ in (("VID_20240825_023257_349.mp4", "testsrc2"), ("VID_20240826_101010_001.mp4", "mandelbrot")):
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"{s_}=size=640x360:rate=30,trim=duration=20",
                    "-f", "lavfi", "-i", "sine=duration=20", "-shortest", "-pix_fmt", "yuv420p", os.path.join(media, n)], check=True)
w = Main(os.path.join(root, "lib"), autoplay=False); w.resize(1440, 900); w.show(); app.processEvents()
w.lib.set("tip_seen", 1); w.lib.set("uniform_tip_seen", 1)
w.import_folder(media); spin(lambda: getattr(w, "_an_job", 1) is None and w.cards)
spin(lambda: all(c.isVisible() for c in w.wall.cards), 30)
assert w.wall.isVisible() and all(c.isVisible() for c in w.wall.cards), "卡片牆被藏掉"
# R71 回歸：既有片庫、視窗尚未 show 就建好牆 → show 之後卡片必須看得到
w0 = Main(os.path.join(root, "lib"), autoplay=False); w0.resize(1440, 900); w0.show(); app.processEvents()
spin(lambda: w0.wall.cards and all(c.isVisible() for c in w0.wall.cards), 30)
assert w0.wall.isVisible() and w0.wall.cards and all(c.isVisible() for c in w0.wall.cards), "未 show 時建的牆在 show 後仍是空白"
w0.close(); app.processEvents()

# ---- 勾選框停用時仍看得出勾選
a = w.exp_panel.audio; a.setChecked(True); app.processEvents()
on_l, on_n = indicator_pixels(a)
a.setChecked(False); a.setEnabled(False); app.processEvents(); off_l, off_n = indicator_pixels(a)
a.setChecked(True); app.processEvents(); dis_l, dis_n = indicator_pixels(a)
a.setEnabled(True)
print("indicator", (on_l, on_n), (off_l, off_n), (dis_l, dis_n))
assert dis_n > off_n and abs(dis_l - off_l) > 8, "停用＋勾選不可畫成和停用空框一樣"

# ---- 抽屜底邊停在匯出列上緣
for W in (1200, 1024):
    w.resize(W, 800); app.processEvents()
    w.drawer_b.setChecked(True); app.processEvents()
    host = w.rscroll.parentWidget()
    eb_top = w.ebar.mapTo(host, w.ebar.rect().topLeft()).y()
    g = w.rscroll.geometry()
    assert g.bottom() < eb_top and g.bottom() >= eb_top - 2, (W, g, eb_top)
    eb = w.exp_b.mapTo(host, w.exp_b.rect().topLeft())
    assert not g.intersects(w.exp_b.rect().translated(eb)), "抽屜不可蓋主按鈕"
    w.drawer_b.setChecked(False); app.processEvents()
w.resize(1440, 900); app.processEvents()

# ---- 匯出中：單一取消鍵、pill 停用外觀、剩約不截斷、toast 位置
out = os.path.join(root, "out"); w.exp_panel.folder_e.setText(out)
res = {}; w.export_clips(on_done=lambda r: res.update(r=r)); app.processEvents()
assert w.exp_b.text() == "取消匯出" and not w.ebar.cancel_b.isVisibleTo(w)
cancels = [b for b in w.findChildren(C.QPushButton) if b.isVisibleTo(w) and "取消" in b.text()]
assert len(cancels) == 1, [b.text() for b in cancels]
pill = next(iter(w.strat_bar.pills.values())); assert not pill.isEnabled()
assert "QPushButton:disabled" in pill.styleSheet()
assert not w.exp_panel.audio.isEnabled() and w.exp_panel.audio.isChecked()
w.ebar.prog_l.setText("匯出中 120/500 · 剩約 12:34"); app.processEvents()
pl = w.ebar.prog_l
assert pl.width() >= pl.fontMetrics().horizontalAdvance(pl.text()), (pl.width(), pl.text())
spin(lambda: "r" in res)
w.done_dlg.close(); app.processEvents()

w.toast.show_msg("已依新的剪片策略更新候選（已勾選、鎖定、微調過的片段都保留）", ms=4000); app.processEvents()
cw = w.centralWidget(); tg = w.toast.geometry()
sc = w.scroll.viewport(); so = sc.mapTo(cw, sc.rect().topLeft())
view = sc.rect().translated(so)
eb_top = w.ebar.mapTo(cw, w.ebar.rect().topLeft()).y()
assert tg.top() >= eb_top - 1, ("toast 要在匯出列內", tg, eb_top)
assert not tg.intersects(view), "toast 不可蓋卡片區"
w.toast.hide()

# ---- 完成對話框：無橫向捲軸、主行只放檔名、ElideMiddle 真的生效、已截短
long = "PRO_LRV_20240825_023257_01_349_" + "很長的檔名" * 8 + "_場景變換_01.mp4"
sub = os.path.join(root, "PRO_LRV_20240825_023257_01_349"); os.makedirs(sub, exist_ok=True)
pth = os.path.join(sub, long); open(pth, "wb").write(b"x")
cp = core.ClipPath(pth, 4.0, 1.0)
dlg = C.ExportDoneDialog(w, [(cp, None), (p1, None)], [os.path.relpath(pth, root), os.path.basename(p1)], root, 3)
dlg.resize(560, 400); dlg.show(); app.processEvents()
assert dlg.files.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
it = dlg.files.item(0)
assert it.text().startswith(long) and "/" not in it.text() and "已截短" in it.text(), it.text()
assert pth in it.toolTip()
vr = dlg.files.visualItemRect(it)
assert vr.width() <= dlg.files.viewport().width(), "項目不可被撐成全文寬度"
assert dlg.files.fontMetrics().horizontalAdvance(it.text()) > vr.width(), "測試檔名要夠長才會觸發省略"
assert dlg.trunc and "截短" in dlg.trunc_l.text() and "4.0→1.0" in dlg.trunc_l.text(), dlg.trunc
assert "截短" not in dlg.files.item(1).text()
dlg.close()

w.close(); app.processEvents()
assert not FAILS, FAILS
print("test_r71 OK")
