"""R71：500+ 段效能量測（離螢幕）。先正常分析 1 支，再把檔案與候選複製成 45 支 × 12 段＝540 段，
量：載入（開視窗到卡片牆建好）、重建卡片牆、整面重繪、捲動、本頁全選、匯出規劃。結果寫到 perf_500.json。"""
import os, sys, time, json, tempfile, subprocess, shutil, sqlite3, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from app import core
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop
app = QApplication(sys.argv)
from app.gui.main import Main
NF, PER = int(os.environ.get("PERF_FILES", 45)), 12
ff = core.find_ffmpeg(); root = tempfile.mkdtemp(); media = os.path.join(root, "media"); os.makedirs(media)


def spin(cond, timeout=600):
    t = time.time()
    while not cond():
        app.processEvents(QEventLoop.AllEvents, 50)
        assert time.time() - t < timeout, "逾時"
        time.sleep(0.01)


def settle():
    for _ in range(5):
        app.processEvents()


seed = os.path.join(media, "VID_20240825_023257_000.mp4")
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30,trim=duration=60",
                "-f", "lavfi", "-i", "sine=duration=60", "-shortest", "-pix_fmt", "yuv420p", seed], check=True)
lib_dir = os.path.join(root, "lib")
w = Main(lib_dir, autoplay=False); w.resize(1440, 900); w.show(); w.lib.set("tip_seen", 1); w.lib.set("uniform_tip_seen", 1)
w.import_folder(media); spin(lambda: getattr(w, "_an_job", 1) is None and w.cards)
dbp = [os.path.join(lib_dir, f) for f in os.listdir(lib_dir) if f.endswith((".db", ".sqlite"))][0]
w.close(); app.processEvents(); del w
db = sqlite3.connect(dbp); db.row_factory = sqlite3.Row
f0 = dict(db.execute("SELECT * FROM files").fetchone()); fid0 = f0["id"]
c0 = [dict(r) for r in db.execute("SELECT * FROM clips WHERE file_id=?", (fid0,))]
db.execute("DELETE FROM watched")
for i in range(1, NF):
    p = os.path.join(media, f"VID_20240825_0233{i:02d}_{i:03d}.mp4"); shutil.copy2(seed, p)
    f = dict(f0); f.pop("id"); f["path"] = p
    nid = db.execute(f"INSERT INTO files({','.join(f)}) VALUES({','.join('?' * len(f))})", list(f.values())).lastrowid
    for j in range(PER):
        c = dict(c0[j % len(c0)]); c.pop("id"); c["file_id"] = nid
        c["start"] = float(j * 4.5); c["end"] = c["start"] + 4.0; c["checked"] = int(j == 0)
        db.execute(f"INSERT INTO clips({','.join(c)}) VALUES({','.join('?' * len(c))})", list(c.values()))
db.commit(); total = db.execute("SELECT COUNT(*) FROM clips").fetchone()[0]; db.close()

R = {"files": NF, "clips_in_db": total}
t = time.perf_counter()
w = Main(lib_dir, autoplay=False); w.resize(1440, 900); w.show(); settle()
spin(lambda: len(w.cards) >= total * 0.9, 300)
R["load_to_wall_s"] = round(time.perf_counter() - t, 3); R["cards"] = len(w.cards)
R["needs_analysis"] = len(w.lib.needs_analysis())
t = time.perf_counter(); w._build_wall(); settle(); R["rebuild_wall_s"] = round(time.perf_counter() - t, 3)
t = time.perf_counter(); w.grab(); R["full_repaint_s"] = round(time.perf_counter() - t, 3)
sb = w.scroll.verticalScrollBar(); steps = []
for k in range(40):
    t = time.perf_counter(); sb.setValue(int(sb.maximum() * (k + 1) / 40)); w.scroll.viewport().repaint(); settle()
    steps.append(time.perf_counter() - t)
R["scroll_step_ms_median"] = round(statistics.median(steps) * 1000, 1); R["scroll_step_ms_max"] = round(max(steps) * 1000, 1)
t = time.perf_counter(); w.select_visible(); settle(); R["select_all_s"] = round(time.perf_counter() - t, 3)
R["selected"] = sum(c.on for c in w._uniq_cards())
t = time.perf_counter(); items = w._export_items(); w._summary(); R["export_plan_s"] = round(time.perf_counter() - t, 3)
R["export_items"] = len(items)
t = time.perf_counter(); w.resize(1200, 800); settle(); w.resize(1440, 900); settle(); R["resize_reflow_s"] = round(time.perf_counter() - t, 3)
w.close(); app.processEvents()
print(json.dumps(R, ensure_ascii=False, indent=1))
json.dump(R, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.environ.get("PERF_OUT", "perf_500.json")), "w"), ensure_ascii=False, indent=1)
