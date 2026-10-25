"""R63 截圖：python review/uiux_r63/shoot.py <outdir>"""
import os, sys, time, tempfile, glob, shutil
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/workspace/insta-editor")
OUT="/tmp"
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
w.resize(1360,860); w.import_folder(media, watch=False); wait(500)
spin(lambda: not w.busy() and not w.lib.needs_analysis()); wait(2500)
sa=w.scroll; print("widget is wall", sa.widget() is w.wall, "wall vis", w.wall.isVisible(), w.wall.geometry(), "vp", sa.viewport().size(), "sb", sa.verticalScrollBar().value(), sa.verticalScrollBar().maximum())
print("cards", len(w.wall.cards), [ (c.isVisible(), c.geometry()) for c in w.wall.cards[:3]])
print("headers", [(h.isVisible(), h.geometry()) for h in w.wall.headers])
w.grab().save("/tmp/dbg.png")
