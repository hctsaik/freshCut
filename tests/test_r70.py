"""R70：匯出後驗證（入出點夾回素材長度、沒有影像/聲音或太短就算失敗＋可重試）、窄視窗抽屜、匯出中鎖定、
完成對話框長檔名、均勻取樣保底、關閉後不碰資料庫。離螢幕執行。"""
import faulthandler; faulthandler.dump_traceback_later(600, exit=True)
import os, sys, tempfile, subprocess, time, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from app import core

ff = core.find_ffmpeg(); root = tempfile.mkdtemp()
src = os.path.join(root, "a.mp4")
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=6",
                "-f", "lavfi", "-i", "sine=duration=6", "-shortest", "-pix_fmt", "yuv420p", src], check=True)
mute = os.path.join(root, "mute.mp4")
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=4",
                "-pix_fmt", "yuv420p", mute], check=True)
co = core.ClipOptions(pattern="time", subfolders=False)

# ---- #4 夾回素材長度
s, info = core.clamp_segment(core.Segment(src, 4.0, 99.0))
assert s.start == 4.0 and abs(s.end - info.duration) < 1e-6, (s, info.duration)
try:
    core.clamp_segment(core.Segment(src, 50.0, 60.0)); raise SystemExit("超出檔尾應丟 ClipInvalid")
except core.ClipInvalid:
    pass
out = os.path.join(root, "o")
r = core.export_clips([(core.Segment(src, 4.0, 99.0), ["start"]), (core.Segment(src, 30.0, 35.0), ["uniform"])], out, co)
assert r[0][0] and not r[0][1] and abs(core.probe(r[0][0]).duration - 2.0) < 0.2, r
assert r[1][0] is None and "ClipInvalid" in r[1][1], r
assert not glob.glob(os.path.join(out, "*.part*"))

# ---- #4 驗證：沒有聲音（原聲開、素材有聲）、太短、沒有影像 → 失敗
sh = os.path.join(root, "short.mp4")
subprocess.run([ff, "-y", "-v", "error", "-i", src, "-t", "0.5", sh], check=True)
seg = core.Segment(src, 0.0, 4.0)
for bad, why in ((sh, "太短"), (mute, "沒有聲音")):
    try:
        core.validate_clip(bad, seg, co, core.probe(src)); raise SystemExit(f"{why} 應失敗")
    except core.ClipInvalid as e:
        assert why in str(e), e
aud = os.path.join(root, "aud.m4a")
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=duration=4", aud], check=True)
try:
    core.validate_clip(aud, seg, co); raise SystemExit("沒有影像應失敗")
except core.ClipInvalid as e:
    assert "影像" in str(e), e
core.validate_clip(mute, core.Segment(mute, 0, 4), co, core.probe(mute))       # 素材本來就沒聲音 → OK
co_na = core.ClipOptions(pattern="time", subfolders=False, audio=False)
core.validate_clip(mute, seg, co_na, core.probe(src))                           # 不保留原聲 → OK
# 輸出流程壞掉（產出空殼）→ 回報失敗、不留檔、不取代舊檔
orig = core._clip_direct
def broken(seg, part, co, cb, cancel):
    subprocess.run([ff, "-y", "-v", "error", "-i", src, "-t", "0.2", "-an", "-f", "mp4", part], check=True)
core._clip_direct = broken
out2 = os.path.join(root, "o2"); os.makedirs(out2)
r = core.export_clips([(core.Segment(src, 0.0, 4.0), ["start"])], out2, co)
assert r[0][0] is None and "ClipInvalid" in r[0][1] and not os.listdir(out2), (r, os.listdir(out2))
core._clip_direct = orig
print("export validation OK")

# ---- 均勻取樣：每支最多 1 段；只有均勻取樣的候選標 optional、排最後
assert core.strategy_config({"uniform": {"n": 5}})["uniform"]["n"] == 1 and core.STRAT_RANGE["uniform"][1] == (1, 1)

# ---- GUI
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtTest import QTest
app = QApplication(sys.argv)
from app.gui.main import Main
from app.gui import clips as C
from app.gui import dialogs as D
FAILS = []
D.ErrorDialog.exec = lambda self: (FAILS.append(self.summary.text()), 0)[1]
Main._job_failed = lambda self, m: FAILS.append(m)


def spin(cond, timeout=180):
    t = time.time()
    while not cond():
        app.processEvents(QEventLoop.AllEvents, 50)
        if time.time() - t > timeout:
            raise AssertionError("逾時")
        time.sleep(0.02)


