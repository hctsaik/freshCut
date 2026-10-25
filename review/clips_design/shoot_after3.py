"""R71 截圖（真實素材，唯讀以 symlink 使用）：python review/clips_design/shoot_after3.py"""
import os, sys, time, tempfile, glob
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "review/clips_design/after3"); os.makedirs(OUT, exist_ok=True)
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from app.gui.main import Main
from app.gui import clips as C
root = tempfile.mkdtemp(); media = os.path.join(root, "media"); os.makedirs(media)
for p in sorted(glob.glob("/workspace/real_labeled/source/*.lrv"), key=os.path.getsize, reverse=True)[32:38]:
    os.symlink(p, os.path.join(media, os.path.basename(p)))
def wait(ms):
    t = time.time()
    while time.time() - t < ms / 1000: app.processEvents(); time.sleep(0.02)
def spin(c, to=900):
    t = time.time()
    while not c() and time.time() - t < to: app.processEvents(); time.sleep(0.05)
def shot(w, n): w.grab().save(os.path.join(OUT, n)); print("saved", n)
w = Main(root=os.path.join(root, "lib")); w.resize(1440, 900); w.show(); wait(1000)
w.lib.set("tip_seen", 1); w.toast.hide(); shot(w, "01_empty.png")
w.import_folder(media, watch=False); spin(lambda: not w.busy() and not w.lib.needs_analysis()); wait(2500)
w.toast.hide(); shot(w, "02_by_video_default.png")   # 含均勻取樣第一次的一行說明
w.strat_bar.tip_x.click()
cfg = {k: dict(v, on=(k == "action")) for k, v in w.lib.strategy_cfg().items()}; cfg["action"]["n"] = 2
w.strat_bar.set_cfg(cfg); w._strategy_changed(cfg); spin(lambda: not w._rc_job); wait(1500)
shot(w, "03_only_action_n2.png")
for k in ("people", "loud", "scene"): w.strat_bar.pills[k].click(); spin(lambda: not w._rc_job)
wait(1500); w.toast.hide(); shot(w, "04_four_strategies.png")
w.group_btns[1].click(); wait(1200); shot(w, "05_by_strategy.png"); w.group_btns[0].click()
w.strat_bar.more.click(); wait(600); shot(w, "06_strategy_panel.png")
w.strat_bar.more.click()
w._set_many(list(w.cards)[:4], True); wait(800); shot(w, "07_selected.png")
w.show_btns[1].click(); wait(600); shot(w, "08_filter_checked.png"); w.show_btns[0].click()
w.resize(1200, 800); wait(600); shot(w, "09_narrow_1200.png"); w.drawer_b.click(); wait(500); shot(w, "10_narrow_drawer.png"); w.drawer_b.click()
w.resize(1024, 768); wait(600); shot(w, "13_narrow_1024.png"); w.drawer_b.click(); wait(500); shot(w, "14_narrow_1024_drawer.png"); w.drawer_b.click()
w.resize(1440, 900); wait(500)
w.exp_panel.folder_e.setText(os.path.join(root, "out")); res = {}
w.export_clips(on_done=lambda r: res.update(r=r)); wait(700); shot(w, "11_exporting.png")
spin(lambda: "r" in res); wait(800); shot(w.done_dlg, "12_done_dialog.png"); w.done_dlg.close()
# 匯出中（1200 寬、抽屜打開：設定鎖住、主按鈕變「取消匯出」）
w.resize(1200, 800); wait(400); w.drawer_b.click(); res = {}
w.export_clips(folder=os.path.join(root, "out_b"), on_done=lambda r: res.update(r=r)); wait(700); shot(w, "15_exporting_locked_1200.png")
shot(w.exp_panel, "20_disabled_checkbox.png")      # 匯出中停用：保留原音／子資料夾仍看得出已勾
w.cancel_export(); spin(lambda: "r" in res); wait(300)
w.toast.hide(); shot(w, "19_drawer_with_exportbar_1200.png")   # 抽屜底邊停在匯出列上緣
w.drawer_b.click(); w.resize(1440, 900); wait(400)
# 長檔名
ld = os.path.join(root, "long"); os.makedirs(ld); ps = []
for i in range(7):
    n = f"2024-08-25_023257_長長的旅行片段名稱_海邊日落_小孩在沙灘上奔跑_{i:02d}_精彩動作_00m{i * 7:02d}s.mp4"
    p = os.path.join(ld, n); open(p, "wb").write(b"x" * 2000000); ps.append(p)
d = C.ExportDoneDialog(w, [(p, None) for p in ps], [os.path.basename(p) for p in ps], ld, 42); d.show(); wait(400)
shot(d, "16_done_long_names.png"); d.close()
# 失敗：輸出流程產生空殼（太短、沒聲音）→ 驗證擋下、不說成功、可重試
from app import core
k = [0]; origs = {n: getattr(core, n) for n in ("_clip_direct", "_clip_reframed")}
def mk(orig):
    def broken(seg, part, co, cb, cancel):
        k[0] += 1
        if k[0] % 2:
            import subprocess
            subprocess.run([core.find_ffmpeg(), "-y", "-v", "error", "-i", seg.path, "-t", "0.2", "-an", "-f", "mp4", part], check=True)
        else:
            orig(seg, part, co, cb, cancel)
    return broken
for n, f in origs.items(): setattr(core, n, mk(f))
res = {}
w.export_clips(folder=os.path.join(root, "out_c"), on_done=lambda r: res.update(r=r)); spin(lambda: "r" in res); wait(800)
shot(w.done_dlg, "17_export_failure.png"); shot(w, "18_failure_main.png")
for n, f in origs.items(): setattr(core, n, f)
w.done_dlg.close()
# 部分超出影片長度 → 成功但標「已截短」
src = w.lib.files()[0]["path"]; D = core.probe(src).duration
items = [(core.Segment(src, D - 1.0, D + 3.0), ["action"]), (core.Segment(src, 1.0, 4.0), ["action"])]
res = {}
w.export_clips(only=items, folder=os.path.join(root, "out_d"), on_done=lambda r: res.update(r=r)); spin(lambda: "r" in res); wait(800)
shot(w.done_dlg, "21_truncated_clip_dialog.png")
w.close(); os._exit(0)
