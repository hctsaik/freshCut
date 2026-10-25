"""成組檔案（.insv/.lrv/.thm）匯入與刪除、無垃圾桶磁碟、SD 卡拔出、監看間隔、成品長度縮短。"""
import os, sys, tempfile, subprocess, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import core, library
from app.library import Library, STATUS_OFFLINE, STATUS_PENDING, group_files

ff = core.find_ffmpeg()
root = tempfile.mkdtemp(); dc = os.path.join(root, "DCIM"); os.makedirs(dc)
def gen(p, dur=3):
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=duration={dur}:size=320x180:rate=30",
                    "-pix_fmt", "yuv420p", "-f", "mp4", p], check=True)
def junk(p, n=4096):
    open(p, "wb").write(os.urandom(n))

# Insta360：INSV（無法直接開）+ LRV + THM → 1 支，主檔用 LRV
junk(f"{dc}/VID_20261024_101500_00_001.insv", 300_000)
gen(f"{dc}/LRV_20261024_101500_01_001.lrv")
junk(f"{dc}/VID_20261024_101500_00_001.thm")
# Insta360 平面匯出 MP4 + LRV → 1 支，主檔用 MP4
gen(f"{dc}/VID_20261024_110000_00_002.mp4"); gen(f"{dc}/LRV_20261024_110000_01_002.lrv")
# GoPro：GX010001.MP4 + GL010001.LRV + GX010001.THM → 1 支
gen(f"{dc}/GX010001.MP4"); gen(f"{dc}/GL010001.LRV"); junk(f"{dc}/GX010001.THM")
# 一般檔案 + 孤兒 THM（不會成為影片）
gen(f"{dc}/beach.mov"); junk(f"{dc}/orphan.thm")

gs = group_files(library.scan_folder(dc))
prim = sorted(os.path.basename(g["primary"]) for g in gs)
assert prim == ["GX010001.MP4", "LRV_20261024_101500_01_001.lrv", "VID_20261024_110000_00_002.mp4", "beach.mov"], prim

lib = Library(os.path.join(root, "lib"))
ids = lib.add_folder(dc, recursive=True)
assert len(ids) == 4, ids
by = {os.path.basename(lib.group_members(i)[0]): i for i in ids}
insta = by["LRV_20261024_101500_01_001.lrv"]
assert len(lib.group_members(insta)) == 3 and len(lib.group_members(by["GX010001.MP4"])) == 3
# 重新掃描不會把附屬檔當新影片
assert lib.rescan() == []
# 只匯入單一檔案時也會自動找到同組附屬檔
lib2 = Library(os.path.join(root, "lib2"))
i2 = lib2.add_files([f"{dc}/GL010001.LRV"])
assert len(i2) == 1 and os.path.basename(lib2.group_members(i2[0])[0]) == "GX010001.MP4"
lib2.close()

# 刪除整組：確認內容列出 3 個檔案與總大小
plan = lib.delete_plan([insta])
assert plan["count"] == 1 and plan["file_count"] == 3 and plan["total_bytes"] > 300_000 and plan["no_trash"] == []
os.environ["XDG_DATA_HOME"] = os.path.join(root, "xdg")
ok, fail = lib.delete_files([insta])
assert ok == [insta] and not fail, fail
assert not any(n.startswith(("VID_20261024_1015", "LRV_20261024_1015")) for n in os.listdir(dc))

# 沒有垃圾桶的磁碟（模擬 Windows SD 卡）：預設不刪；確認後才永久刪除
real = library.volume_info
library.volume_info = lambda p: ({"trash": False, "kind": "removable", "label": "記憶卡或 USB 磁碟（E:）"}
                                 if ("GX01" in p or "GL01" in p) else {"trash": True, "kind": "local", "label": ""})
gp = by["GX010001.MP4"]
plan = lib.delete_plan([gp, by["beach.mov"]])
assert plan["no_trash"] == [gp], plan["no_trash"]
assert plan["no_trash_volumes"] == ["記憶卡或 USB 磁碟（E:）"]
# S2：略過無垃圾桶的檔案，其餘照常進垃圾桶
ok, fail = lib.delete_files([gp], skip_no_trash=True)
assert ok == [] and all(r == "skipped" for _, r in fail) and os.path.exists(f"{dc}/GX010001.MP4")
ok, fail = lib.delete_files([gp])
assert ok == [] and fail and all(r == "no_trash" for _, r in fail)
assert os.path.exists(f"{dc}/GX010001.MP4")
ok, fail = lib.delete_files([gp], allow_permanent=True)
assert ok == [gp] and not fail and not os.path.exists(f"{dc}/GL010001.LRV")
library.volume_info = real

# SD 卡拔出：監看資料夾不存在 → 「已中斷連線」，不是「遺失」，也不會被移除
sd = os.path.join(root, "SDCARD"); os.makedirs(sd); gen(f"{sd}/VID_20261024_120000_00_003.mp4")
sid = lib.add_folder(sd)[0]
assert lib.status(sid) == STATUS_PENDING
os.rename(sd, sd + "_ejected")
assert lib.status(sid) == STATUS_OFFLINE
assert lib.rescan() == [] and sid in [f["id"] for f in lib.files()]
assert dict((f, s) for f, _, s in lib.watched_status())[os.path.abspath(sd)] == STATUS_OFFLINE
os.rename(sd + "_ejected", sd); assert lib.status(sid) == STATUS_PENDING

# 監看間隔
assert library.watch_interval(battery=False) == 30 and library.watch_interval(battery=True) == 300

# 成品長度縮短：依比例縮短、最短 1.5 秒，仍超過時回報
S = core.Segment
segs = [S("a", 0, 4, 3), S("b", 10, 16, 1), S("c", 20, 22, 2)]  # 12 秒
fit, over = core.fit_to_target(segs, 9)
assert over == 0 and abs(sum(s.end - s.start for s in fit) - 9) < 1e-6
assert all(s.end - s.start >= 1.5 - 1e-9 for s in fit)
assert abs((fit[1].start - 10) - (16 - fit[1].end)) < 1e-9        # 兩端等量
fit, over = core.fit_to_target(segs, 3)
assert abs(over - 1.5) < 1e-6 and all(abs(s.end - s.start - 1.5) < 1e-9 for s in fit)
assert core.suggest_drop_count(fit, over) == 1
assert core.fit_to_target(segs, 0)[1] == 0
print("GROUPS OK")
