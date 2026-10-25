"""GUI 煙霧測試（離螢幕）：匯入 → 推薦 → 勾選 → 輸出，並存截圖到 review/v7/gui_*.png。
沒有 PySide6 的直譯器會略過（印出 SKIP，結束碼 0）。"""
import faulthandler; faulthandler.dump_traceback_later(int(__import__("os").environ.get("GUI_TIMEOUT", "840")), exit=True)
import os, sys, tempfile, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication, QDialog
    from PySide6.QtCore import Qt, QEventLoop, QTimer
    from PySide6.QtTest import QTest
except ImportError:
    print("SKIP test_gui：這個直譯器沒有 PySide6"); sys.exit(0)
from app import core

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(HERE, "review", "v7"); os.makedirs(SHOTS, exist_ok=True)
ff = core.find_ffmpeg()
root = tempfile.mkdtemp(); media = os.path.join(root, "media"); os.makedirs(media)
for n, src in (("VID_0001.mp4", "testsrc2"), ("VID_0002.mp4", "mandelbrot"), ("VID_0003.mp4", "life=mold=10:ratio=0.5:death_color=#203040:life_color=#e0a040")):
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", (f"{src}:size=640x360:rate=30" if "=" in src else f"{src}=size=640x360:rate=30") + ",trim=duration=20",
                    "-f", "lavfi", "-i", "sine=duration=20", "-shortest", "-pix_fmt", "yuv420p", os.path.join(media, n)], check=True)

app = QApplication(sys.argv)
from app.gui.main import Main
from app.gui import dialogs as D


def spin(cond, timeout=120):
    t = time.time()
    while not cond():
        app.processEvents(QEventLoop.AllEvents, 50)
        if time.time() - t > timeout:
            raise AssertionError("逾時")
        time.sleep(0.02)


def wait(ms):
    t = time.time()
    while time.time() - t < ms / 1000:
        app.processEvents(); time.sleep(0.02)


def shot(w, name):
    p = os.path.join(SHOTS, name); assert w.grab().save(p), p; print("saved", p)


JOB_ERRORS = []
Main._job_failed = lambda self, msg: (JOB_ERRORS.append(msg), print("JOB FAILED:", msg))   # 測試中不要開會卡住的對話框
w = Main(root=os.path.join(root, "lib"))
w.show(); app.processEvents()
assert w.stack.currentIndex() == 0, "空素材庫要顯示歡迎頁"
spin(lambda: w.toast.isVisible(), 10)
assert "匯出已選片段" in w.toast.lab.text() and w.lib.get("tip_seen"), "第一次開啟要有提示"
shot(w, "gui_0_first_tip.png"); w.toast.hide()
shot(w, "gui_1_welcome.png")

# 匯入（資料夾、監看）→ 背景分析
w.import_folder(media)
assert w.stack.currentIndex() == 1
assert w.vlist.count() == 3
spin(lambda: getattr(w, "_an_job", 1) is None)
assert all(f["status"] == "已分析" or f["status"] for f in w.lib.files())
assert len(w.cards) >= 6, len(w.cards)
# 窄視窗：右側設定收成抽屜
w.resize(1000, 760); app.processEvents()
assert w.drawer_b.isVisible() and not w.rscroll.isVisible()
w.drawer_b.click(); app.processEvents(); assert w.rscroll.isVisible() and w.drawer_b.text() == "✕" and w.dstrip.width() == 48 and w.rscroll.width() == 320
shot(w, "gui_10_narrow_drawer.png")
w.drawer_b.click(); app.processEvents(); assert not w.rscroll.isVisible()
w.resize(1360, 860); app.processEvents(); assert w.rscroll.isVisible() and not w.drawer_b.isVisible() and not w.dstrip.isVisible()
w2 = Main(root=os.path.join(root, "lib")); app.processEvents(); wait(1000)
assert not w2.toast.isVisible(), "提示只出現一次"; w2.close(); w2.deleteLater()
print("R9 drawer/tip OK")
assert w.lib.needs_analysis() == []
# 推薦：每支預設勾 2 段
# 推薦：每支預設最多勾 2 段；明顯較差（< 45% 最高分，B5）的不自動勾
tl = w.lib.timeline(); rows = w.lib.clip_rows(); top = max(r["score"] for r in rows)
print("checked", len(tl), "scores", sorted(round(r["score"], 2) for r in rows))
assert 3 <= len(tl) <= 6, len(tl)   # R50：每支預設 1 段，接近最佳段的第二段才勾
assert w.tl.count() == len(tl)
wait(1500)   # 讓迷你預覽播出影格
frames = sum(1 for c in w.cards.values() if c.view.pixmap() and not c.view.pixmap().isNull())
print("cards with frames:", frames, "/", len(w.cards))
assert frames == len(w.cards)
players = [c.view.player for c in w.cards.values() if c.view.player]
assert players and all(p.audioOutput().isMuted() for p in players), "預覽必須靜音"
shot(w, "gui_2_wall.png")

