"""R69：只輸出片段的介面（SPEC 驗收 #1、#2、#3、#4、#5、#6 的 GUI 部分）。離螢幕執行。"""
import faulthandler; faulthandler.dump_traceback_later(600, exit=True)
import os, sys, tempfile, subprocess, time, glob, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication, QPushButton
    from PySide6.QtCore import Qt, QEventLoop
    from PySide6.QtTest import QTest
except ImportError:
    print("SKIP"); sys.exit(0)
from app import core

ff = core.find_ffmpeg(); root = tempfile.mkdtemp(); media = os.path.join(root, "media"); os.makedirs(media)
for n, src in (("VID_20240825_023257_349.mp4", "testsrc2"), ("VID_20240826_101010_001.mp4", "mandelbrot")):
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"{src}=size=640x360:rate=30,trim=duration=24",
                    "-f", "lavfi", "-i", "sine=duration=24", "-shortest", "-pix_fmt", "yuv420p", os.path.join(media, n)], check=True)
app = QApplication(sys.argv)
from app.gui.main import Main
from app.gui import clips as C
from app.gui import dialogs as D
FAILS = []
D.ErrorDialog.exec = lambda self: (FAILS.append(self.summary.text()), print("ERROR DIALOG:", self.summary.text(), self.detail.toPlainText()[-800:]))[0] and 0
Main._job_failed = lambda self, m: (FAILS.append(m), print("JOB FAILED:", m))


def spin(cond, timeout=180):
    t = time.time()
    while not cond():
        app.processEvents(QEventLoop.AllEvents, 50)
        if time.time() - t > timeout:
            raise AssertionError("逾時")
        time.sleep(0.02)


w = Main(os.path.join(root, "lib"), autoplay=False); w.resize(1440, 900); w.show(); app.processEvents()
w.lib.set("tip_seen", 1)
# 舊流程不出現在介面上
vis = lambda x: x.isVisibleTo(w)
assert not vis(w.legacy_bot) and not vis(w.legacy_rscroll) and not vis(w.welcome_auto) and not vis(w.trip_b)
assert not any(a.isVisible() for a in (w.a_auto, w.a_shuffle))
w.import_folder(media, watch=False)
spin(lambda: FAILS or (w.lib.files() and not w.lib.needs_analysis() and not w.busy()))
assert not FAILS, FAILS
app.processEvents()
# 唯一的黃色主按鈕
prim = [b for b in w.findChildren(QPushButton) if b.property("primary") and b.isVisibleTo(w)]
assert prim == [w.exp_b], [b.text() for b in prim]
n0 = len(w.lib.timeline()); assert n0 >= 1
assert w.exp_b.text() == f"匯出已選片段（{n0}）" and w.exp_b.isEnabled()
assert len(w.strat_bar.pills) == 7
for k, p in w.strat_bar.pills.items():
    assert p.accessibleName().startswith(core.STRAT_NAMES[k] + "，")
print("UI shell OK", n0, "selected")

# 驗收 #1：只開「精彩動作」、每支 2 段 → 每支 ≤ 2 張卡、只有「精彩動作」chip
cfg = {k: dict(v, on=(k == "action")) for k, v in core.strategy_config(None).items()}; cfg["action"]["n"] = 2
w.strat_bar.set_cfg(cfg); w._strategy_changed(cfg)
spin(lambda: not w._rc_job)
app.processEvents()
for f in w.lib.files():
    cs = [c for c in w.lib.clips(f["id"]) if c["source"] == "ai"]
    assert len(cs) <= 2, (f["path"], len(cs))
for card in w.cards.values():
    assert card.strategies == ["action"], card.strategies
assert w.strat_bar.pills["action"].isChecked() and not w.strat_bar.pills["start"].isChecked()
print("#1 OK", len(w.cards), "cards")

# 驗收 #2：再開「從頭開始」→ 每支多一張（或併入既有卡），關閉的策略 chip 不顯示
p = w.strat_bar.pills["start"]; p.click(); spin(lambda: not w._rc_job); app.processEvents()
for f in w.lib.files():
    st = [json.loads(c["strategy"] or "[]") for c in w.lib.clips(f["id"]) if c["source"] == "ai"]
    assert any("start" in s for s in st), st
assert all(set(c.strategies) <= {"start", "action"} for c in w.cards.values())
# 關掉 action → chip 立刻消失（不用等重算）
w.strat_bar.pills["action"].click(); app.processEvents()
assert all("action" not in c.strategies for c in w.cards.values()), "關閉的策略不可再顯示 chip"
spin(lambda: not w._rc_job)
w.strat_bar.pills["action"].click(); spin(lambda: not w._rc_job); app.processEvents()
# chip 最多 2 個＋「+N」
html = C.chip_html(["start", "people", "action", "loud"]); assert html.count("<span") == 3 and "+2" in html
print("#2 OK")

# 依策略分組：同一段在兩組都出現時顯示「也在：…」
w.group_btns[1].click(); app.processEvents()
assert w.group_mode == "strategy" and w.wall.headers
w.group_btns[0].click(); app.processEvents()

