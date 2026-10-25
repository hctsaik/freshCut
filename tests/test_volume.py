"""R6／S2／O2／O3：磁碟判斷（mock statfs、GetDriveType）、只刪除預覽檔、組名。"""
import os, sys, tempfile, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import core, library
from app.library import (mac_volume_from_statfs as M, win_volume_from_type as W, MNT_LOCAL,
                         Library, group_name)

# macOS：statfs 的 f_fstypename / MNT_LOCAL
assert M(("smbfs", 0, "/Volumes/video", "//nas/video"))["trash"] is False
assert M(("smbfs", 0, "/Volumes/video", "//nas/video"))["label"] == "網路磁碟 //nas/video"
for fs in ("nfs", "afpfs", "webdav"):
    assert M((fs, 0, "/Volumes/x", "srv:/x"))["trash"] is False, fs
assert M(("apfs", MNT_LOCAL, "/", "/dev/disk3s1"))["trash"] is True
assert M(("exfat", MNT_LOCAL, "/Volumes/SD", "/dev/disk4s1")) == {"trash": True, "kind": "removable", "label": "外接磁碟（SD）"}
assert M(("weirdfs", 0, "/Volumes/y", "y"))["trash"] is False            # 沒有 MNT_LOCAL → 視為網路
assert M(("apfs", MNT_LOCAL, "/", "d"), nsurl_local=False)["trash"] is False
# statfs 失敗 → 用 NSURLVolumeIsLocalKey；兩者都沒有 → 假設有垃圾桶（send2trash 自身仍會報錯）
assert M(None, nsurl_local=False)["trash"] is False and M(None, nsurl_local=True)["trash"] is True
assert M(None)["trash"] is True
# mock 掉 _mac_statfs，走 volume_info 的 darwin 分支
real_plat, rs, rn = sys.platform, library._mac_statfs, library._mac_is_local_nsurl
try:
    library.sys.platform = "darwin"
    library._mac_statfs = lambda p: ("smbfs", 0, "/Volumes/v", "//nas/v")
    library._mac_is_local_nsurl = lambda p: None
    if os.name != "nt":
        assert library.trash_supported("/Volumes/v/a.mp4") is False
        library._mac_statfs = lambda p: ("apfs", MNT_LOCAL, "/", "/dev/disk3s1")
        assert library.trash_supported("/Users/me/a.mp4") is True
finally:
    library.sys.platform, library._mac_statfs, library._mac_is_local_nsurl = real_plat, rs, rn
# 真機自測（只在 macOS 上執行）：本機根目錄一定有垃圾桶，statfs 要讀得到
if sys.platform == "darwin":
    info = library._mac_statfs("/")
    assert info and info[1] & MNT_LOCAL, info
    assert library.trash_supported(os.path.expanduser("~"))

# Windows：GetDriveTypeW
assert W("C:\\v\\a.mp4", 3)["trash"] is True
assert W("E:\\DCIM\\a.mp4", 2) == {"trash": False, "kind": "removable", "label": "記憶卡或 USB 磁碟（E:）"}
assert W("Z:\\a.mp4", 4)["label"] == "網路磁碟（Z:）"
assert W("\\\\NAS\\video\\a.mp4", 0)["label"] == "網路磁碟 \\\\NAS\\video"

# O3：組名
assert group_name("/d/LRV_20261024_101500_01_001.lrv") == "VID_20261024_101500_001"
assert group_name("/d/VID_20261024_101500_00_001.insv") == "VID_20261024_101500_001"
assert group_name("/d/GX010001.MP4") == "GX010001"

# O2：只刪除預覽檔（LRV/THM），保留 MP4，勾選保留
ff = core.find_ffmpeg(); root = tempfile.mkdtemp(); dc = os.path.join(root, "DCIM"); os.makedirs(dc)
gen = lambda p: subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=duration=3:size=320x180:rate=30",
                                "-pix_fmt", "yuv420p", "-f", "mp4", p], check=True)
gen(f"{dc}/VID_20261024_110000_00_002.mp4"); gen(f"{dc}/LRV_20261024_110000_01_002.lrv")
open(f"{dc}/VID_20261024_110000_00_002.thm", "wb").write(b"x" * 100)
os.environ["XDG_DATA_HOME"] = os.path.join(root, "xdg")
lib = Library(os.path.join(root, "lib")); [fid] = lib.add_folder(dc)
plan = lib.delete_plan([fid]); g = plan["groups"][0]
assert g["name"] == "VID_20261024_110000_002" and g["primary_ext"] == "MP4"
assert g["previews_only_ok"] and len(g["previews"]) == 2
ok, fail = lib.delete_files([fid], previews_only=True)
assert ok == [fid] and not fail, fail
assert sorted(os.listdir(dc)) == ["VID_20261024_110000_00_002.mp4"]
assert lib.group_members(fid) == [f"{dc}/VID_20261024_110000_00_002.mp4"]
ok, fail = lib.delete_files([fid], previews_only=True)          # 已經沒有預覽檔
assert ok == [] and fail[0][1] == "no_original"
lib.close()
print("VOLUME OK")
try:
    from app.gui.dialogs import eta_text
except ImportError:
    eta_text = None
if eta_text:
    assert eta_text(0.02, 0, 10) == "" and eta_text(0.5, 0, 2) == ""
    assert eta_text(0.5, 0, 30) == "　約剩 30 秒", eta_text(0.5, 0, 30)
    assert eta_text(0.25, 0, 60) == "　約剩 3 分鐘"
    print("ETA OK")
