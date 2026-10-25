"""R63 截圖：python review/uiux_r63/shoot.py <outdir>"""
import os, sys, time, tempfile, glob, shutil
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE)
OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
app = QApplication(sys.argv)
from app.gui.main import Main
from app.gui import dialogs as D
SRC = "/workspace/real_labeled/source"
root = tempfile.mkdtemp(); media = os.path.join(root, "media"); os.makedirs(media)
lrvs = sorted(glob.glob(SRC + "/*.lrv"), key=os.path.getsize, reverse=True)[32:38] + ["/workspace/real_long/PRO_LRV_20250201_212751_01_046.lrv"]
for p in lrvs:
    os.symlink(p, os.path.join(media, os.path.basename(p)))
def wait(ms):
    t = time.time()
    while time.time() - t < ms / 1000: app.processEvents(); time.sleep(0.02)
def spin(c, to=900):
    t = time.time()
    while not c():
        app.processEvents(); time.sleep(0.05)
        if time.time() - t > to: print("timeout"); return
def shot(w, n, size=None):
    if size: w.resize(*size); wait(400)
    p = os.path.join(OUT, n); w.grab().save(p); print("saved", p)
Main._job_failed = lambda self, m: print("JOB FAILED", m)
w = Main(root=os.path.join(root, "lib")); w.show(); wait(1200)
shot(w, "01_welcome_first_tip.png"); w.toast.hide(); shot(w, "02_welcome.png")
w.import_folder(media, watch=False); wait(500)
shot(w, "03_analyzing.png")
spin(lambda: not w.busy() and not w.lib.needs_analysis()); wait(2500)
shot(w, "04_candidates_1360.png")
shot(w, "05_candidates_1024.png", (1024, 700)); w.resize(1360, 860); wait(300)
for cid in list(w.cards)[:3]:
    try: w.cards[cid].set_on(True) if hasattr(w.cards[cid],"set_on") else None; w.toggle(cid, True)
    except Exception as e: print("tick", e)
wait(1500); shot(w, "06_selected_timeline.png")
shot(w, "07_wide_1920.png", (1920, 1080)); w.resize(1360, 860)
def dlg(d, n):
    d.show(); wait(600); shot(d, n); d.hide(); d.deleteLater()
cl = w.lib.clip_rows()[0]
try: dlg(D.TrimDialog(w, cl, 60.0), "08_trim_dialog.png")
except Exception as e: print("trim", e)
dlg(D.RemoveDialog(w, ["PRO_VID_A", "PRO_VID_B"]), "09_remove_dialog.png")
p = D.ProgressDialog(w); p.set(0.42, "正在轉場與混音…"); dlg(p, "10_progress.png")
dlg(D.DoneDialog(w, os.path.join(root, "out.mp4")), "11_done.png")
dlg(D.ErrorDialog(w, "輸出失敗", "ffmpeg 結束碼 1：磁碟空間不足"), "12_error.png")
try: dlg(D.SettingsDialog(w, w.lib), "13_settings.png")
except Exception as e: print("settings", e)
w.resize(1360, 860); w.lib.clear_clips() if hasattr(w.lib, "clear_clips") else None
print("CLIPS", len(w.lib.clip_rows()))
w.close(); os._exit(0)