media = os.path.join(root, "media"); os.makedirs(media)
for n, s_ in (("VID_20240825_023257_349.mp4", "testsrc2"), ("VID_20240826_101010_001.mp4", "mandelbrot")):
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"{s_}=size=640x360:rate=30,trim=duration=20",
                    "-f", "lavfi", "-i", "sine=duration=20", "-shortest", "-pix_fmt", "yuv420p", os.path.join(media, n)], check=True)
w = Main(os.path.join(root, "lib"), autoplay=False); w.resize(1440, 900); w.show(); app.processEvents()
w.lib.set("tip_seen", 1)
for a in ("music", "trans", "vol", "beat", "pace"):
    assert not hasattr(w, a), a
assert not w.strat_bar.tip.isHidden(), "均勻取樣第一次要有一行說明"
w.strat_bar.tip_x.click(); assert w.lib.get("uniform_tip_seen") and w.strat_bar.tip.isHidden()
w.import_folder(media); spin(lambda: getattr(w, "_an_job", 1) is None and w.cards)
from app.gui.main import _uniform_only
for f in w.lib.files():
    cl = w.lib.clips(f["id"])
    assert sum(_uniform_only(c) for c in cl) <= 1, cl
    assert not any(c["checked"] for c in cl if _uniform_only(c)), "只有均勻取樣的片段不可自動勾"

# ---- 抽屜：1200、1024 寬
for W in (1200, 1024):
    w.resize(W, 800); app.processEvents()
    assert w.width() <= W + 1, (W, w.width(), w.minimumSizeHint())
    assert w.dstrip.isVisibleTo(w) and w.dstrip.width() == 48 and not w.rscroll.isVisibleTo(w), W
    w.drawer_b.click(); app.processEvents()
    assert w.rscroll.isVisibleTo(w) and w.rscroll.width() == 320 and w.drawer_b.isChecked(), W
    mid = w.scroll.width()
    w.drawer_b.click(); app.processEvents(); assert not w.rscroll.isVisibleTo(w)
    assert w.scroll.width() == mid, "抽屜浮在上面，不擠壓卡片牆"
    w.drawer_b.click(); app.processEvents(); QTest.keyClick(w, Qt.Key_Escape); app.processEvents()
    assert not w.rscroll.isVisibleTo(w) and not w.drawer_b.isChecked(), "Esc 關抽屜"
    fbw = w.filter_bar.width(); assert fbw >= w.filter_bar.minimumSizeHint().width(), (W, fbw)
w.drawer_b.click(); w.resize(1440, 900); app.processEvents()
assert w.rscroll.isVisibleTo(w) and not w.dstrip.isVisibleTo(w) and not w.drawer_b.isChecked()
print("drawer OK")

# ---- 匯出中：主按鈕變「取消匯出」、設定鎖住；長檔名對話框
out3 = os.path.join(root, "out3"); w.exp_panel.folder_e.setText(out3)
n = len(w._export_items()); assert n >= 1
res = {}; w.export_clips(on_done=lambda r: res.update(r=r))
assert w.exp_b.text() == "取消匯出" and w.exp_b.isEnabled() and not w.exp_panel.isEnabled() and not w.strat_bar.isEnabled()
assert not w.prev_b.isEnabled()
spin(lambda: "r" in res, 300)
assert w.exp_panel.isEnabled() and w.strat_bar.isEnabled() and w.exp_b.text().startswith("匯出已選片段")
w.done_dlg.close()
# 主按鈕當取消
res = {}; w.export_clips(on_done=lambda r: res.update(r=r)); w.exp_b.click()
spin(lambda: "r" in res, 300); assert res["r"] is None and w.exp_panel.isEnabled()

long = "VID_20240825_023257_349_" + "很長的檔名" * 12 + "_start_00m03s.mp4"
paths = [os.path.join(root, long)]; open(paths[0], "wb").write(b"x")
dlg = C.ExportDoneDialog(w, [(paths[0], None)], [long], root, 3)
dlg.show(); app.processEvents()
it = dlg.files.item(0)
assert it.text() == long and it.toolTip() == paths[0] and dlg.files.textElideMode() == C.Qt.ElideMiddle
dlg.close()
# 失敗 → 不顯示成功、有重試
dlg = C.ExportDoneDialog(w, [(None, "ClipInvalid: 輸出檔沒有聲音")], ["a.mp4"], root, 1)
assert "失敗" in dlg.title.text() and "✓" not in dlg.title.text() and not dlg.retry_b.isHidden() and dlg.windowTitle() == "匯出未完成"
got = []; dlg.retry.connect(got.append); dlg.retry_b.click(); assert got == [[0]]

# ---- 關閉後延遲的工作不碰已關閉的資料庫
w.close(); app.processEvents()
assert w.run_job(lambda job: 1) is None
w.start_tagging()
assert not FAILS, FAILS
print("test_r70 OK")