# 勾選：鍵盤空白鍵切換
first_unchecked = next(c for c in w.cards.values() if not c.on)
first_unchecked.setFocus(); QTest.keyClick(first_unchecked, Qt.Key_Space)
assert first_unchecked.on and len(w.lib.timeline()) == len(tl) + 1
QTest.keyClick(first_unchecked, Qt.Key_Space)
assert len(w.lib.timeline()) == len(tl)
# 取消勾選全部 → 產生成品停用並顯示原因
for c in list(w.cards.values()):
    if c.on:
        w.toggle(c.cid, False)
assert not w.exp_b.isEnabled() and w.reason.text()
shot(w, "gui_3_empty_timeline.png")
picked = [c.cid for c in list(w.cards.values())[:4]]
for cid in picked:
    w.toggle(cid, True)
# B6 之後：曾在時間軸的片段重新勾選會回到原本位置，所以只比對集合
assert sorted(c["id"] for c in w.lib.timeline()) == sorted(picked)
picked = [c["id"] for c in w.lib.timeline()]
# 時間軸 Ctrl+↓ 移動
w.tl.setFocus(); w.tl.setCurrentRow(0); QTest.keyClick(w.tl, Qt.Key_Down, Qt.ControlModifier)
assert [c["id"] for c in w.lib.timeline()] == [picked[1], picked[0]] + picked[2:]
# N1：自訂長度錯誤切回預設長度要消失
w.target.setCurrentIndex(4); w.cust.setValue(5); app.processEvents()
assert (not w.cust_err.isHidden()), "4 段 × 1.5 秒 > 5 秒，應顯示錯誤"
shot(w, "gui_4_custom_error.png")
w.target.setCurrentIndex(0); app.processEvents()
assert not (not w.cust_err.isHidden())
w.target.setCurrentIndex(3)   # 不限

# 輸出
out = os.path.join(root, "out.mp4"); res = {}
w.aspect.setCurrentIndex(0); w.res.setCurrentIndex(0)
w.lib.set("hw_encode", False)
w.export(out=out, auto=True, on_done=lambda p, err=None: res.update(p=p, err=err))
wait(400); shot(w._prog, "gui_5_progress.png")
# R71：不用牆鐘時間判定——等「完成」或「失敗」事件；上限只是防卡死（負載高時一鍵輸出可能超過 300 秒）
n_err = len(JOB_ERRORS)
spin(lambda: res or len(JOB_ERRORS) > n_err, timeout=float(os.environ.get("GUI_EXPORT_TIMEOUT", 1800)))
assert len(JOB_ERRORS) == n_err, JOB_ERRORS[n_err:]
assert res.get("p") == out and not res.get("err"), res
info = core.probe(out)
exp = sum(c["end"] - c["start"] for c in w.lib.timeline())   # R70：轉場元件已移除，crossfade=0
print("export duration", info.duration, "expected≈", exp, info.width, info.height)
assert (info.width, info.height) == (1920, 1080) and abs(info.duration - exp) < 1.0

# 設定（Windows 語意：金鑰刪除要按套用才生效）
os.environ["INSTA_PF"] = "win"
dlg = D.SettingsDialog(w, w.lib); dlg.show(); dlg.tabs.setCurrentIndex(2); app.processEvents()
shot(dlg, "gui_6_settings.png")
if D.PF != "mac":
    w.lib.set("ai_key_ok", True)
    dlg._del(); assert w.lib.get("ai_key_ok") is True and dlg.pend_del
    dlg.reject(); assert w.lib.get("ai_key_ok") is True, "取消後不應刪除"
dlg.close()

# 移除（可復原）
fid = w.lib.files()[0]["id"]
w.remove_selected([fid], auto="remove"); assert w.vlist.count() == 2
w.undo(); assert w.vlist.count() == 3
# 刪除對話框截圖（不實際刪除）
td = D.TrashDialog(w, w.lib.delete_plan([fid])); td.show(); app.processEvents(); shot(td, "gui_7_trash.png"); td.close()

# ---- R1：重新推薦 / 手動新增 / 雲端 AI 在背景執行，事件迴圈不中斷 ----
ticks = [0]; tm = QTimer(); tm.timeout.connect(lambda: ticks.__setitem__(0, ticks[0] + 1)); tm.start(20)
fid = w.lib.files()[0]["id"]
before = {c["id"] for c in w.lib.clips(fid)}
t0 = time.time(); w.reanalyze(fid); call_ms = (time.time() - t0) * 1000
assert call_ms < 300, f"reanalyze 呼叫阻塞 {call_ms:.0f} ms"
assert w._headers[fid].st.text() == "分析中…"
spin(lambda: w._an_job is None)
el = time.time() - t0
print(f"reanalyze bg: call {call_ms:.0f} ms, total {el:.1f}s, ticks {ticks[0]}")
assert ticks[0] > el * 1000 / 20 * 0.3, "重新推薦期間介面卡住"
after = w.lib.clips(fid); assert after and {c["id"] for c in after} != before
assert all(os.path.exists(c["proxy"]) for c in after)

