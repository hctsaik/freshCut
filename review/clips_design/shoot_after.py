"""R69 截圖（真實素材）：python review/clips_design/shoot_after.py"""
import os, sys, time, tempfile, glob
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "review/clips_design/after"); os.makedirs(OUT, exist_ok=True)
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
w.toast.hide(); shot(w, "02_by_video_default.png")
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
w.resize(1440, 900); wait(500)
w.exp_panel.folder_e.setText(os.path.join(root, "out")); res = {}
w.export_clips(on_done=lambda r: res.update(r=r)); wait(700); shot(w, "11_exporting.png")
spin(lambda: "r" in res); wait(800); shot(w.done_dlg, "12_done_dialog.png")
w.close(); os._exit(0)
