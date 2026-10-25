"""本機素材庫：SQLite 快取分析結果、候選片段、預覽 proxy，並保存使用者的勾選/微調/順序。"""
import os, re, sys, json, time, sqlite3, hashlib, shutil, subprocess
LOW_REL = 0.45   # 相對最高分的門檻（B5）
import logging
import numpy as np
from . import core

log = logging.getLogger(__name__)
# 分析單一檔案時「預期會發生」的錯誤：壞檔、ffmpeg 失敗、解碼問題。程式錯誤（TypeError 等）不吞掉。
ANALYZE_ERRORS = (OSError, RuntimeError, ValueError, subprocess.SubprocessError, EOFError)

STATUS_DONE, STATUS_PENDING, STATUS_CHANGED, STATUS_ERROR, STATUS_MISSING = \
    "已分析", "待分析", "已變更", "錯誤", "遺失"
STATUS_OFFLINE = "已中斷連線"   # 所在的監看資料夾/磁碟目前不存在（例如 SD 卡未插入）

# ---------- 成組檔案（Insta360 .insv/.lrv/.thm、GoPro GX/GL/THM、DJI .LRF）----------
COMPANION_EXTS = (".thm", ".lrf")            # 只跟著主檔走，不單獨成為影片
_PRIMARY_RANK = {".mp4": 0, ".mov": 0, ".m4v": 0, ".lrv": 1, ".lrf": 1, ".insv": 2, ".thm": 9}
_INSTA = re.compile(r"^(?:PRO_)?(?:VID|LRV|IMG)_(\d{8}_\d{6})_\d{2}_(\d+)$", re.I)
_GOPRO = re.compile(r"^G[HXL](\d{6})$", re.I)


def group_key(path):
    """同一次拍攝的檔案回傳相同的 key：(資料夾, 正規化檔名)。"""
    d, b = os.path.split(os.path.abspath(path))
    stem = os.path.splitext(b)[0]
    m = _INSTA.match(stem)
    if m:
        stem = f"INSTA:{m.group(1)}_{m.group(2)}"
    else:
        m = _GOPRO.match(stem)
        stem = f"GOPRO:{m.group(1)}" if m else stem.upper()
    return os.path.normcase(d), stem


def group_files(paths):
    """把路徑分組。回傳 [{'key','primary','members'}]；主檔優先 MP4/MOV，其次 LRV，最後 INSV。
    只有附屬檔（.thm/.lrf）而沒有影片的組會被略過。"""
    groups = {}
    for p in paths:
        groups.setdefault(group_key(p), []).append(os.path.abspath(p))
    out = []
    for k, ms in groups.items():
        ms = sorted(set(ms), key=lambda p: (_PRIMARY_RANK.get(os.path.splitext(p)[1].lower(), 5), p))
        if os.path.splitext(ms[0])[1].lower() in COMPANION_EXTS:
            continue
        out.append({"key": k, "primary": ms[0], "members": ms})
    return sorted(out, key=lambda g: g["primary"])


PREVIEW_EXTS = (".lrv", ".lrf", ".thm")       # 預覽/縮圖檔：可「只刪除預覽檔」


def group_name(path):
    """清單與刪除對話框共用的組名（O3）：Insta360 一律顯示 VID_…，副檔名另以徽章顯示。"""
    stem = os.path.splitext(os.path.basename(path))[0]
    m = _INSTA.match(stem)
    return f"VID_{m.group(1)}_{m.group(2)}" if m else stem


def _siblings(path):
    d = os.path.dirname(os.path.abspath(path)); k = group_key(path)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    return [os.path.join(d, n) for n in names
            if n.lower().endswith(core.VIDEO_EXTS + COMPANION_EXTS) and not n.startswith("._")
            and group_key(os.path.join(d, n)) == k]


# ---------- 垃圾桶可用性 ----------
NO_TRASH_FS = ("smbfs", "nfs", "afpfs", "webdav", "cifs", "ftp", "osxfuse", "macfuse")
MNT_LOCAL = 0x00001000


def _mac_statfs(path):
    """macOS：用 libc statfs() 讀 (f_fstypename, f_flags, f_mntonname, f_mntfromname)。失敗回 None。
    struct statfs 依 <sys/mount.h>（64-bit inode 版，arm64/x86_64 預設）。"""
    import ctypes, ctypes.util

    class StatFS(ctypes.Structure):
        _fields_ = [("f_bsize", ctypes.c_uint32), ("f_iosize", ctypes.c_int32),
                    ("f_blocks", ctypes.c_uint64), ("f_bfree", ctypes.c_uint64), ("f_bavail", ctypes.c_uint64),
                    ("f_files", ctypes.c_uint64), ("f_ffree", ctypes.c_uint64),
                    ("f_fsid", ctypes.c_int32 * 2), ("f_owner", ctypes.c_uint32), ("f_type", ctypes.c_uint32),
                    ("f_flags", ctypes.c_uint32), ("f_fssubtype", ctypes.c_uint32),
                    ("f_fstypename", ctypes.c_char * 16), ("f_mntonname", ctypes.c_char * 1024),
                    ("f_mntfromname", ctypes.c_char * 1024), ("f_flags_ext", ctypes.c_uint32),
                    ("f_reserved", ctypes.c_uint32 * 7)]
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        fn = getattr(libc, "statfs$INODE64", None) if not hasattr(libc, "statfs64") else libc.statfs64
        fn = fn or libc.statfs
        st = StatFS()
        if fn(os.fsencode(path), ctypes.byref(st)) != 0:
            return None
        d = lambda b: b.decode("utf-8", "replace")
        return d(st.f_fstypename), st.f_flags, d(st.f_mntonname), d(st.f_mntfromname)
    except (OSError, AttributeError, ValueError) as e:
        log.debug("statfs failed for %s: %s", path, e)
        return None


def _mac_is_local_nsurl(path):
    """備援：NSURLVolumeIsLocalKey（需要 pyobjc；沒有時回 None）。"""
    try:
        from Foundation import NSURL, NSURLVolumeIsLocalKey
        url = NSURL.fileURLWithPath_(path)
        vals, _ = url.resourceValuesForKeys_error_([NSURLVolumeIsLocalKey], None)
        v = vals and vals.get(NSURLVolumeIsLocalKey)
        return None if v is None else bool(v)
    except (ImportError, AttributeError, TypeError):
        return None


def mac_volume_from_statfs(info, nsurl_local=None):
    """純函式（可測）：由 statfs 結果判斷 macOS 磁碟。回傳 {trash, kind, label}。"""
    if info is None:
        local = nsurl_local
        if local is None:
            return {"trash": True, "kind": "unknown", "label": ""}
        return {"trash": local, "kind": "local" if local else "network", "label": "" if local else "網路磁碟"}
    fstype, flags, mnton, mntfrom = info
    net = fstype.lower() in NO_TRASH_FS or not (flags & MNT_LOCAL) or nsurl_local is False
    if net:
        return {"trash": False, "kind": "network", "label": f"網路磁碟 {mntfrom or mnton}".strip()}
    if fstype.lower() in ("msdos", "exfat") and mnton.startswith("/Volumes/"):
        return {"trash": True, "kind": "removable", "label": f"外接磁碟（{os.path.basename(mnton)}）"}
    return {"trash": True, "kind": "local", "label": ""}