ticks[0] = 0; t0 = time.time(); j = w.manual_clip(fid, (1.0, 3.5))
assert (time.time() - t0) < 0.3 and j is not None
spin(lambda: j.finished); wait(100)
man = [c for c in w.lib.clips(fid) if c["source"] == "manual"]
assert man and abs(man[-1]["start"] - 1.0) < 0.01 and os.path.exists(man[-1]["proxy"]), man
el2 = time.time() - t0   # R17：原本固定 >3 次；工作很快完成時會誤判，改成和經過時間成比例
assert ticks[0] >= max(1, int(el2 * 1000 / 20 * 0.3)), (ticks, el2)

from app.gui import ai as AI
_orig = AI.match
def slow_match(base, key, model, q, thumbs):
    time.sleep(1.0); return {thumbs[0][0]}
AI.match = slow_match; w.cloud = True
ticks[0] = 0; w.aiq.setText("海邊"); j = w.ai_search()
assert not w.aiq.isEnabled()
spin(lambda: j.finished); wait(100)
assert ticks[0] > 20 and len(w.ai_hits) == 1 and w.aiq.isEnabled(), (ticks[0], w.ai_hits)
def bad_match(*a):
    raise AI.AIError("quota", "quota exceeded")
AI.match = bad_match; j = w.ai_search(); spin(lambda: j.finished); wait(100)
assert not w.aierr.isHidden() and "額度" in w.aierr_lab.text()
AI.match = _orig; w.cloud = False; w.aiq.setText(""); w.ai_search()
print("R1 background jobs OK")

# ---- R1：停止分析在 ffmpeg 執行中立即生效，舊結果保留 ----
long = os.path.join(media, "VID_LONG.mp4")
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=duration=120:size=1280x720:rate=30",
                "-pix_fmt", "yuv420p", "-preset", "ultrafast", long], check=True)
w.import_files([long]); lf = [f for f in w.lib.files() if f["path"] == long][0]["id"]
spin(lambda: w._an_job is not None, 10)
wait(600); t0 = time.time(); w._stop_analyze()
spin(lambda: w._an_job is None, 30); stop_s = time.time() - t0
print(f"stop analyze took {stop_s:.2f}s")
assert stop_s < 2.0, stop_s
assert w.lib.clips(lf) == [], "被中止的分析不應留下半套片段"
assert lf in w.lib.needs_analysis()
assert all(os.path.exists(c["proxy"]) for c in w.lib.clips(fid)), "其他影片的預覽不受影響"
w.remove_selected([lf], auto="remove")
tm.stop()

# ---- R1：輸出取消 → 不留半成品 ----
res = {}; out2 = os.path.join(root, "cancel.mp4")
w.export(out=out2, auto=True, on_done=lambda p, err=None: res.update(p=p, err=err))
wait(300); [setattr(x, "cancelled", True) for x in w.jobs]
spin(lambda: res, 60)
assert res == {"p": None, "err": "cancelled"} and not os.path.exists(out2), res
print("R1 cancel OK")

# ---- R2-R5：本機搜尋、風格範本、一鍵成片（對拍 + 慢動作 + 去重 + 片頭）----
w.aiq.setText("夜景"); j = w.ai_search(); spin(lambda: j.finished); wait(100)
assert w._search_mode in ("basic", "clip"), w._search_mode
w.aiq.setText("量子力學"); j = w.ai_search(); spin(lambda: j.finished); wait(100)
assert w._search_mode in ("unknown", "clip")
w.apply_style("運動")
assert w._pacing == "輕快" and w.slowmo.isChecked() and w.target.currentData() == 30
o = w.options(); assert o.look == "鮮豔" and o.auto_enhance, (o.look, o.auto_enhance)
# R70：配樂／轉場／節拍元件已從介面程式碼移除
for a in ("music", "trans", "beat", "vol", "pace", "_music_list", "_music_path", "_beat_state"):
    assert not hasattr(w, a), a
assert o.music == "" and o.crossfade == 0.0 and w._prep()["music"] == ""
w.title_e.setText("測試旅行"); w.date_c.setChecked(True)
res = {}; out3 = os.path.join(root, "auto.mp4")
shot(w, "gui_8_ai_panel.png")
w.one_click(out=out3, on_done=lambda p, err=None: res.update(p=p, err=err))
spin(lambda: res, 300)
assert res.get("p") == out3, res
tl = w.lib.timeline(); info = core.probe(out3)
print("one-click:", len(tl), "clips, duration", info.duration)
assert 3 <= len(tl) and 8 < info.duration < 45 and info.has_audio
w.title_e.setText(""); w.date_c.setChecked(False); w.slowmo.setChecked(False)
print("R2-5 OK")

