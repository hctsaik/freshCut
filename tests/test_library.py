import os, sys, time, tempfile, subprocess, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import core
from app.library import Library, STATUS_DONE, STATUS_PENDING, STATUS_CHANGED

ff = core.find_ffmpeg()
root = tempfile.mkdtemp(); media = os.path.join(root, "media"); os.makedirs(media + "/sub")
def gen(p, dur=12, src="testsrc2"):
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"{src}=duration={dur}:size=640x360:rate=30",
                    "-f", "lavfi", "-i", f"sine=duration={dur}", "-shortest", "-pix_fmt", "yuv420p",
                    "-f", "mp4", p], check=True)
gen(media + "/a.mp4"); gen(media + "/sub/b.MOV"); gen(media + "/sub/c.lrv")
open(media + "/notes.txt", "w").write("x")

lib = Library(os.path.join(root, "lib"))
ids = lib.add_folder(media, recursive=True)
assert len(ids) == 3, ids
assert len(Library.__dict__) and len(lib.add_folder(media, recursive=False, watch=False)) == 1  # 非遞迴只有 a.mp4
assert all(f["status"] == STATUS_PENDING for f in lib.files())
t = time.time(); lib.analyze_pending(count=3, seg_len=1.5); t1 = time.time() - t
assert all(f["status"] == STATUS_DONE for f in lib.files())
assert lib.cache_size() > 0
tl = lib.timeline(); assert len(tl) == 3, len(tl)   # R50：每支預設勾 1 段（第二段 optional 不勾）
# 勾選 / 微調 / 順序
c0 = lib.clips(ids[0])
assert len(c0) >= 2, ("R62：12 秒影片至少 2 個策略候選（重疊 IoU>0.6 合併）", len(c0))
unchecked = [c for c in c0 if not c["checked"]][0]
lib.set_checked(unchecked["id"], True)
lib.trim(unchecked["id"], 0.2, 1.4)
order = [c["id"] for c in lib.timeline()][::-1]
lib.set_order(order)
lib.close()

# 重開：不重新分析、選取保留
lib = Library(os.path.join(root, "lib"))
assert lib.needs_analysis() == []
t = time.time(); assert lib.analyze_pending() == []; assert time.time() - t < 0.5
assert [c["id"] for c in lib.timeline()] == order
c = [c for c in lib.clips(ids[0]) if c["id"] == unchecked["id"]][0]
assert (c["start"], c["end"], c["checked"]) == (0.2, 1.4, 1)
assert os.path.exists(c["proxy"])
lib.reset_trim(c["id"])

# 已變更偵測
gen(media + "/a.mp4", dur=5, src="rgbtestsrc"); os.utime(media + "/a.mp4", (time.time() + 5,) * 2)
st = {f["id"]: f["status"] for f in lib.files()}
assert st[ids[0]] == STATUS_CHANGED, st
assert lib.needs_analysis() == [ids[0]]
lib.analyze(ids[0], count=3, seg_len=1.5)
assert lib.files()[0]["status"] == STATUS_DONE

# 監看：新檔案
gen(media + "/sub/d.mp4", 4)
new = lib.rescan(); assert len(new) == 1
assert lib.needs_analysis() == new

# 從清單移除 + 復原
lib.remove_from_list([ids[1], ids[2]])
assert len(lib.files()) == 2
assert all(c["path"] != media + "/sub/b.MOV" for c in lib.timeline())
lib.undo_remove(); assert len(lib.files()) == 3 + 1 - 0
assert os.path.exists(media + "/sub/b.MOV")

# 刪除檔案（垃圾桶）
os.environ["XDG_DATA_HOME"] = os.path.join(root, "xdg")  # send2trash Linux 垃圾桶位置
s = lib.delete_summary([ids[2]]); assert (s["count"], s["names"], s["no_trash"]) == (1, ["c"], []), s; assert s["groups"][0]["primary_ext"] == "LRV", s
ok, fail = lib.delete_files([ids[2]])
assert ok == [ids[2]] and not fail, fail
assert not os.path.exists(media + "/sub/c.lrv")
assert any("c.lrv" in f for _, _, fs in os.walk(os.path.join(root, "xdg")) for f in fs), "not in trash"
assert ids[2] not in [f["id"] for f in lib.files(include_removed=True)]

# 快取清除後保留選取
before = [c["id"] for c in lib.timeline()]
lib.clear_cache(); assert lib.cache_size() == 0
assert [c["id"] for c in lib.timeline()] == before
lib.regen_missing_assets(); assert lib.cache_size() > 0

# 用素材庫的時間軸輸出
out = os.path.join(root, "out.mp4")
core.export(lib.timeline_segments(), out, core.ExportOptions(resolution="1080p"))
print(core.probe(out)); print(f"first analysis {t1:.1f}s; LIBRARY OK")