def win_volume_from_type(path, drive_type):
    """純函式（可測）：GetDriveTypeW 結果 → {trash, kind, label}。2=卸除式 3=固定 4=網路。"""
    import ntpath
    drive = ntpath.splitdrive(path)[0]
    if not drive or drive.startswith("\\\\"):
        unc = "\\".join(path.split("\\")[:4]) if path.startswith("\\\\") else path
        return {"trash": False, "kind": "network", "label": f"網路磁碟 {unc}"}
    if drive_type == 3:
        return {"trash": True, "kind": "local", "label": ""}
    if drive_type == 4:
        return {"trash": False, "kind": "network", "label": f"網路磁碟（{drive}）"}
    return {"trash": False, "kind": "removable", "label": f"記憶卡或 USB 磁碟（{drive}）"}


def volume_info(path):
    """該檔所在磁碟：有沒有垃圾桶、種類、顯示名稱（給 dPerm 文案）。"""
    path = os.path.abspath(path)
    if os.name == "nt":
        import ctypes
        drive = os.path.splitdrive(path)[0]
        t = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") if drive and not drive.startswith("\\\\") else 4
        return win_volume_from_type(path, t)
    if sys.platform == "darwin":
        return mac_volume_from_statfs(_mac_statfs(path), _mac_is_local_nsurl(path))
    return {"trash": True, "kind": "local", "label": ""}


def trash_supported(path):
    """該檔所在磁碟是否有垃圾桶/資源回收筒（沒有時 send2trash 會失敗或永久刪除）。
    Windows：只有固定磁碟（DRIVE_FIXED）有；SD 卡、USB、網路磁碟、UNC 沒有。
    macOS：statfs() 的 f_fstypename 為 smbfs/nfs/afpfs/webdav…或 f_flags 沒有 MNT_LOCAL → 沒有；
    statfs 失敗時改用 NSURLVolumeIsLocalKey。"""
    return volume_info(path)["trash"]


def on_battery():
    try:
        import psutil
        b = psutil.sensors_battery()
        return bool(b and not b.power_plugged)
    except (ImportError, AttributeError, OSError, RuntimeError, NotImplementedError):
        return False