# R8：鎖定（L 鍵）＋換一批
w.refresh(); spin(lambda: w.cards, 10)
keep = next(c for c in w.cards.values() if c.on)
keep.setFocus(); QTest.keyClick(keep, Qt.Key_L)
assert keep.lock and w.lib.db.execute("SELECT locked FROM clips WHERE id=?", (keep.cid,)).fetchone()[0] == 1
before = {r["id"] for r in w.lib.clip_rows() if r["checked"]}
w.reshuffle()
after = {r["id"] for r in w.lib.clip_rows() if r["checked"]}
print("reshuffle", sorted(before), "->", sorted(after))
spare = [r for r in w.lib.clip_rows() if r["id"] not in before]   # R50：每支預設 2 段候選，可能沒有可換的
assert keep.cid in after and (after != before or len(spare) <= 2), (before, after, len(spare))   # 少量備選可能被去重擋掉
assert w.cards[keep.cid].lock, "重新整理後鎖頭要保留"
shot(w, "gui_9_locked.png")
print("R8 OK")

# R10：拖放匯入（影片＋非影片檔），走真正的 QDragEnterEvent / QDropEvent
from PySide6.QtCore import QMimeData, QUrl, QPointF
from PySide6.QtGui import QDragEnterEvent, QDropEvent
dv = os.path.join(root, "drop"); os.makedirs(dv)
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30,trim=duration=6",
                "-pix_fmt", "yuv420p", os.path.join(dv, "DROP_1.mp4")], check=True)