# 篩選＋計數
w.show_btns[1].click(); app.processEvents()
assert all(c.on for c in w.wall.cards if not c.filtered)
w.show_btns[0].click(); app.processEvents()
assert "共" in w.count_l.text() and "已選" in w.count_l.text()

# 驗收 #3：匯出 N 段 → N 個檔、取消原音 → 沒有音軌、長度差 ≤ 0.1 秒
w._set_many([c.cid for c in w.cards.values()], True)
n = len(w._export_items()); assert w.exp_b.text() == f"匯出已選片段（{n}）"
out = os.path.join(root, "out"); w.exp_panel.folder_e.setText(out)
w.exp_panel.audio.setChecked(False)
res = {}
w.export_clips(on_done=lambda r: res.update(r=r)); assert w.exp_b.text() == "取消匯出" and not w.ebar.cancel_b.isVisibleTo(w)   # R71：只有一個取消
spin(lambda: "r" in res, 300); app.processEvents()
files = sorted(glob.glob(os.path.join(out, "**", "*.mp4"), recursive=True))
assert len(files) == n, (len(files), n)
items = w._export_items()
for (path, err), (seg, _) in zip(res["r"], items):
    assert path and not err
    pr = core.probe(path); assert not pr.has_audio, path
    assert abs(pr.duration - (seg.end - seg.start)) <= 0.1, (path, pr.duration, seg.end - seg.start)
assert not glob.glob(os.path.join(out, "**", "*.part*"), recursive=True)
dlg = w.done_dlg; assert dlg.title.text() == f"✓ 已匯出 {n} 個片段", dlg.title.text()
assert dlg.files.count() == n and all(dlg.files.item(i).text().endswith(".mp4") for i in range(n))
w.grab().save(os.path.join(root, "done.png"))
dlg.close_b.click()
print("#3 OK", n, "files")

# 驗收 #4：取消時舊的同名檔不被刪；開覆寫也一樣
w.exp_panel.over.setChecked(True)
before = {p: os.path.getsize(p) for p in files}
res = {}
w.export_clips(on_done=lambda r: res.update(r=r)); w.cancel_export()
spin(lambda: "r" in res, 300)
assert res["r"] is None
for p_, sz in before.items():
    assert os.path.exists(p_) and os.path.getsize(p_) == sz, p_
assert not glob.glob(os.path.join(out, "**", "*.part*"), recursive=True)
assert w.exp_b.isEnabled() and w.exp_b.text() != "取消匯出" and not w.ebar.cancel_b.isVisibleTo(w)
w.exp_panel.over.setChecked(False)
print("#4 OK")

# 驗收 #5：在 Finder／檔案總管中顯示
calls = []
assert C.reveal("/x/a.mp4", "darwin", run=calls.append) == ["open", "-R", "/x/a.mp4"]
assert C.reveal("C:\\x\\a.mp4", "win32", run=calls.append)[0] == "explorer"
assert calls[1][1].startswith("/select,")
urls = []; C.reveal(files[0], "linux", run=calls.append, open_url=urls.append)
assert urls and urls[0].toLocalFile() == os.path.dirname(files[0])
assert C.reveal_label("darwin") == "在 Finder 中顯示" and C.reveal_label("win32") == "在檔案總管中顯示"
print("#5 OK")

# 窄螢幕：匯出設定收成抽屜
w.resize(1200, 800); app.processEvents()
assert w.drawer_b.isVisibleTo(w) and not w.rscroll.isVisibleTo(w)
w.drawer_b.click(); app.processEvents(); assert w.rscroll.isVisibleTo(w)
w.drawer_b.click(); w.resize(1440, 900); app.processEvents(); assert w.rscroll.isVisibleTo(w)

# 驗收 #6：500+ 段時「已勾選」＋全部收合 → 卷動長度 < 2 個畫面
fid = w.lib.files()[0]["id"]
for i in range(520):
    w.lib.db.execute("INSERT INTO clips(file_id,start,end,score,source,checked,strategy) VALUES(?,?,?,?,'ai',?,?)",
                     (fid, i * 0.04, i * 0.04 + 3, 0.1, int(i % 50 == 0), json.dumps(["uniform"])))
w.lib.db.commit(); w.refresh(); app.processEvents()
assert len(w.cards) > 500
t = time.time(); w.show_btns[1].click(); app.processEvents()
w._fold_all(); app.processEvents(); w._relayout_now(); app.processEvents()
vh = w.scroll.viewport().height(); total = w.wall.sizeHint().height()
print("#6", len(w.cards), "cards, filter", round(time.time() - t, 2), "s, scroll", total, "/", vh)
assert total < 2 * vh
w._fold_all(); app.processEvents()
vh = w.scroll.viewport().height(); total = w.wall.sizeHint().height()
assert total < 2 * vh * 3, total     # 只顯示已勾選（~11+n 段）
# Ctrl+A：本頁全選只勾看得到的
w.show_btns[0].click(); app.processEvents()
print("#6 OK")
w.close()
print("test_gui_clips OK")