def analyze_workers():
    return max(1, min(3, (os.cpu_count() or 2) // 2))


def watch_interval(battery=None):
    """監看掃描間隔（秒）：接電源 30 秒，用電池 5 分鐘。"""
    return 300 if (on_battery() if battery is None else battery) else 30


def app_data_dir():
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    d = os.path.join(base, "HighlightEditor")
    os.makedirs(d, exist_ok=True)
    return d


def scan_folder(folder, recursive=True):
    out = []
    if recursive:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            out += [os.path.join(root, f) for f in files]
    else:
        out = [os.path.join(folder, f) for f in os.listdir(folder)]
    return sorted(p for p in out if os.path.isfile(p)
                  and p.lower().endswith(core.VIDEO_EXTS + COMPANION_EXTS)
                  and not os.path.basename(p).startswith("._"))


def file_key(path):
    """(size, mtime, 部分雜湊：頭尾各 1MB + 大小)"""
    st = os.stat(path)
    h = hashlib.sha1(str(st.st_size).encode())
    with open(path, "rb") as f:
        h.update(f.read(1 << 20))
        if st.st_size > 2 << 20:
            f.seek(-(1 << 20), 2)
            h.update(f.read())
    return st.st_size, st.st_mtime, h.hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, path TEXT UNIQUE, size INT, mtime REAL,
  phash TEXT, duration REAL, width INT, height INT, has_audio INT, analyzed_key TEXT,
  error TEXT, in_list INT DEFAULT 1, added_at REAL, folder TEXT);
CREATE TABLE IF NOT EXISTS clips(id INTEGER PRIMARY KEY, file_id INT, start REAL, end REAL,
  score REAL, source TEXT, checked INT DEFAULT 0, ord INT, ai_start REAL, ai_end REAL,
  proxy TEXT, thumb TEXT);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS watched(folder TEXT PRIMARY KEY, recursive INT);
"""
MIGRATIONS = ["ALTER TABLE files ADD COLUMN companions TEXT",
              "ALTER TABLE clips ADD COLUMN sig BLOB",       # 去重用小圖 (9x16x3 float32)
              "ALTER TABLE clips ADD COLUMN peak REAL",      # 最精彩的秒數
              "ALTER TABLE clips ADD COLUMN track TEXT",     # 主體水平位置軌跡 JSON
              "ALTER TABLE clips ADD COLUMN emb BLOB",       # 本機語意向量（CLIP，選用）
              "ALTER TABLE clips ADD COLUMN locked INTEGER DEFAULT 0",  # 換一批時一定保留
              "ALTER TABLE clips ADD COLUMN tags TEXT",      # 本機 CLIP 自動標籤 JSON（R15）
              "ALTER TABLE clips ADD COLUMN speed TEXT",     # 手動速度曲線 JSON（5 點，R26）
              "ALTER TABLE files ADD COLUMN worth TEXT",     # R54
              "ALTER TABLE clips ADD COLUMN strategy TEXT",  # R62：候選策略 JSON list（start/middle/people/action/whole）
              "ALTER TABLE clips ADD COLUMN touched INTEGER DEFAULT 0"]  # R68：使用者親手勾過/取消過（重算策略時保留）  # R62：候選策略 JSON list（start/middle/people/action/whole）


class Library:
    def __init__(self, root=None):
        self.root = root or app_data_dir()
        self.cache_dir = os.path.join(self.root, "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.db = sqlite3.connect(os.path.join(self.root, "library.db"))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for m in MIGRATIONS:
            try:
                self.db.execute(m)
            except sqlite3.OperationalError:
                pass
        self._undo = []

    # ---------- 設定 ----------
    def get(self, k, default=None):
        r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else default

    def set(self, k, v):
        self.db.execute("REPLACE INTO kv VALUES(?,?)", (k, json.dumps(v)))
        self.db.commit()

    # ---------- R62：使用者對候選策略的偏好 ----------
    def strategy_prefs(self):
        """{策略: {"picks": 使用者手動勾選次數, "shown": 顯示次數}}；core.strategy_weights 用來排序。"""
        return self.get("strategy_stats", {}) or {}

    def _bump_strategy(self, names, field, n=1):
        if not names:
            return
        st = self.strategy_prefs()
        for k in names:
            st.setdefault(k, {"picks": 0, "shown": 0})[field] += n
        self.db.execute("REPLACE INTO kv VALUES(?,?)", ("strategy_stats", json.dumps(st)))

    # ---------- R68：策略設定（7 種，每種 on/len/n） ----------
    def strategy_cfg(self):
        """{策略: {on, len, n}}（已合併預設、夾回範圍）。舊版的 strategies_enabled 自動轉換。"""
        cfg = self.get("strategy_cfg")
        if cfg is None:
            return core.strategy_config(None, self.get("strategies_enabled") or None)
        return core.strategy_config(cfg)

    def set_strategy_cfg(self, cfg):
        cfg = core.strategy_config(cfg)
        self.set("strategy_cfg", cfg)
        self.set("strategies_enabled", [k for k, v in cfg.items() if v["on"]])
        return cfg

    def enabled_strategies(self):
        return {k for k, v in self.strategy_cfg().items() if v["on"]}

    def _feat_path(self, fid):
        return os.path.join(self.cache_dir, f"feat_{fid}.pkl")

    def _save_features(self, fid, cands):
        F = getattr(cands, "features", None)
        if F is None:
            return
        import pickle
        try:
            with open(self._feat_path(fid) + ".tmp", "wb") as fh:
                pickle.dump(F, fh, protocol=4)
            os.replace(self._feat_path(fid) + ".tmp", self._feat_path(fid))
        except (OSError, pickle.PicklingError) as e:
            log.warning("feature cache %s: %s", fid, e)

    def _load_features(self, fid):
        import pickle
        try:
            with open(self._feat_path(fid), "rb") as fh:
                return pickle.load(fh)
        except Exception:   # noqa: BLE001 — 快取壞了就重新解碼
            return None

    def recompute_strategies(self, fids=None, proxies=True, progress=None):
        """R68：策略設定改了 → 只重算候選（用特徵快取，不重新解碼；沒有快取的才重新分析）。
        保留：手動片段、已鎖定、微調過、使用者親手勾選的；其他 AI 候選依新設定替換。
        新候選若跟保留的片段重疊（IoU>0.6）就不重複新增，改把新策略標籤併到保留的那段。"""
        cfg = self.strategy_cfg(); prefs = self.strategy_prefs()
        if fids is None:
            fids = [r[0] for r in self.db.execute("SELECT id FROM files WHERE in_list=1 AND analyzed_key IS NOT NULL")]
        done = []
        for i, fid in enumerate(fids):
            if progress:
                progress(i, len(fids))
            r = self.db.execute("SELECT path, duration, analyzed_key FROM files WHERE id=?", (fid,)).fetchone()
            if not r or not r["analyzed_key"]:
                continue
            src = self.analysis_source(fid)
            try:
                cnt, sl = r["analyzed_key"].split(":")
                cnt = int(cnt); sl = None if sl == "None" else float(sl)
            except ValueError:
                cnt, sl = 2, None
            F = self._load_features(fid)
            try:
                if F is not None and r["duration"]:
                    cands = core.candidates_from_features(F, src, float(r["duration"]), cnt, sl, prefs=prefs, cfg=cfg)
                else:
                    cands = core.candidates_for_video(src, cnt, sl, prefs=prefs, cfg=cfg)
                    self._save_features(fid, cands)
            except core.Cancelled:
                raise
            except ANALYZE_ERRORS as e:
                log.warning("recompute failed %s: %s", r["path"], e)
                continue
            self._replace_candidates(fid, cands, proxies)
            done.append(fid)
        return done

    def _replace_candidates(self, fid, cands, proxies=True):
        rows = self.clips(fid)
        def kept(c):
            trimmed = c["ai_start"] is not None and (abs(c["start"] - c["ai_start"]) > 1e-3 or abs(c["end"] - c["ai_end"]) > 1e-3)
            return c["source"] != "ai" or c["locked"] or trimmed or (c["checked"] and c.get("touched"))
        keep = [c for c in rows if kept(c)]
        drop = [c for c in rows if not kept(c)]
        made = []
        try:
            for c in drop:
                self.db.execute("DELETE FROM clips WHERE id=?", (c["id"],))
            fresh = []
            for c in cands:
                hit = next((k for k in keep if core._iou((k["start"], k["end"]), (c.start, c.end)) > core.STRAT_CFG["merge_iou"]), None)
                if hit is not None:
                    if hit["source"] == "ai":
                        old = json.loads(hit.get("strategy") or "[]")
                        new = old + [s for s in (getattr(c, "strategies", None) or []) if s not in old]
                        self.db.execute("UPDATE clips SET strategy=? WHERE id=?", (json.dumps(new), hit["id"]))
                    continue
                fresh.append(c)
            has_checked = any(k["checked"] for k in keep)
            wi = None
            w = self.db.execute("SELECT worth FROM files WHERE id=?", (fid,)).fetchone()
            try:
                wi = json.loads(w[0]) if w and w[0] else None
            except ValueError:
                wi = None
            worth_keep = True if wi is None else bool(wi.get("keep", True))
            top = max([c.score for c in cands] + [self.db.execute(
                "SELECT COALESCE(MAX(score),0) FROM clips WHERE file_id<>? AND source='ai'", (fid,)).fetchone()[0]])
            first = next((c for c in cands if not getattr(c, "optional", False)), None)
            nxt = (self.db.execute("SELECT MAX(ord) FROM clips").fetchone()[0] or 0) + 1
            for c in fresh:
                chk = (not has_checked and worth_keep and c is first and c.score >= LOW_REL * top)
                cur = self.db.execute(
                    "INSERT INTO clips(file_id,start,end,score,source,checked,ord,ai_start,ai_end,sig,peak,track,strategy) "
                    "VALUES(?,?,?,?,'ai',?,?,?,?,?,?,?,?)",
                    (fid, c.start, c.end, c.score, int(chk), nxt if chk else None, c.start, c.end,
                     getattr(c, "sig", None) is not None and np.asarray(c.sig).astype("float32").tobytes() or None,
                     getattr(c, "peak", None), json.dumps(getattr(c, "track", None)),
                     json.dumps(getattr(c, "strategies", None)) if getattr(c, "strategies", None) else None))
                if chk:
                    nxt += 1
                if proxies:
                    made += self._make_assets(cur.lastrowid, remove_old=False)
            self.db.commit()
        except BaseException:
            self.db.rollback(); self._rm(*made); raise
        self._rm(*[x for c in drop for x in (c["proxy"], c["thumb"])])

    def set_roll(self, cid, deg):
        """R40：每段手動水平角度；None＝自動（重力感測）。"""
        if deg is None:
            self.db.execute("DELETE FROM kv WHERE k=?", (f"roll:{cid}",)); self.db.commit()
        else:
            self.set(f"roll:{cid}", float(deg))

    # ---------- 匯入 ----------
    def add_files(self, paths, folder=None, find_siblings=True):
        """匯入檔案；同組的 .insv/.lrv/.thm 只算一支（主檔 MP4 > LRV > INSV），其餘記為附屬檔。"""
        paths = [os.path.abspath(p) for p in paths]
        if find_siblings:
            paths = paths + [q for p in paths for q in _siblings(p)]
        ids = []
        for g in group_files(paths):
            p, comps = g["primary"], [m for m in g["members"] if m != g["primary"]]
            r = None
            for m in g["members"]:
                r = self.db.execute("SELECT id,path,companions FROM files WHERE path=?", (m,)).fetchone()
                if r:
                    break
            if r is None:   # 也許它是某筆紀錄的附屬檔
                for row in self.db.execute("SELECT id,path,companions FROM files WHERE companions LIKE ?",
                                           ("%" + os.path.basename(p) + "%",)):
                    if p in json.loads(row["companions"] or "[]"):
                        r = row; break
            if r:
                allm = set(json.loads(r["companions"] or "[]")) | set(g["members"])
                allm.discard(r["path"])
                self.db.execute("UPDATE files SET in_list=1, companions=? WHERE id=?",
                                (json.dumps(sorted(allm)), r["id"]))
                ids.append(r["id"]); continue
            size, mtime, ph = file_key(p)
            old = self.db.execute("SELECT id,path FROM files WHERE phash=? AND size=?",
                                  (ph, size)).fetchone()
            if old and not os.path.exists(old["path"]):
                self.db.execute("UPDATE files SET path=?, mtime=?, in_list=1, companions=? WHERE id=?",
                                (p, mtime, json.dumps(comps), old["id"]))
                ids.append(old["id"]); continue
            cur = self.db.execute(
                "INSERT INTO files(path,size,mtime,phash,added_at,folder,companions) VALUES(?,?,?,?,?,?,?)",
                (p, size, mtime, ph, time.time(), folder, json.dumps(comps)))
            ids.append(cur.lastrowid)
        self.db.commit()
        merged = self._pair_by_meta(ids)
        return [i for i in ids if i not in merged]

    def _pair_by_meta(self, ids):
        """R38：檔名被改掉（例如上傳後變成雜湊）時，用長度/fps/比例/拍攝時間把只有 LRV 的紀錄併到對應的 MP4。
        回傳被併掉的 LRV 紀錄 id。"""
        rows = {r["id"]: r for r in self.db.execute("SELECT id,path,companions FROM files WHERE in_list=1")}
        lrvs = [i for i, r in rows.items() if r["path"].lower().endswith(".lrv")] if ids else []
        if not lrvs:
            return set()
        mp4s = [r for r in rows.values() if r["path"].lower().endswith((".mp4", ".mov"))
                and not any(c.lower().endswith(".lrv") for c in json.loads(r["companions"] or "[]"))]
        meta = {}
        def M(p):
            if p not in meta:
                try:
                    meta[p] = core.quick_meta(p)
                except Exception:
                    meta[p] = None
            return meta[p]
        merged = set()
        for li in lrvs:
            lp = rows[li]["path"]
            for r in mp4s:
                if r["id"] in merged or os.path.dirname(r["path"]) != os.path.dirname(lp):
                    continue
                if core.same_recording(M(lp), M(r["path"])):
                    comps = sorted(set(json.loads(r["companions"] or "[]")) | {lp} | set(json.loads(rows[li]["companions"] or "[]")))
                    self.db.execute("UPDATE files SET companions=? WHERE id=?", (json.dumps(comps), r["id"]))
                    self.db.execute("DELETE FROM clips WHERE file_id=?", (li,))
                    self.db.execute("DELETE FROM files WHERE id=?", (li,))
                    merged.add(li); mp4s = [x for x in mp4s if x["id"] != r["id"]]
                    break
        self.db.commit()
        return merged

    def group_members(self, fid):
        """主檔 + 附屬檔（.lrv/.thm/.insv…）。"""
        r = self.db.execute("SELECT path, companions FROM files WHERE id=?", (fid,)).fetchone()
        return [r["path"]] + json.loads(r["companions"] or "[]") if r else []

    def add_folder(self, folder, recursive=True, watch=True):
        if watch:
            self.db.execute("REPLACE INTO watched VALUES(?,?)", (os.path.abspath(folder), int(recursive)))
        return self.add_files(scan_folder(folder, recursive), folder=os.path.abspath(folder))

    def rescan(self):
        """重新掃描監看資料夾，回傳新加入的 file id。資料夾不存在（SD 卡拔出）時不改任何紀錄。"""
        known = set()
        for r in self.db.execute("SELECT path, companions FROM files"):
            known.add(r[0]); known.update(json.loads(r[1] or "[]"))
        before = {x[0] for x in self.db.execute("SELECT id FROM files")}
        new = []
        for r in self.db.execute("SELECT folder, recursive FROM watched").fetchall():
            if os.path.isdir(r[0]):
                fresh = [p for p in scan_folder(r[0], bool(r[1])) if p not in known]
                new += [i for i in self.add_files(fresh, folder=r[0]) if i not in before and i not in new]
        return new

    def watched_status(self):
        """[(folder, recursive, '已連線'|'已中斷連線')]"""
        return [(r[0], bool(r[1]), "已連線" if os.path.isdir(r[0]) else STATUS_OFFLINE)
                for r in self.db.execute("SELECT folder, recursive FROM watched")]

    # ---------- 狀態 ----------
    def status(self, fid):
        r = self.db.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
        if not os.path.exists(r["path"]):
            if r["folder"] and not os.path.isdir(r["folder"]):
                return STATUS_OFFLINE          # 整個資料夾/磁碟不在 → 不標成遺失
            return STATUS_MISSING
        if r["error"]:
            return STATUS_ERROR
        if not r["analyzed_key"]:
            return STATUS_PENDING
        st = os.stat(r["path"])
        if st.st_size != r["size"] or abs(st.st_mtime - r["mtime"]) > 1e-3:
            ph = file_key(r["path"])[2]
            if ph != r["phash"]:
                return STATUS_CHANGED
            self.db.execute("UPDATE files SET mtime=?,size=? WHERE id=?", (st.st_mtime, st.st_size, fid))
        return STATUS_DONE

    def files(self, include_removed=False):
        q = "SELECT * FROM files" + ("" if include_removed else " WHERE in_list=1") + " ORDER BY id"
        return [dict(r, status=self.status(r["id"])) for r in self.db.execute(q).fetchall()]

    def needs_analysis(self):
        return [f["id"] for f in self.files() if f["status"] in (STATUS_PENDING, STATUS_CHANGED)]

    # ---------- 分析 ----------
    def analyze(self, fid, count=2, seg_len=None, default_checked=2, proxies=True, force=False, pre=None):
        """分析一支影片。被 core.Cancelled 中止時整筆交易回復，舊的片段與快取檔都保留。"""
        st = self.status(fid)
        if st == STATUS_DONE and not force:
            return False
        r = self.db.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
        path = r["path"]
        src = self.analysis_source(fid)      # R37：有同名 LRV 時用 LRV 分析（快很多），輸出仍用 MP4
        try:
            if isinstance(pre, BaseException):
                raise pre
            info, cands = pre if pre else (core.probe(path), core.candidates_for_video(src, count, seg_len, cfg=self.strategy_cfg(),
                                                                                         prefs=self.strategy_prefs()))
        except core.Cancelled:
            raise
        except ANALYZE_ERRORS as e:
            log.warning("analyze failed %s: %s", path, e)
            self.db.execute("UPDATE files SET error=? WHERE id=?", (str(e), fid)); self.db.commit()
            return False
        old = self.db.execute("SELECT id,proxy,thumb FROM clips WHERE file_id=? AND source='ai'", (fid,)).fetchall()
        made = []
        try:
            self.db.executemany("DELETE FROM clips WHERE id=?", [(o["id"],) for o in old])  # 手動片段保留
            # REVIEW_r10 B5：明顯比媒體庫其他影片差（< 45% 最高分）的片段不自動勾選，卡片標「分數偏低」
            top = max([c.score for c in cands] + [self.db.execute(
                "SELECT COALESCE(MAX(score),0) FROM clips WHERE file_id<>? AND source='ai'", (fid,)).fetchone()[0]])
            best = [c for c in sorted(cands, key=lambda c: -c.score)[:default_checked] if c.score >= LOW_REL * top
                    and not getattr(c, "optional", False)]          # R50：可選的第二段預設不勾
            if not best and cands:
                best = [max(cands, key=lambda c: c.score)]
            # R54：跨檔排序（長度、連拍一組一支、近乎重複）→ 不值得留的影片，AI 片段預設不勾
            wi = self._worth_info(cands, info)
            if wi is not None and not self._rank_keep(fid, path, wi):
                best = []
            nxt = (self.db.execute("SELECT MAX(ord) FROM clips").fetchone()[0] or 0) + 1
            for c in cands:
                chk = c in best
                cur = self.db.execute(
                    "INSERT INTO clips(file_id,start,end,score,source,checked,ord,ai_start,ai_end,sig,peak,track,strategy) "
                    "VALUES(?,?,?,?,'ai',?,?,?,?,?,?,?,?)",
                    (fid, c.start, c.end, c.score, int(chk), nxt if chk else None, c.start, c.end,
                     getattr(c, "sig", None) is not None and c.sig.astype("float32").tobytes() or None,
                     getattr(c, "peak", None), json.dumps(getattr(c, "track", None)),
                     json.dumps(getattr(c, "strategies", None)) if getattr(c, "strategies", None) else None))
                self._bump_strategy(getattr(c, "strategies", None), "shown")
                if chk:
                    nxt += 1
                if proxies:
                    made += self._make_assets(cur.lastrowid, remove_old=False)
            size, mtime, ph = file_key(path)
            self.db.execute("UPDATE files SET duration=?,width=?,height=?,has_audio=?,size=?,mtime=?,"
                            "phash=?,analyzed_key=?,error=NULL WHERE id=?",
                            (info.duration, info.width, info.height, int(info.has_audio), size, mtime,
                             ph, f"{count}:{seg_len}", fid))
            if wi is not None:
                self.db.execute("UPDATE files SET worth=? WHERE id=?", (json.dumps(wi), fid))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            self._rm(*made)
            raise
        self._rm(*[x for o in old for x in (o["proxy"], o["thumb"])])
        self._save_features(fid, cands)      # R68：改策略時只重算候選
        return True

    @staticmethod
    def _worth_info(cands, info):
        if not hasattr(cands, "worth"):
            return None
        top = max(cands, key=lambda c: c.score) if cands else None
        sig = getattr(top, "sig", None) if top is not None else None
        return {"worth": float(cands.worth), "person": float(getattr(cands, "person", 0.0)),
                "bad": float(getattr(cands, "bad", 0.0)), "duration": float(info.duration),
                "sig": None if sig is None else [round(float(v), 3) for v in np.asarray(sig).ravel()]}

    def _rank_keep(self, fid, path, wi):
        """R54：跟媒體庫裡其他已分析影片一起跑 ranking.rank_files，回傳這支是否值得留。"""
        from . import ranking
        items = []
        for r in self.db.execute("SELECT id,path,mtime,worth FROM files WHERE worth IS NOT NULL AND id<>?", (fid,)):
            try:
                w = json.loads(r["worth"])
            except (TypeError, ValueError):
                continue
            items.append(dict(w, path=r["path"], id=r["id"], sig=None if w.get("sig") is None else np.array(w["sig"], np.float32)))
        me = dict(wi, path=path, id=fid, sig=None if wi.get("sig") is None else np.array(wi["sig"], np.float32))
        items.append(me)
        for it in items:
            if ranking._ts(it) is None:
                try:
                    it["time"] = os.path.getmtime(it["path"])
                except OSError:
                    pass
        ranking.rank_files(items)
        if len(items) < ranking.RANK_MIN:          # 媒體庫太少支時跨檔排序沒意義 → 一律保留
            me["keep"] = True
        wi["keep"] = me["keep"]; wi["worth_n"] = me["worth_n"]
        return me["keep"]

    def analyze_pending(self, progress=None, workers=None, **kw):
        """R27：多支影片時，解碼＋評分（純計算、各自一個 ffmpeg）平行跑；寫資料庫與產生預覽仍在本執行緒依序做。
        workers 預設 = min(3, CPU 數 // 2)，至少 1；IE_ANALYZE_WORKERS 可覆寫。"""
        ids = self.needs_analysis()
        n = workers or int(os.environ.get("IE_ANALYZE_WORKERS", 0)) or analyze_workers()
        if n <= 1 or len(ids) < 2:
            for i, fid in enumerate(ids):
                if progress:
                    progress(i, len(ids))
                self.analyze(fid, **kw)
            return ids
        from concurrent.futures import ThreadPoolExecutor
        cancel = getattr(core._tls, "cancel", None)
        count, seg_len = kw.get("count", 2), kw.get("seg_len", None)
        paths = {fid: self.db.execute("SELECT path FROM files WHERE id=?", (fid,)).fetchone()["path"] for fid in ids}
        srcs = {fid: self.analysis_source(fid) for fid in ids}
        prefs = self.strategy_prefs()
        cfg = self.strategy_cfg()   # 主執行緒讀好，worker 不碰 SQLite

        def work(fid):
            core.set_cancel(cancel)   # 取消檢查是每個執行緒各自設定
            try:
                return core.probe(paths[fid]), core.candidates_for_video(srcs[fid], count, seg_len, prefs=prefs, cfg=cfg)
            except BaseException as e:   # 交給 analyze() 用同一套規則處理（記錄錯誤或往上丟）
                return e
        with ThreadPoolExecutor(n) as ex:
            futs = [ex.submit(work, fid) for fid in ids]
            try:
                for i, (fid, f) in enumerate(zip(ids, futs)):
                    if progress:
                        progress(i, len(ids))
                    self.analyze(fid, pre=f.result(), **kw)
            except BaseException:
                for f in futs:
                    f.cancel()
                raise
        return ids

    def analysis_source(self, fid):
        """R37：主檔是 MP4/MOV 且同組有 .lrv（Insta360 低解析預覽檔）→ 回傳 LRV，否則主檔。
        兩者長度差超過 1 秒（不是同一段錄影）就不用 LRV。IE_NO_LRV=1 可關閉（測速用）。"""
        r = self.db.execute("SELECT path, companions FROM files WHERE id=?", (fid,)).fetchone()
        if not r:
            return None
        if os.environ.get("IE_NO_LRV") or os.path.splitext(r[0])[1].lower() not in (".mp4", ".mov", ".m4v"):
            return r[0]
        lrv = [p for p in json.loads(r[1] or "[]") if p.lower().endswith(".lrv") and os.path.exists(p)]
        if not lrv:
            return r[0]
        k = f"lrvok:{lrv[0]}:{int(os.path.getmtime(lrv[0]))}"
        v = self.get(k)
        if v is None:
            try:
                v = "1" if abs(core.probe(lrv[0]).duration - core.probe(r[0]).duration) <= 1.0 else "0"
            except Exception:
                v = "0"
            self.set(k, v)
        return lrv[0] if v == "1" else r[0]

    def low_res(self, fid):
        """R37：只有 LRV、沒有原始 MP4 → 仍可用，但介面標「低解析來源」。"""
        r = self.db.execute("SELECT path FROM files WHERE id=?", (fid,)).fetchone()
        return bool(r) and r[0].lower().endswith((".lrv", ".lrf"))

    def projection(self, fid):
        r = self.db.execute("SELECT path FROM files WHERE id=?", (fid,)).fetchone()
        return core.detect_projection(self.analysis_source(fid)) if r else ""

    def _make_assets(self, cid, remove_old=True):
        c = self.db.execute("SELECT c.*, f.path FROM clips c JOIN files f ON f.id=c.file_id WHERE c.id=?",
                            (cid,)).fetchone()
        base = os.path.join(self.cache_dir, f"c{cid}_{int(c['start']*100)}_{int(c['end']*100)}")
        src = self.analysis_source(c["file_id"])     # R37：預覽小檔/縮圖也從 LRV 做
        seg = core.Segment(src, c["start"], c["end"])
        proxy = core.preview_proxy(seg, base + ".mp4")
        thumb = core.thumbnail(src, c["start"], base + ".jpg")
        if remove_old:
            self._rm(*[p for p in (c["proxy"], c["thumb"]) if p not in (proxy, thumb)])
        self.db.execute("UPDATE clips SET proxy=?, thumb=? WHERE id=?", (proxy, thumb, cid))
        return [p for p in (proxy, thumb) if p]

    @staticmethod
    def _rm(*paths):
        for p in paths:
            if p and os.path.exists(p):
                os.remove(p)

    def _drop_clips(self, fid, sources=("ai", "manual")):
        q = f"SELECT id,proxy,thumb FROM clips WHERE file_id=? AND source IN ({','.join('?'*len(sources))})"
        for c in self.db.execute(q, (fid, *sources)).fetchall():
            self._rm(c["proxy"], c["thumb"])
            self.db.execute("DELETE FROM clips WHERE id=?", (c["id"],))

    # ---------- 片段 / 勾選 / 順序 ----------
    def clips(self, fid):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM clips WHERE file_id=? ORDER BY start", (fid,))]

    def add_manual_clip(self, fid, start, end, checked=True):
        cur = self.db.execute("INSERT INTO clips(file_id,start,end,score,source,checked) "
                              "VALUES(?,?,?,0,'manual',0)", (fid, start, end))
        self._make_assets(cur.lastrowid)
        if checked:
            self.set_checked(cur.lastrowid, True)
        self.db.commit()
        return cur.lastrowid

    def set_checked(self, cid, on):
        if on:
            r = self.db.execute("SELECT checked, strategy FROM clips WHERE id=? AND source='ai'", (cid,)).fetchone()
            if r is not None and not r["checked"] and r["strategy"]:
                try:
                    self._bump_strategy(json.loads(r["strategy"]), "picks")   # R62：記錄使用者勾了哪種策略
                except ValueError:
                    pass
            nxt = (self.db.execute("SELECT MAX(ord) FROM clips").fetchone()[0] or 0) + 1
            self.db.execute("UPDATE clips SET checked=1, touched=1, ord=COALESCE(ord, ?) WHERE id=?", (nxt, cid))
        else:
            self.db.execute("UPDATE clips SET checked=0, touched=1 WHERE id=?", (cid,))   # 保留 ord：重新勾選回到原位（B6）
        self.db.commit()

    def trim(self, cid, start, end, regen=True):
        self.db.execute("UPDATE clips SET start=?, end=? WHERE id=?", (start, end, cid))
        if regen:
            self._make_assets(cid)
        self.db.commit()

    def set_speed(self, cid, curve):
        """R26：手動速度曲線（5 個 0.25–4 倍的數字；None＝原速）。"""
        from . import smart
        val = json.dumps([smart.clamp_speed(v) for v in curve]) if curve else None
        if curve and len(curve) != len(smart.CURVE_U):
            raise ValueError("速度曲線要有 5 個點")
        self.db.execute("UPDATE clips SET speed=? WHERE id=?", (val, cid)); self.db.commit()

    def reset_trim(self, cid):
        c = self.db.execute("SELECT ai_start, ai_end FROM clips WHERE id=?", (cid,)).fetchone()
        if c["ai_start"] is not None:
            self.trim(cid, c["ai_start"], c["ai_end"])

    def timeline(self):
        rows = self.db.execute("SELECT c.*, f.path, f.duration FROM clips c JOIN files f ON f.id=c.file_id "
                               "WHERE c.checked=1 AND f.in_list=1 ORDER BY c.ord, c.id").fetchall()
        return [dict(r) for r in rows]

    def set_order(self, clip_ids):
        for i, cid in enumerate(clip_ids, 1):
            self.db.execute("UPDATE clips SET ord=? WHERE id=?", (i, cid))
        self.db.commit()

    def timeline_clip_items(self):
        """R65：[(Segment, strategies)]，給 core.export_clips 單段匯出用（順序同時間軸）。"""
        segs = self.timeline_segments()
        rows = [c for c in self.timeline() if os.path.exists(c["path"])]
        out = []
        for s, c in zip(segs, rows):
            try:
                st = json.loads(c.get("strategy") or "[]")
            except ValueError:
                st = []
            out.append((s, st if c.get("source") != "manual" else ["manual"]))
        return out

    def timeline_segments(self):
        out = []
        for c in self.timeline():
            if not os.path.exists(c["path"]):
                continue
            s = core.Segment(c["path"], c["start"], c["end"], c["score"])
            if c.get("peak") is not None and c["start"] <= c["peak"] <= c["end"]:
                s.peak = c["peak"]
            if c.get("track"):
                s.track = c["track"]
            src = self.analysis_source(c["file_id"]) if c.get("file_id") else None
            if src and src != c["path"]:
                s.analysis_path = src            # R39：魚眼跟拍在 LRV 上算
            r = self.get(f"roll:{c['id']}") if c.get("id") else None
            if r is not None:
                s.roll = float(r)                # R40：手動水平（每段）
            s.duration = c.get("duration") or c["end"]
            if c.get("speed"):
                s.curve = json.loads(c["speed"])
            out.append(s)
        return out

    # ---------- 離線 AI ----------
    def clip_rows(self):
        rows = self.db.execute("SELECT c.*, f.path, f.mtime AS ftime, f.duration FROM clips c JOIN files f "
                               "ON f.id=c.file_id WHERE f.in_list=1").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["sig"] = np.frombuffer(r["sig"], np.float32).reshape(9, 16, 3) if r["sig"] else None
            out.append(d)
        return out

    def music_beats(self, path):
        """音樂節拍分析結果快取在素材庫（依檔案大小+修改時間）。"""
        from . import beats
        st = os.stat(path); k = f"beats:{path}:{st.st_size}:{int(st.st_mtime)}"
        v = self.get(k)
        if v:
            return json.loads(v) if isinstance(v, str) else v
        m = beats.analyze_music(path); self.set(k, json.dumps(m))
        return m

    def apply_selection(self, ids):
        """只勾選 ids（依順序排進時間軸），其他取消勾選。"""
        self.db.execute("UPDATE clips SET checked=0, ord=NULL")
        self.db.executemany("UPDATE clips SET checked=1, ord=? WHERE id=?", [(i + 1, c) for i, c in enumerate(ids)])
        self.db.commit()

    def auto_pick(self, target=60.0, reshuffle=False, prefer_tag=None, only_fids=None, people=0, smile=False):
        """reshuffle=True：「換一批」，保留鎖定的片段，其餘盡量換成上一批沒選的。
        prefer_tag：主題標籤（字串或清單），有標籤的片段分數 ×1.6。
        only_fids：只從這些影片挑（R32「用這組做影片」）；people：多一點人（R34）；
        被「這段不要」排除的片段（kv excluded）不會再被自動挑（R34）。"""
        from . import smart, convenience as CV
        rows = self.clip_rows()
        tags = [prefer_tag] if isinstance(prefer_tag, str) and prefer_tag else list(prefer_tag or [])
        if tags:
            rows = [dict(r, score=r["score"] * (1.6 if set(tags) & set(json.loads(r.get("tags") or "[]")) else 1.0))
                    for r in rows]
        if people or smile:
            rows = [dict(r, score=CV.people_score(r, max(people, 1 if smile else 0))) for r in rows]
        ex = set(self.excluded())
        if only_fids is not None:
            fs = set(only_fids)
            rows = [r for r in rows if r["file_id"] in fs or r.get("locked")]
        rows = [r for r in rows if r["id"] not in ex or r.get("locked")]
        locked = [r["id"] for r in rows if r.get("locked")]
        avoid = [r["id"] for r in rows if r["checked"] and not r.get("locked")] if reshuffle else []
        ids = smart.auto_pick(rows, target, locked=locked, avoid=avoid)
        self.apply_selection(ids)
        return ids

    def excluded(self):
        return json.loads(self.get("excluded", "[]") or "[]")

    def exclude(self, cids):
        """R34「這段不要」：取消勾選並記住，之後自動挑選跳過（鎖定的不受影響）。"""
        ex = sorted(set(self.excluded()) | set(cids))
        self.set("excluded", json.dumps(ex))
        self.db.executemany("UPDATE clips SET checked=0, ord=NULL WHERE id=? AND COALESCE(locked,0)=0", [(c,) for c in cids])
        self.db.commit()

    def file_meta(self, fid):
        """(拍攝時間 epoch, (lat,lon)|None)。讀 creation_time / GPS metadata，沒有就用檔案修改時間；結果快取在 kv。"""
        r = self.db.execute("SELECT path, mtime FROM files WHERE id=?", (fid,)).fetchone()
        if not r:
            return None, None
        k = f"meta:{r[0]}:{int(r[1] or 0)}"
        v = self.get(k)
        if v:
            d = json.loads(v); return d["t"], tuple(d["g"]) if d["g"] else None
        from . import convenience as CV
        t, g = None, None
        try:
            p = core._run([core.find_ffmpeg(), "-hide_banner", "-i", r[0]])
            t, g = CV.parse_meta(p.stderr.decode("utf-8", "replace"))
        except Exception:
            pass
        t = t or r[1]
        self.set(k, json.dumps({"t": t, "g": list(g) if g else None}))
        return t, g

    def trips(self, gap_hours=8.0):
        """R32：依拍攝日/旅程分組。"""
        from . import convenience as CV
        items = []
        for (fid,) in self.db.execute("SELECT id FROM files WHERE in_list=1").fetchall():
            t, g = self.file_meta(fid)
            items.append({"id": fid, "t": t, "gps": g})
        return CV.group_trips(items, gap_hours=gap_hours)

    def known_paths(self):
        known = set()
        for r in self.db.execute("SELECT path, companions FROM files"):
            known.add(r[0]); known.update(json.loads(r[1] or "[]"))
        return known

    def set_locked(self, cid, on):
        self.db.execute("UPDATE clips SET locked=?, checked=CASE WHEN ? THEN 1 ELSE checked END WHERE id=?",
                        (1 if on else 0, 1 if on else 0, cid))
        self.db.commit()

    def _ensure_embs(self, rows):
        from . import semantic
        need = [r for r in rows if r["emb"] is None and r["thumb"] and os.path.exists(r["thumb"])]
        if need:
            E = semantic.embed_images([r["thumb"] for r in need])
            self.db.executemany("UPDATE clips SET emb=? WHERE id=?", [(e.tobytes(), r["id"]) for e, r in zip(E, need)])
            self.db.commit()
            return self.clip_rows()
        return rows

    def tag_clips(self, force=False):
        """用本機 CLIP 幫每段貼場景標籤（海/山/雪/夜景/人物/寵物）。沒裝 CLIP 回傳 None。"""
        from . import semantic
        if not semantic.has_clip():
            return None
        ver = semantic.tagger_version()
        if self.get("tagger_version") != ver:
            force = True   # R29：標籤器升級 → 舊標籤全部重貼
        rows = self._ensure_embs(self.clip_rows())
        todo = [r for r in rows if r["emb"] and (force or r.get("tags") is None)]
        if todo:
            T = semantic.auto_tags([np.frombuffer(r["emb"], np.float32) for r in todo])
            self.db.executemany("UPDATE clips SET tags=? WHERE id=?",
                                [(json.dumps(t, ensure_ascii=False), r["id"]) for t, r in zip(T, todo)])
            self.db.commit()
        self.set("tagger_version", ver)
        return len(todo)

    def tag_counts(self):
        from collections import Counter
        c = Counter()
        for r in self.clip_rows():
            c.update(json.loads(r.get("tags") or "[]"))
        return c

    def semantic_search(self, q, allow_clip=True):
        """回傳 (符合的 clip id 依相關度排序, 模式 'clip' / 'basic' / 'unknown')。向量快取在 clips.emb。"""
        from . import semantic
        rows = self.clip_rows()
        if allow_clip and semantic.has_clip():
            need = [r for r in rows if r["emb"] is None and r["thumb"] and os.path.exists(r["thumb"])]
            if need:
                E = semantic.embed_images([r["thumb"] for r in need])
                self.db.executemany("UPDATE clips SET emb=? WHERE id=?",
                                    [(e.tobytes(), r["id"]) for e, r in zip(E, need)])
                self.db.commit()
                rows = self.clip_rows()
            embs = {r["id"]: np.frombuffer(r["emb"], np.float32) for r in rows if r["emb"]}
            return [i for i, _ in semantic.rank(q, embs)], "clip"
        res, known = semantic.basic_rank(q, {r["id"]: r["sig"] for r in rows})
        return [i for i, _ in res], ("basic" if known else "unknown")

    # ---------- 移除 / 刪除 ----------
    def remove_from_list(self, fids):
        """從清單移除（保留檔案與快取，可復原）。"""
        fids = list(fids)
        self.db.executemany("UPDATE files SET in_list=0 WHERE id=?", [(f,) for f in fids])
        self.db.commit()
        self._undo.append(fids)
        return fids

    def undo_remove(self):
        if not self._undo:
            return []
        fids = self._undo.pop()
        self.db.executemany("UPDATE files SET in_list=1 WHERE id=?", [(f,) for f in fids])
        self.db.commit()
        return fids

    def purge(self, fids):
        """從素材庫徹底清除（含快取），不碰原始檔。"""
        for f in fids:
            self._drop_clips(f)
            self.db.execute("DELETE FROM files WHERE id=?", (f,))
        self.db.commit()

    def delete_plan(self, fids):
        """確認對話框用：每支影片的整組檔案、大小、磁碟種類與名稱、有沒有垃圾桶。"""
        groups = []
        for f in fids:
            ms = self.group_members(f)
            if not ms:
                continue
            files = [(m, os.path.getsize(m) if os.path.exists(m) else 0) for m in ms]
            vols = [volume_info(m) for m in ms if os.path.exists(m)]
            bad = [v for v in vols if not v["trash"]]
            previews = [m for m in ms if os.path.splitext(m)[1].lower() in PREVIEW_EXTS]
            groups.append({"fid": f, "name": group_name(ms[0]), "primary_ext": os.path.splitext(ms[0])[1][1:].upper(),
                           "files": files, "bytes": sum(b for _, b in files),
                           "trash": not bad, "volume": (bad[0]["label"] if bad else ""),
                           "volume_kind": (bad[0]["kind"] if bad else "local"),
                           "previews": previews,
                           "previews_only_ok": bool(previews) and len(previews) < len(ms)})
        return {"count": len(groups), "names": [g["name"] for g in groups], "groups": groups,
                "file_count": sum(len(g["files"]) for g in groups),
                "total_bytes": sum(g["bytes"] for g in groups),
                "no_trash": [g["fid"] for g in groups if not g["trash"]],
                "no_trash_volumes": sorted({g["volume"] for g in groups if not g["trash"]})}

    delete_summary = delete_plan

    def delete_files(self, fids, allow_permanent=False, skip_no_trash=False, previews_only=False):
        """把整組原始檔（主檔 + .lrv/.thm…）移到垃圾桶/資源回收筒，並清除快取。
        磁碟沒有垃圾桶時：
          allow_permanent=False → 不刪除，原因 'no_trash'（skip_no_trash=True 時原因為 'skipped'，其餘照常進垃圾桶）；
          allow_permanent=True  → 永久刪除（UI 須先勾「我了解無法還原」）。
        previews_only=True（O2）：只刪除 .lrv/.lrf/.thm，保留原始檔；該筆影片改以剩下的檔案為主檔，勾選保留。
        回傳 (成功 fid, 失敗[(path, 原因)])。"""
        from send2trash import send2trash
        ok, fail, kept = [], [], []
        for f in fids:
            allm = self.group_members(f)
            if not allm:
                continue
            ms = [m for m in allm if os.path.exists(m)]
            if previews_only:
                ms = [m for m in ms if os.path.splitext(m)[1].lower() in PREVIEW_EXTS]
                if not ms or len(ms) == len([m for m in allm if os.path.exists(m)]):
                    fail.append((allm[0], "no_original")); continue
            has_trash = all(trash_supported(m) for m in ms)
            if not has_trash and not allow_permanent:
                fail += [(m, "skipped" if skip_no_trash else "no_trash") for m in ms]; continue
            errs = []
            for m in ms:
                try:
                    send2trash(m) if has_trash else os.remove(m)
                except OSError as e:  # send2trash 的 TrashPermissionError 也是 OSError
                    errs.append((m, str(e)))
            fail += errs
            if errs:
                continue
            if previews_only:
                rest = [m for m in allm if os.path.exists(m)]
                g = group_files(rest)[0] if group_files(rest) else {"primary": rest[0]}
                size, mtime, ph = file_key(g["primary"])
                self.db.execute("UPDATE files SET path=?, size=?, mtime=?, phash=?, companions=? WHERE id=?",
                                (g["primary"], size, mtime, ph,
                                 json.dumps([m for m in rest if m != g["primary"]]), f))
                kept.append(f)
            ok.append(f)
        self.db.commit()
        self.purge([f for f in ok if f not in kept])
        return ok, fail

    # ---------- 快取管理 ----------
    def cache_size(self):
        return sum(os.path.getsize(os.path.join(self.cache_dir, f)) for f in os.listdir(self.cache_dir))

    def clear_cache(self, keep_selections=True):
        """清除 proxy/縮圖與分析結果；勾選與微調可保留（下次重產 proxy）。"""
        shutil.rmtree(self.cache_dir, ignore_errors=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        self.db.execute("UPDATE clips SET proxy=NULL, thumb=NULL")
        if not keep_selections:
            self.db.execute("DELETE FROM clips")
            self.db.execute("UPDATE files SET analyzed_key=NULL")
        self.db.commit()

    def regen_missing_assets(self):
        for r in self.db.execute("SELECT id FROM clips WHERE proxy IS NULL").fetchall():
            self._make_assets(r[0])
        self.db.commit()

    def close(self):
        self.db.close()