open(os.path.join(dv, "notes.txt"), "w").write("x")
md = QMimeData(); md.setUrls([QUrl.fromLocalFile(os.path.join(dv, n)) for n in ("DROP_1.mp4", "notes.txt")])
n0 = len(w.lib.files())
ev = QDragEnterEvent(w.rect().center(), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier); w.dragEnterEvent(ev)
assert ev.isAccepted()
w.dropEvent(QDropEvent(QPointF(w.rect().center()), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
names = [os.path.basename(f["path"]) for f in w.lib.files()]
print("after drop:", names)
assert len(names) == n0 + 1 and "DROP_1.mp4" in names and "notes.txt" not in names
spin(lambda: getattr(w, "_an_job", 1) is None, 120)
empty = QMimeData(); empty.setText("hello")
ev = QDragEnterEvent(w.rect().center(), Qt.CopyAction, empty, Qt.LeftButton, Qt.NoModifier); ev.ignore(); w.dragEnterEvent(ev)
assert not ev.isAccepted(), "純文字拖曳不接受"
print("R10 drop OK")

# R10：磁碟空間不足 → 跳出 DiskDialog；選「取消」時不開始輸出、不留檔
import shutil as _sh, collections
real_du = _sh.disk_usage; seen = []
_sh.disk_usage = lambda p: collections.namedtuple("du", "total used free")(10**9, 10**9 - 10**6, 10**6)
real_exec = D.DiskDialog.exec
D.DiskDialog.exec = lambda self: (seen.append(self.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)[0].text()), 0)[1]
try:
    low = os.path.join(root, "low.mp4"); nj = len(w.jobs)
    w.export(out=low)
finally:
    _sh.disk_usage = real_du; D.DiskDialog.exec = real_exec
print("disk dialog:", seen)
assert seen and "磁碟" in seen[0] and len(w.jobs) == nj and not os.path.exists(low)
print("R10 low-disk OK")

# R11：1024 寬不裁切標題列按鈕、卡片牆不出現水平捲軸；分享預設
w.resize(1024, 700); app.processEvents(); wait(300)
vp = w.scroll.viewport()
for h in w.wall.headers:
    r = h.manual.mapTo(vp, h.manual.rect().topRight())
    assert r.x() <= vp.width(), ("手動新增被裁切", r.x(), vp.width())
assert not w.scroll.horizontalScrollBar().isVisible() or w.scroll.horizontalScrollBar().maximum() == 0
print("cols at 1024:", w.wall.COLS, "viewport", vp.width())
shot(w, "gui_11_1024.png")
w.resize(1360, 860); app.processEvents(); wait(200)
w.share.setCurrentIndex(w.share.findData("IG Reels"))
assert w.aspect.currentData() == "9:16" and w.target.currentData() == 30
assert w.options().loudnorm and not w.options(preview=True).loudnorm and "_Reels" in w._suggest_out()
w.share.setCurrentIndex(0); assert not w.options().loudnorm
print("R11 OK")

# R13（REVIEW_r10 B2/B3/B4）
w._after_analysis = lambda: (_ for _ in ()).throw(SystemExit("stale one-click export fired"))
w._an_queue = [("x", False)]
_orig_ed = D.ErrorDialog.exec; D.ErrorDialog.exec = lambda self: 0
w._analyze_failed("RuntimeError: boom"); D.ErrorDialog.exec = _orig_ed
assert w._after_analysis is None and w._an_queue == []
from PySide6.QtCore import Qt as _Qt
assert w.scroll.focusPolicy() == _Qt.NoFocus and w.rscroll.focusPolicy() == _Qt.NoFocus
w.aiq.setText(""); w._reflow(); app.processEvents()   # R69：aiq 現在是檔名篩選
seq, cur = [], w.vlist
for _ in range(400):
    cur = cur.nextInFocusChain(); seq.append(cur)
    if cur is w.exp_b:
        break
first_card = next((i for i, x in enumerate(seq) if x in w.wall.cards), None)
assert first_card is not None and first_card < seq.index(w.exp_panel.folder_e) < seq.index(w.exp_b) and w.tl not in seq, "Tab 順序：卡片牆 → 匯出設定 → 匯出（R69：沒有時間軸）"
from app.gui import style as _st
assert 'card[on="true"]:focus {{ border:3px solid #FFFFFF' in open(_st.__file__, encoding="utf-8").read()
print("R13 OK")
# R12：GUI 匯入 LUT 與濾鏡預覽
cube = os.path.join(tempfile.mkdtemp(), "teal.cube")
with open(cube, "w") as f:
    f.write("LUT_3D_SIZE 2\n" + "".join(f"{r*0.5} {g} {b}\n" for b in (0, 1) for g in (0, 1) for r in (0, 1)))
w._look_prev_ok = False
assert w.import_lut(cube) and w.look_c.currentData().startswith("lut:")
assert w.import_lut(os.path.join(tempfile.mkdtemp(), "x.cube")) is None   # 不存在的檔案 → toast，不當機
t0 = time.time()
while not getattr(w, "_look_prev_ok", False) and time.time() - t0 < 20:
    app.processEvents(); time.sleep(0.05)
assert w._look_prev_ok and not w.look_prev.pixmap().isNull(), "濾鏡預覽沒出現"
shot(w, "gui_12_lut.png"); w.look_c.setCurrentIndex(0)
print("R12 GUI OK")

# R14（REVIEW_r10 建議 B5–B8）
def _lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
cr = lambda a, b: (max(_lum(a), _lum(b)) + 0.05) / (min(_lum(a), _lum(b)) + 0.05)
print("contrast disabled border", round(cr("#767676", "#202020"), 2), "focus blue vs ACC", round(cr("#186FCF", _st.ACC), 2))
assert cr("#186FCF", _st.ACC) >= 3 and cr("#186FCF", _st.CARD) >= 3
assert cr("#767676", "#202020") >= 3 and cr("#767676", "#242424") >= 3
# B6：取消再勾選回到原位
tl0 = [c["id"] for c in w.lib.timeline()]
mid = tl0[1]; w.lib.set_checked(mid, False); w.lib.set_checked(mid, True)
assert [c["id"] for c in w.lib.timeline()] == tl0, "重新勾選後位置改變"
# B7：友善錯誤＋詳細資料
ed = D.ErrorDialog(w, "輸出失敗", "TypeError: unsupported operand type(s) for +: 'NoneType'")
assert "TypeError" not in ed.summary.text() and "TypeError" in ed.detail.toPlainText() and not ed.detail.isVisible()
from app import core as _core
assert "磁碟空間" in _core.friendly_error("OSError: [Errno 28] No space left on device")
assert "找不到檔案" in _core.friendly_error("FileNotFoundError: [Errno 2] No such file or directory: 'x'")
# B8：1024 寬時間軸文字不截斷、toast 不蓋時間軸
w.resize(1024, 700); app.processEvents(); wait(300)
fm = w.tl.fontMetrics()
for i in range(w.tl.count()):
    it = w.tl.item(i); assert it.sizeHint().width() >= fm.horizontalAdvance(it.text()) + 30
w.toast.show_msg("分析完成，已幫每支影片勾選最精彩的 2 段"); app.processEvents()
tl_top = w.ebar.mapTo(w.centralWidget(), w.ebar.rect().topLeft()).y()   # R69：toast 不可蓋住匯出列
# R71：toast 改放在匯出列中間的空白處——不蓋卡片牆、不蓋匯出列的按鈕
tg = w.toast.geometry(); cw = w.centralWidget()
vr = w.scroll.viewport().rect().translated(w.scroll.viewport().mapTo(cw, w.scroll.viewport().rect().topLeft()))
assert not tg.intersects(vr), (tg, vr)
for b in (w.ebar.exp_b, w.ebar.prev_b):
    br = b.rect().translated(b.mapTo(cw, b.rect().topLeft()))
    assert not tg.intersects(br), (tg, br)
shot(w, "gui_14_1024.png"); w.resize(1360, 860); app.processEvents()
print("R14 OK")
# R15：CLIP 標籤卡片 chip＋一鍵成片主題
import json as _json
base = set(w.lib.auto_pick(30))
cand = [r for r in w.lib.clip_rows() if r["id"] not in base]
if cand:
    tc = max(cand, key=lambda r: r["score"])
    w.lib.db.execute("UPDATE clips SET tags=? WHERE id=?", (_json.dumps(["海", "人物"], ensure_ascii=False), tc["id"]))
    w.lib.db.commit(); w.refresh(); app.processEvents(); wait(200)
    card = w.cards[tc["id"]]
    assert card.tagl.isVisible() and "#海" in card.tagl.text() and "標籤 海" in card.accessibleName()
    w.theme.setCurrentIndex(w.theme.findData("海"))
    ids = w.lib.auto_pick(30, prefer_tag=w.theme.currentData())
    print("R15 tagged", tc["id"], "picked", tc["id"] in ids)
    assert tc["id"] in ids, "主題標籤沒有讓片段優先"
    w._update_theme_counts(); assert "1 段" in w.theme.itemText(w.theme.findData("海"))
    w.cards[tc["id"]].setFocus(); app.processEvents(); shot(w, "gui_15_tags.png")
    w.theme.setCurrentIndex(0)
print("R15 OK")
# R16：文字效果／貼圖控制項
assert not w.sticker_pos.isEnabled()
w.sticker.setCurrentIndex(w.sticker.findData("❤️")); w.sticker_pos.setCurrentIndex(w.sticker_pos.findData("左下"))
assert w.sticker_pos.isEnabled() and w._prep()["stickers"] == [("❤️", "左下", "無")]
w.tstyle.setCurrentIndex(w.tstyle.findData("霓虹")); w.tanim.setCurrentIndex(w.tanim.findData("上滑"))
o = w.options(); assert o.title_style == "霓虹" and o.title_anim == "上滑"
w.sticker.setCurrentIndex(0); w.tstyle.setCurrentIndex(0); w.tanim.setCurrentIndex(0)
assert w._prep()["stickers"] == []
print("R16 OK")
# R20：低分片段卡片標註（B5 後續）
from app.library import LOW_REL
rows = w.lib.clip_rows(); top = max(r["score"] for r in rows if r["source"] != "manual")
low = [r["id"] for r in rows if r["source"] != "manual" and r["score"] < LOW_REL * top]
print("R20 low cards", len(low))
assert low, "測試素材應該有灰色雜訊影片的低分片段"
for cid, card in w.cards.items():
    assert not card.low.isVisibleTo(w)   # R69：SPEC 移除「較平淡」徽章
assert "分數偏低" not in w.cards[low[0]].accessibleName()
w.scroll.ensureWidgetVisible(w.cards[low[0]]); app.processEvents(); wait(200); shot(w, "gui_20_low.png")
print("R20 OK")
# R23：特效模板
assert w.options().effect == ""
w.fx.setCurrentIndex(w.fx.findData("故障")); assert w.options().effect == "故障"
w.fx.setCurrentIndex(0)
print("R23 OK")
# R24：貼圖拖曳＋動畫
from PySide6.QtTest import QTest
from PySide6.QtCore import QPoint
w.sticker.setCurrentIndex(w.sticker.findData("⭐")); w.sticker_pos.setCurrentIndex(w.sticker_pos.findData("custom"))
app.processEvents(); assert (not w.sticker_pad.isHidden()) and w.sticker_anim.isEnabled()
w.scroll.ensureWidgetVisible(w.sticker_pad) if hasattr(w, "scroll") else None
pad = w.sticker_pad; a = pad.area()
QTest.mouseClick(pad, Qt.LeftButton, Qt.NoModifier, QPoint(int(a.x() + a.width() * 0.3), int(a.y() + a.height() * 0.6)))
fx, fy = pad.pos_f; assert abs(fx - 0.3) < 0.03 and abs(fy - 0.6) < 0.03, pad.pos_f
pad.setFocus(); QTest.keyClick(pad, Qt.Key_Right); assert abs(pad.pos_f[0] - fx - 0.02) < 0.005
w.sticker_anim.setCurrentIndex(w.sticker_anim.findData("彈跳"))
st = w._prep()["stickers"][0]; assert st[0] == "⭐" and st[1] == pad.pos_f and st[2] == "彈跳", st
pad.resize(240, 200); shot(pad, "gui_24_sticker_pad.png")
w.sticker.setCurrentIndex(0); app.processEvents(); assert not (not w.sticker_pad.isHidden())
print("R24 OK")
# R26：速度曲線編輯器
from app.gui import dialogs as DD
cid0 = next(iter(w.cards)); c0 = dict(w.lib.db.execute("SELECT c.*, f.duration FROM clips c JOIN files f ON f.id=c.file_id WHERE c.id=?", (cid0,)).fetchone())
dlg = DD.TrimDialog(w, c0, c0["duration"] or c0["end"]); dlg.show(); app.processEvents()
assert dlg.curve.curve() is None and "輸出約" in dlg.curve_info.text()
dlg.preset.setCurrentIndex(dlg.preset.findData("中段慢動作")); app.processEvents()
assert dlg.curve.vals == [1.0, 1.0, 0.4, 1.0, 1.0], dlg.curve.vals
dlg.curve.setFocus(); dlg.curve.sel = 0; QTest.keyClick(dlg.curve, Qt.Key_Up)
assert abs(dlg.curve.vals[0] - 1.25) < 1e-6 and dlg.preset.currentData() == "自訂"
a, b = dlg.curve._geom()[0], dlg.curve._geom()[1]
QTest.mouseClick(dlg.curve, Qt.LeftButton, Qt.NoModifier, QPoint(int(dlg.curve._x(4)), int(dlg.curve._y(2.0))))
assert abs(dlg.curve.vals[4] - 2.0) < 0.15, dlg.curve.vals
shot(dlg, "gui_26_speed_curve.png")
dlg._ok(); assert dlg.result_curve and len(dlg.result_curve) == 5
w.lib.set_speed(cid0, dlg.result_curve)
dlg2 = DD.TrimDialog(w, dict(w.lib.db.execute("SELECT c.*, f.duration FROM clips c JOIN files f ON f.id=c.file_id WHERE c.id=?", (cid0,)).fetchone()), 99)
assert dlg2.curve.vals == [round(x, 3) for x in dlg.result_curve] and dlg2.preset.currentData() == "自訂"; dlg2.reject()
w.lib.set_speed(cid0, None)
print("R26 OK")
# R28：貼圖小畫面顯示實際畫面＋多張貼圖
w._timeline(); app.processEvents()
assert w.sticker_pad.thumb is not None, "小畫面沒有實際畫面"
w.sticker.setCurrentIndex(w.sticker.findData("⭐")); w.sticker_pos.setCurrentIndex(w.sticker_pos.findData("左上"))
w.sticker_anim.setCurrentIndex(w.sticker_anim.findData("無"))
assert (not w.sticker_pad.isHidden()) and w.sticker_pad.pos_f == (0.1, 0.1)
w._sticker_add(); app.processEvents()
assert w.sticker.currentData() == "" and w.sticker_list.count() == 1 and (not w.sticker_pad.isHidden())
e2 = w.sticker.itemData(2); w.sticker.setCurrentIndex(2); app.processEvents()
pad = w.sticker_pad; a = pad.area()
QTest.mouseClick(pad, Qt.LeftButton, Qt.NoModifier, QPoint(int(a.x() + a.width() * 0.7), int(a.y() + a.height() * 0.7)))
assert w.sticker_pos.currentData() == "custom", "拖曳後應切到自訂"
sts = w._prep()["stickers"]; assert len(sts) == 2 and sts[0] == ("⭐", "左上", "無") and sts[1][0] == e2, sts
assert len(pad.others) == 1
pad.resize(320, 200); shot(pad, "gui_28_sticker_multi.png")
for _ in range(6):
    w.sticker.setCurrentIndex(1); w._sticker_add()
w.sticker.setCurrentIndex(1); app.processEvents()
assert len(w.stickers) == core.STICKER_MAX and not w.sticker_add.isEnabled()
w.sticker_list.setCurrentRow(0); w._sticker_del(); assert len(w.stickers) == core.STICKER_MAX - 1
while w.stickers:
    w.sticker_list.setCurrentRow(0); w._sticker_del()
w.sticker.setCurrentIndex(0); app.processEvents(); assert not (not w.sticker_pad.isHidden()) and w._prep()["stickers"] == []
print("R28 OK")
# R29：特效預覽＋標籤器版本
for name in [e for e in core.EFFECTS if e]:
    w.fx.setCurrentIndex(w.fx.findData(name)); app.processEvents()
    assert (not w.fx_preview.isHidden()) and not w.fx_preview.pixmap().isNull(), name
w.fx.setCurrentIndex(w.fx.findData("閃白")); app.processEvents()
w.fx_preview.parentWidget().resize(w.fx_preview.parentWidget().size()); shot(w.fx_preview, "gui_29_fx_preview.png")
w.fx.setCurrentIndex(w.fx.findData("")); app.processEvents(); assert not (not w.fx_preview.isHidden())
from app import semantic as _sem
w.lib.set("tagger_version", "old")
assert w.tags_stale() == _sem.has_clip()
print("R29 OK")
# R31：插入記憶卡 → 提示 → 匯入並分析
from app import convenience as CV
card = tempfile.mkdtemp(); cam = os.path.join(card, "DCIM", "Camera01"); os.makedirs(cam)
subprocess.run([core.find_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=d=6:s=320x180:r=30", "-pix_fmt", "yuv420p",
                os.path.join(cam, "VID_20261001_101010_00_001.mp4")], check=True)
os.environ["IE_VOLUME_ROOTS"] = card
w._device_tick(); app.processEvents()
assert w.devbar.isVisible() and "Insta360" in w.dev_lab.text() and "1 支新影片" in w.dev_lab.text(), w.dev_lab.text()
shot(w, "gui_31_device.png")
w._device_tick(); assert w._dev is not None      # 同一張卡不重複提示（橫幅仍在）
n0 = len(w.lib.files()); w.import_device(); app.processEvents()
assert not w.devbar.isVisible() and len(w.lib.files()) == n0 + 1
spin(lambda: w._an_job is None, 180)
w.devwatch.seen.clear(); w.devbar.hide(); w._device_tick(); assert not w.devbar.isVisible(), "已匯入的卡不該再提示"
del os.environ["IE_VOLUME_ROOTS"]
print("R31 GUI OK")
# R32：旅程下拉＋用這組做影片
w.refresh(); app.processEvents()
assert w.trip_c.count() >= 1 and w.trip_b.isEnabled()
ids_trip = w.trips[0]["ids"]
res = {}; w.make_trip(0, out=os.path.join(root, "trip.mp4"), on_done=lambda p, err=None: res.update(p=p, err=err))
spin(lambda: "p" in res, 300); assert res["p"] and os.path.exists(res["p"]), res
tl_f = {c["file_id"] for c in w.lib.timeline()}
lockedf = {r["file_id"] for r in w.lib.clip_rows() if r.get("locked")}
assert tl_f <= set(ids_trip) | lockedf, (tl_f, ids_trip)
print("R32 GUI OK")
# R33：一句話成片（離線）
w.cloud = False
res = {}; b = w.run_brief("15秒方形海邊 熱血 史詩", out=os.path.join(root, "brief.mp4"),
                          on_done=lambda p, err=None: res.update(p=p, err=err))
assert b["target"] == 15 and w.aspect.currentData() == "1:1" and w._pacing == "史詩"
assert w.theme.currentData() == "海"
spin(lambda: "p" in res, 300); assert res["p"] and core.probe(res["p"]).width == core.probe(res["p"]).height, res
shot(w, "gui_33_brief.png")
print("R33 GUI OK")
# R34：調整指令
tgt0 = w._target(); w.refine("長一點"); assert w._target() == min(600, round(tgt0 * 1.4)), w._target()
w.refine("短一點"); assert w._target() < round(tgt0 * 1.4)
w.refine("更熱血"); assert w._pacing == "輕快"
tl = w.lib.timeline(); assert len(tl) >= 2
lock_id = tl[0]["id"]; w.lock_clip(lock_id, True); w.refresh()
w.tl.setCurrentRow(0); msg = w.refine("這段不要"); assert "鎖定" in msg[-1] and lock_id in [c["id"] for c in w.lib.timeline()]
w.tl.setCurrentRow(1); drop = w.tl.currentItem().data(Qt.UserRole); w.refine("這段不要")
ids_now = [c["id"] for c in w.lib.timeline()]
assert drop not in ids_now and lock_id in ids_now and drop in w.lib.excluded()
w.refine("多一點人"); assert w._refine.get("people") == 1 and lock_id in [c["id"] for c in w.lib.timeline()]
assert w.refine("隨便") == []
w.refine_btns["短一點"].click(); app.processEvents()
shot(w.rscroll, "gui_34_refine.png")
w.lock_clip(lock_id, False)
print("R34 GUI OK")
# R35：偏好記住＋我的範本
w.aspect.setCurrentIndex(w.aspect.findData("9:16")); w.fmt_c["1:1"].setChecked(True)
t = w.save_template("IG 直式"); assert "IG 直式" in t and w.tpl_c.findData("IG 直式") >= 0
w.aspect.setCurrentIndex(w.aspect.findData("16:9")); w.fmt_c["1:1"].setChecked(False)
w.apply_template("IG 直式"); assert w.aspect.currentData() == "9:16" and w.fmt_c["1:1"].isChecked()
w.save_prefs()
w2 = Main(root=os.path.join(root, "lib"), autoplay=False)
assert w2.aspect.currentData() == "9:16"  and w2.fmt_c["1:1"].isChecked()
assert w2.tpl_c.findData("IG 直式") >= 0
spin(lambda: getattr(w2, "_an_job", None) is None, 60); w2.close()
w.delete_template("IG 直式"); assert w.tpl_c.findData("IG 直式") < 0
print("R35 GUI OK")
# R36：一次輸出 16:9＋9:16＋1:1
w.lib.set("excluded", "[]"); w.target.setCurrentIndex(w.target.findData(15))
w.aspect.setCurrentIndex(w.aspect.findData("16:9"))
for a in ("16:9", "9:16", "1:1"):
    w.fmt_c[a].setChecked(True)
res = {}; plan = w.export(out=os.path.join(root, "multi.mp4"), auto=True, on_done=lambda p, err=None: res.update(p=p, err=err))
assert [a for a, _ in plan] == ["16:9", "9:16", "1:1"]
spin(lambda: "p" in res, 600); assert res["p"] and len(w.multi_results) == 3, (res, getattr(w, "multi_results", None))
for (a, o), want in zip(plan, ((16, 9), (9, 16), (1, 1))):
    i = core.probe(o); assert abs(i.width / i.height - want[0] / want[1]) < 0.02, (o, i.width, i.height)
assert w.aspect.currentData() == "16:9", "輸出完要回到原本比例"
for a in ("16:9", "9:16", "1:1"):
    w.fmt_c[a].setChecked(False)
print("R36 GUI OK")
assert not JOB_ERRORS, JOB_ERRORS
w.close()
print("test_gui OK")
