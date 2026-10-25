"""核心：ffmpeg 定位、探測、精華偵測、輸出。無 GUI 依賴。"""
import os
import tempfile, re, sys, shutil, subprocess, tempfile, dataclasses, threading, functools
import numpy as np

VIDEO_EXTS = (".mp4", ".mov", ".lrv", ".insv", ".m4v")
_NOWIN = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


def find_ffmpeg():
    env = os.environ.get("FFMPEG_BINARY")
    if env and os.path.exists(env):
        return env
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    for name in ("ffmpeg.exe", "ffmpeg"):
        p = os.path.join(base, "bin", name)
        if os.path.exists(p):
            return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    for p in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if p and os.path.exists(p):
            return p
    raise RuntimeError("找不到 ffmpeg。請執行 pip install imageio-ffmpeg 或安裝 ffmpeg。")


_tls = threading.local()


@functools.lru_cache(None)
def has_filter(name):
    """這個 ffmpeg 有沒有某個濾鏡（例如 imageio-ffmpeg 內建版本沒有 drawtext）。"""
    try:
        r = subprocess.run([find_ffmpeg(), "-hide_banner", "-filters"], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, creationflags=_NOWIN, text=True, errors="replace")
        return any(l.split()[1:2] == [name] for l in r.stdout.splitlines() if len(l.split()) > 1)
    except Exception:
        return False


def set_cancel(fn):
    """為目前執行緒設定取消檢查函式；之後這個執行緒的 ffmpeg 呼叫都可在執行中被中止（停止分析）。"""
    _tls.cancel = fn


def _run(args, **kw):
    cancel = getattr(_tls, "cancel", None)
    if cancel is None:
        return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              creationflags=_NOWIN, **kw)
    if cancel():
        raise Cancelled()
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NOWIN, **kw)
    while True:
        try:
            out, err = p.communicate(timeout=0.1)
            break
        except subprocess.TimeoutExpired:
            if cancel():
                p.kill(); p.communicate()
                raise Cancelled()
    return subprocess.CompletedProcess(args, p.returncode, out, err)


@dataclasses.dataclass
class MediaInfo:
    path: str
    duration: float
    width: int
    height: int
    has_audio: bool


_PROJ_CACHE = {}


def classify_projection(w, h, gray=None):
    """R37：flat／equirect（2:1 全景）／dfisheye（雙魚眼：左右兩個圓、四角與兩圓之間的角落近乎全黑）。
    gray：縮成 64x32 的灰階畫面（numpy，0..255），沒有就只看比例。"""
    if h and abs(w / h - 1) < 0.03 and gray is not None:
        return "fisheye" if is_circular_fisheye(gray) else ""
    if not h or abs(w / h - 2) > 0.03:
        return ""
    if gray is None:
        return "equirect"
    g = np.asarray(gray, np.float32); H, W = g.shape
    k = max(2, H // 8)
    corners = [g[:k, :k], g[:k, -k:], g[-k:, :k], g[-k:, -k:], g[:k, W // 2 - k // 2:W // 2 + k // 2],
               g[-k:, W // 2 - k // 2:W // 2 + k // 2]]
    dark = max(float(c.mean()) for c in corners)
    centers = min(float(g[H // 2 - k:H // 2 + k, W // 4 - k:W // 4 + k].mean()),
                  float(g[H // 2 - k:H // 2 + k, 3 * W // 4 - k:3 * W // 4 + k].mean()))
    return "dfisheye" if dark < 12 and centers > dark + 25 else "equirect"


FISHEYE_FOV = float(os.environ.get("IE_FISHEYE_FOV", 190))   # R38：單一圓形魚眼的鏡頭視角；依真實樣本（Ambarella、2688²）目測調整


def is_circular_fisheye(gray):
    """方形畫面＋四角近黑＋中心亮 → 單一圓形魚眼（例如 Insta360 單鏡頭/拇指相機的 MP4/LRV）。
    圓可能略大於畫面（左右被切到），所以只看四個角落 1/8 區塊。"""
    g = np.asarray(gray, np.float32); H, W = g.shape
    k = max(2, min(H, W) // 10)
    corners = [g[:k, :k], g[:k, -k:], g[-k:, :k], g[-k:, -k:]]
    dark = max(float(np.percentile(c, 75)) for c in corners)
    center = float(g[H // 2 - H // 4:H // 2 + H // 4, W // 2 - W // 4:W // 2 + W // 4].mean())
    return dark < 30 and center > dark + 40


FISHEYE_VIEW = float(os.environ.get("IE_FISHEYE_VIEW", 125))


def fisheye_view(W, H, x=0.5, y=0.5, fov=None, view=None):
    """R38：圓形魚眼 → 一般畫面的 v360 參數。長邊視角＝view 度；(x, y) 是主體在魚眼畫面中的位置（0..1），
    轉成 yaw/pitch，並限制在鏡頭範圍內（不會看到黑邊）。"""
    import math
    fov = fov or FISHEYE_FOV; view = view or FISHEYE_VIEW
    if W >= H:
        hf = view; vf = math.degrees(2 * math.atan(math.tan(math.radians(hf / 2)) * H / W))
    else:
        vf = view; hf = math.degrees(2 * math.atan(math.tan(math.radians(vf / 2)) * W / H))
    # 圓形魚眼（等距）：離中心的距離 ∝ 角度
    yaw = (x - 0.5) * fov; pitch = -(y - 0.5) * fov
    my = max(0.0, fov / 2 - hf / 2 - 5); mp = max(0.0, fov / 2 - vf / 2 - 5)
    yaw = max(-my, min(my, yaw)); pitch = max(-mp, min(mp, pitch))
    return (f"v360=input=fisheye:ih_fov={fov:.0f}:iv_fov={fov:.0f}:output=flat:h_fov={hf:.1f}:v_fov={vf:.1f}"
            f":yaw={yaw:.1f}:pitch={pitch:.1f}:w={W}:h={H}:interp=linear")


def detect_projection(path, info=None):
    """依檔案判斷投影；.insv 一律雙魚眼。取影片 1/3 處一格判斷，結果快取。"""
    if path.lower().endswith(".insv"):
        return "dfisheye"
    try:
        st = os.stat(path); key = (path, st.st_size, int(st.st_mtime))
    except OSError:
        key = (path,)
    if key in _PROJ_CACHE:
        return _PROJ_CACHE[key]
    try:
        info = info or probe(path)
        sq = info.height and abs(info.width / info.height - 1) < 0.03
        if not info.height or (abs(info.width / info.height - 2) > 0.03 and not sq):
            r = ""
        else:
            t = max(0.0, info.duration / 3)
            p = _run([find_ffmpeg(), "-v", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                      "-vf", "scale=64:32,format=gray", "-f", "rawvideo", "-"])
            g = np.frombuffer(p.stdout, np.uint8)
            r = classify_projection(info.width, info.height, g[:2048].reshape(32, 64) if g.size >= 2048 else None)
    except Exception:
        r = ""
    _PROJ_CACHE[key] = r
    return r


def quick_meta(path):
    """R38：配對用的檔頭資訊：長度、比例、fps、creation_time（字串）。"""
    r = _run([find_ffmpeg(), "-hide_banner", "-i", path])
    err = r.stderr.decode("utf-8", "replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", err)
    v = re.search(r"Video:.*?(\d{2,5})x(\d{2,5}).*?([\d.]+) fps", err)
    c = re.search(r"creation_time\s*:\s*(\S+)", err)
    if not (m and v):
        return None
    return {"dur": int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]), "w": int(v[1]), "h": int(v[2]),
            "fps": float(v[3]), "ctime": c[1] if c else None}


def same_recording(a, b):
    """MP4 與 LRV 是否為同一段錄影（檔名被改掉時用）：長度 ±0.06 秒、fps、比例相同；解析度不同，且兩者都有 creation_time、相差 ≤2 秒。"""
    if not a or not b:
        return False
    if abs(a["dur"] - b["dur"]) > 0.06 or abs(a["fps"] - b["fps"]) > 0.01:
        return False
    if abs(a["w"] / a["h"] - b["w"] / b["h"]) > 0.02:
        return False
    if a["w"] == b["w"] or not (a["ctime"] and b["ctime"]):
        return False                       # 代理檔一定比原檔小；沒有拍攝時間就不猜（避免把兩段同長度的影片誤併）
    from datetime import datetime          # 實測：同一段的 LRV 與 MP4 creation_time 差 1 秒，所以容許 ±2 秒
    try:
        ta, tb = (datetime.fromisoformat(x.replace("Z", "+00:00")) for x in (a["ctime"], b["ctime"]))
        return abs((ta - tb).total_seconds()) <= 2
    except ValueError:
        return a["ctime"] == b["ctime"]


def probe(path):
    r = _run([find_ffmpeg(), "-hide_banner", "-i", path])
    err = r.stderr.decode("utf-8", "replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", err)
    if not m:
        raise RuntimeError(f"無法讀取影片：{os.path.basename(path)}")
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    vm = re.search(r"Stream #.*Video:.*?(\d{2,5})x(\d{2,5})", err)
    if not vm:
        raise RuntimeError(f"檔案中沒有影像串流：{os.path.basename(path)}")
    w, h = int(vm[1]), int(vm[2])
    # R25：手機直拍常存成橫向畫素＋旋轉 metadata；ffmpeg 解碼時會自動轉正，所以這裡回報「顯示」尺寸
    rm = re.search(r"rotation of (-?[\d.]+) degrees", err) or re.search(r"rotate\s*:\s*(-?[\d.]+)", err)
    if rm and int(round(abs(float(rm[1])))) % 180 == 90:
        w, h = h, w
    return MediaInfo(path, dur, w, h, "Audio:" in err)


@dataclasses.dataclass
class Segment:
    path: str
    start: float
    end: float
    score: float = 0.0

    @property
    def length(self):
        return max(0.0, self.end - self.start)


# ---------------- 精華偵測 ----------------
@dataclasses.dataclass
class Features:
    """每 step 秒一筆的分析結果（全部離線、只用 numpy）。"""
    times: np.ndarray
    score: np.ndarray
    cuts: list
    motion: np.ndarray
    audio: np.ndarray
    peak: np.ndarray        # 音訊突波（歡呼、笑聲、撞擊）
    sharp: np.ndarray       # 清晰度（0=糊）
    shake: np.ndarray       # 手震（全域位移的抖動）
    expo: np.ndarray        # 曝光懲罰（太暗/太亮）
    color: np.ndarray       # 色彩豐富度
    focus_x: np.ndarray     # 畫面主體的水平位置 0..1（直式重新構圖用）
    thumbs: np.ndarray      # (n, 9, 16, 3) 小圖，用於相似片段去重
    face: np.ndarray = None   # 人臉 0..1（選用 OpenCV；沒有就全 0）
    smile: np.ndarray = None  # 笑臉 0/1


def _same(x, k):
    """R49：np.convolve(x, k, "same") 但輸出長度永遠 = len(x)（短片 n < len(k) 時原本會變長而崩潰）。"""
    x = np.asarray(x, np.float64); k = np.asarray(k, np.float64)
    if len(x) == 0:
        return x
    p = len(k) // 2
    xp = np.pad(x, (p, len(k) - 1 - p), mode="edge")
    return np.convolve(xp, k[::-1], mode="valid")[: len(x)]


def _norm(x):
    x = np.asarray(x, np.float32)
    lo, hi = np.percentile(x, 5) if len(x) > 4 else x.min(), np.percentile(x, 95) if len(x) > 4 else x.max()
    return np.clip((x - lo) / (hi - lo + 1e-6), 0, 1)


def _shift(a, b):
    """相位相關估計兩張灰階小圖的全域位移（像素）。"""
    A = np.fft.fft2(a - a.mean()); B = np.fft.fft2(b - b.mean())
    R = A * np.conj(B); R /= np.abs(R) + 1e-6
    r = np.fft.ifft2(R).real
    y, x = np.unravel_index(np.argmax(r), r.shape)
    h, w = r.shape
    return (x if x <= w // 2 else x - w), (y if y <= h // 2 else y - h)


HWACCEL = os.environ.get("IE_HWACCEL", "auto" if sys.platform in ("darwin", "win32") else "")
DECODE_STATS = {"hw_fail": 0}


def _decode_samples(path, step, small, face=None):
    """R27：一次解碼同時產生 64×36 RGB（評分）與 320×180 灰階（人臉），以前要解碼兩次。
    HWACCEL（macOS/Windows 預設 auto）：硬體解碼失敗時自動退回軟體解碼。回傳 (rgb bytes, gray bytes 或 None)。"""
    ff = find_ffmpeg()
    sw, sh = small
    vf = f"fps={1.0 / step}"
    if face:
        fc = (f"[0:v]{vf},split=2[a][b];[a]scale={sw}:{sh},format=rgb24[o1];"
              f"[b]scale={face[0]}:{face[1]},format=gray[o2]")
        tmp = tempfile.NamedTemporaryFile(suffix=".gray", delete=False); tmp.close()
        outs = ["-filter_complex", fc, "-map", "[o1]", "-f", "rawvideo", "pipe:1",
                "-map", "[o2]", "-f", "rawvideo", "-y", tmp.name]
    else:
        tmp = None
        outs = ["-vf", f"{vf},scale={sw}:{sh},format=rgb24", "-f", "rawvideo", "pipe:1"]
    try:
        for hw in ([HWACCEL, ""] if HWACCEL else [""]):
            pre = ["-hwaccel", hw] if hw else []
            r = _run([ff, "-v", "error", *pre, "-i", path, *outs])
            if r.returncode == 0 or not hw:
                break
            DECODE_STATS["hw_fail"] = DECODE_STATS.get("hw_fail", 0) + 1
        g = None
        if tmp:
            if os.name != "nt" and os.path.getsize(tmp.name):
                g = np.memmap(tmp.name, np.uint8, "r")   # R46：記憶體映射（刪檔後仍可讀），不整支讀進 RAM
            else:
                with open(tmp.name, "rb") as fh_:
                    g = fh_.read()
        return r.stdout, g
    finally:
        if tmp and os.path.exists(tmp.name):
            os.remove(tmp.name)


OCC_T = float(os.environ.get("IE_OCC_T", 0.15))
OCC_W = float(os.environ.get("IE_OCC_W", 1.2))


PEOPLE = os.environ.get("IE_PEOPLE", "1") != "0"
# R50–R54：評分權重（依 Thai 真實挑選資料調，見 review/ROUNDS.md）；IE_W_<key> 可覆寫
W = dict(motion=0.35, audio=0.2, peak=0.15, sharp=0.15, color=0.15, face=0.25, smile=0.2, person=0.15, near=0.3,
         shake=0.35, expo=0.5, occ=OCC_W, hand=0.4, sky=0.3, sky_t=0.15, tilt=0.3, tilt_t=50.0)
for _k in list(W):
    if os.environ.get("IE_W_" + _k):
        W[_k] = float(os.environ["IE_W_" + _k])


def sky_fraction(rgb, mask=None):
    """R53：天空（亮、偏藍或灰白、低紋理）佔畫面（魚眼圓內）比例。rgb：(n, h, w, 3) float32。"""
    n, h, w, _ = rgb.shape
    m = np.ones((h, w), bool) if mask is None else mask
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    Y = 0.299 * R + 0.587 * G + 0.114 * B
    sat = rgb.max(axis=3) - rgb.min(axis=3)
    bs = 4; hh, ww = h // bs * bs, w // bs * bs
    std = Y[:, :hh, :ww].reshape(n, hh // bs, bs, ww // bs, bs).std(axis=(2, 4))
    low = np.zeros((n, h, w), bool); low[:, :hh, :ww] = np.repeat(np.repeat(std < 6, bs, 1), bs, 2)
    skyc = ((B > R + 10) & (Y > 110)) | ((Y > 170) & (sat < 40))
    return ((skyc & low & m).sum((1, 2)) / max(1, m.sum())).astype(np.float32)


def occlusion(rgb, mask=None):
    """R43：每格的「鏡頭前遮擋」比例 0..1 與「下半部是手」比例 0..1。
    遮擋＝（很暗 或 膚色）且低紋理（4×4 區塊標準差 < 9）的像素佔畫面（魚眼時只算圓內）比例：
    近距離的手套/手/機身會失焦又占一大塊，所以紋理很少。rgb：(n, h, w, 3) float32，64×36。"""
    n, h, w, _ = rgb.shape
    m = np.ones((h, w), bool) if mask is None else mask
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    Y = 0.299 * R + 0.587 * G + 0.114 * B
    Cr = (R - Y) * 0.713 + 128; Cb = (B - Y) * 0.564 + 128
    skin = (Cr > 137) & (Cr < 175) & (Cb > 80) & (Cb < 130) & (Y > 50)
    dark = (Y < 45) & (np.abs(Cr - 128) + np.abs(Cb - 128) < 25)   # 純藍/紅這類高彩度色塊不算
    bs = 4; hh, ww = h // bs * bs, w // bs * bs
    std = Y[:, :hh, :ww].reshape(n, hh // bs, bs, ww // bs, bs).std(axis=(2, 4))
    low = np.zeros((n, h, w), bool); low[:, :hh, :ww] = np.repeat(np.repeat(std < 9, bs, 1), bs, 2)
    occ = ((dark | skin) & low & m).sum((1, 2)) / max(1, m.sum())
    lower = m & (np.arange(h)[:, None] > h / 2)
    hand = (skin & lower).sum((1, 2)) / max(1, lower.sum())
    return occ.astype(np.float32), hand.astype(np.float32)


def features(path, step=0.5, info=None, use_faces=True):
    info = info or probe(path)
    ff = find_ffmpeg()
    w, h = 64, 36
    from . import faces as FA
    want_faces = use_faces and FA.has_cv()
    fw, fh = 320, 180
    gray = _decode_samples(path, step, (w, h), (fw, fh) if want_faces else None)
    raw = np.frombuffer(gray[0], np.uint8)
    n = len(raw) // (w * h * 3)
    if n < 2:
        z = np.zeros(1)
        return Features(z, z, [], z, z, z, z + 1, z, z, z, z + 0.5, np.zeros((1, 9, 16, 3), np.float32))
    # R46：分塊處理（每塊 256 格），不再一次把整支影片轉成 float 陣列 → 長片記憶體不隨長度暴增
    raw8 = raw[: n * w * h * 3].reshape(n, h, w, 3)
    fish = bool(info.height and abs(info.width / info.height - 1) < 0.03 and is_circular_fisheye(
        raw8[n // 2].astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)))
    yy, xx = np.mgrid[0:h, 0:w]
    circ = np.hypot((xx + 0.5) / w - 0.5, (yy + 0.5) / h - 0.5) < 0.42
    diff = np.zeros(n); lapv = np.zeros(n); mean = np.zeros(n); satm = np.zeros(n)
    focus_x = np.zeros(n); focus_y = np.zeros(n); occ = np.zeros(n); hand = np.zeros(n); sky = np.zeros(n)
    shl = [(0.0, 0.0)]
    prev = None; CH = 256
    for c0 in range(0, n, CH):
        rgb = raw8[c0:c0 + CH].astype(np.float32)
        g = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
        gp = np.concatenate([prev[None], g]) if prev is not None else np.concatenate([g[:1], g])
        dmap = np.abs(gp[1:] - gp[:-1])
        if prev is None:
            dmap[0] = 0
        diff[c0:c0 + len(g)] = dmap.mean(axis=(1, 2))
        for i in range(1, len(gp)):
            if c0 + i - 1 > 0:
                shl.append(_shift(gp[i], gp[i - 1]))
        lap = (g[:, 1:-1, 1:-1] * 4 - g[:, :-2, 1:-1] - g[:, 2:, 1:-1] - g[:, 1:-1, :-2] - g[:, 1:-1, 2:])
        lapv[c0:c0 + len(g)] = lap.var(axis=(1, 2))
        mean[c0:c0 + len(g)] = g.mean(axis=(1, 2))
        satm[c0:c0 + len(g)] = (rgb.max(axis=3) - rgb.min(axis=3)).mean(axis=(1, 2))
        edge = np.abs(np.diff(g, axis=2, prepend=g[:, :, :1]))
        e2 = dmap * 2 + edge
        if fish:
            e2 = e2 * circ[None]
        energy = e2.sum(axis=1) + 1e-3
        focus_x[c0:c0 + len(g)] = (energy * (np.arange(w) + 0.5) / w).sum(1) / energy.sum(1)
        ev = e2.sum(axis=2) + 1e-3
        focus_y[c0:c0 + len(g)] = (ev * (np.arange(h) + 0.5) / h).sum(1) / ev.sum(1)
        o_, h_ = occlusion(rgb, circ if fish else None)
        occ[c0:c0 + len(g)] = o_; hand[c0:c0 + len(g)] = h_
        sky[c0:c0 + len(g)] = sky_fraction(rgb, circ if fish else None)
        prev = g[-1]
        del rgb, g, gp, dmap, lap, edge, e2
    med = np.median(diff[1:]) + 1e-6
    cuts = [i * step for i in range(1, n) if diff[i] > max(25, med * 4)]
    sharp = _norm(np.log1p(lapv))
    sh = np.array(shl[:n], np.float32)
    k = np.ones(5) / 5
    smooth = np.stack([_same(sh[:, j], k) for j in range(2)], 1)
    shake = np.clip(np.linalg.norm(sh - smooth, axis=1) / 4.0, 0, 1)
    shake[[i for i in range(n) if i * step in cuts]] = 0          # 剪接點不算手震
    expo = np.clip((40 - mean) / 40, 0, 1) + np.clip((mean - 225) / 30, 0, 1)
    color = _norm(satm)
    audio = np.zeros(n); peak = np.zeros(n)
    if info.has_audio:
        sr = 8000
        r = _run([ff, "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"])
        a = np.frombuffer(r.stdout, np.int16).astype(np.float32)
        sub = int(sr * 0.1); m = len(a) // sub
        if m:
            rms = np.sqrt((a[: m * sub].reshape(m, sub) ** 2).mean(1) + 1e-6)
            db = 20 * np.log10(rms + 1)
            on = np.clip(db - _same(db, np.ones(20) / 20), 0, None)   # 突然變大聲
            per = int(round(step / 0.1))
            for i in range(min(n, m // per)):
                audio[i] = rms[i * per:(i + 1) * per].mean(); peak[i] = on[i * per:(i + 1) * per].max()
    face = np.zeros(n, np.float32); smile = np.zeros(n, np.float32)
    from . import faces as FA
    if want_faces and not fish:          # R52：魚眼改在攤平畫面找人（見下）
        gr = np.frombuffer(gray[1], np.uint8)
        m = min(n, len(gr) // (fw * fh))
        if m:
            f_, s_, x_ = FA.detect(gr[: m * fw * fh].reshape(m, fh, fw))
            face[:m], smile[:m] = f_, s_
            ok = ~np.isnan(x_)
            focus_x[:m][ok] = x_[ok]            # 有臉時直式構圖跟著臉走
    motion = _norm(np.clip(diff, 0, np.percentile(diff, 95) + 1e-6))
    audio = _norm(audio) if audio.any() else audio
    peak = _norm(peak) if peak.any() else peak
    person = np.zeros(n, np.float32); near = np.zeros(n, np.float32)
    times = np.arange(n) * step
    if fish:
        # R52：魚眼不在原始圓上找臉（邊緣嚴重變形、Haar 幾乎都是誤判/漏判）→ 攤平後用 NanoDet 找人
        face[:] = 0; smile[:] = 0
        from . import fisheye as FE
        ps = FE.people_series(path, info.duration) if use_faces and PEOPLE else None
        if ps is not None and len(ps[0]):
            j = np.clip(np.searchsorted(ps[0], times + 1e-6) - 1, 0, len(ps[0]) - 1)
            person = ps[1][j]; near = ps[2][j]
    tilt = np.zeros(n, np.float32); roll = np.zeros(n, np.float32)
    try:
        from . import fisheye as FE
        ts_ = FE.tilt_series(path, times + step / 2)
        if ts_ is not None:
            tilt, roll = ts_
    except Exception:
        pass
    th = raw8.reshape(n, 9, 4, 16, 4, 3).mean(axis=(2, 4), dtype=np.float32) / 255.0
    F = Features(times, np.zeros(n), cuts, motion, audio, peak, sharp, shake, expo, color,
                 focus_x, th.astype(np.float32), face, smile)
    F.focus_y = focus_y; F.occ = occ; F.hand = hand; F.sky = sky
    F.person = person; F.near = near; F.tilt = tilt; F.roll = roll; F.fish = fish
    F.duration = info.duration; F.step = step
    F.score = score_features(F)
    return F


def _cut_bonus(F):
    b = np.zeros(len(F.times))
    for c in F.cuts:  # 場景切換附近小加分
        i = int(round(c / F.step)); b[i:i + 4] += 0.1
    return b


def penalties(F):
    """R53：(遮擋, 手, 只拍到天空/無紋理, 鏡頭大幅朝天或朝地) 每個取樣點 0..1。"""
    g = lambda k: np.asarray(getattr(F, k, None) if getattr(F, k, None) is not None else np.zeros(len(F.times)), np.float64)
    return (np.clip((g("occ") - OCC_T) / 0.2, 0, 1), np.clip((g("hand") - 0.3) / 0.25, 0, 1),
            np.clip((g("sky") - W["sky_t"]) / 0.25, 0, 1), np.clip((np.abs(g("tilt")) - W["tilt_t"]) / 25, 0, 1))


def score_features(F):
    """R50：每個取樣點的精彩分數（從 Features 各分量算；權重見 W，可用 IE_W_<名稱> 覆寫）。"""
    g = lambda k: np.asarray(getattr(F, k, None) if getattr(F, k, None) is not None else np.zeros(len(F.times)), np.float64)
    occ_pen, hand_pen, sky_pen, tilt_pen = penalties(F)
    score = (W["motion"] * g("motion") + W["audio"] * g("audio") + W["peak"] * g("peak") + W["sharp"] * g("sharp")
             + W["color"] * g("color") + W["face"] * g("face") + W["smile"] * g("smile")
             + W["person"] * g("person") + W["near"] * g("near")
             - W["shake"] * g("shake") - W["expo"] * g("expo") - W["occ"] * occ_pen - W["hand"] * hand_pen
             - W["sky"] * sky_pen - W["tilt"] * tilt_pen)
    score = score + _cut_bonus(F)
    return _same(score, np.ones(3) / 3)



def analyze(path, step=0.5, info=None):
    """回傳 (times, score, cuts)：相容舊介面，內部用 features()。"""
    f = features(path, step, info)
    return f.times, f.score, f.cuts


def similar(sig_a, sig_b):
    """兩段的相似度 0..1（小圖平均絕對差）；> 0.93 視為近乎重複。"""
    a = np.asarray(sig_a, np.float32).ravel(); b = np.asarray(sig_b, np.float32).ravel()
    if a.size != b.size or not a.size:
        return 0.0
    return float(1 - np.abs(a - b).mean() * 4)


def suggest_segments(paths, target_total=30.0, seg_len=4.0, progress=None):
    """在所有影片中挑出精華片段，總長約 target_total 秒。"""
    cands = []
    for vi, p in enumerate(paths):
        if progress:
            progress(vi, len(paths), p)
        try:
            info = probe(p)
            times, score, cuts = analyze(p, info=info)
        except Exception:
            continue
        dur = info.duration
        L = min(seg_len, dur)
        win = max(1, int(L / 0.5))
        if len(score) >= win:
            csum = np.convolve(score, np.ones(win), mode="valid") / win
        else:
            csum = np.array([score.mean()])
        used = []
        order = np.argsort(-csum)
        for idx in order[: 200]:
            s = float(times[idx]) if idx < len(times) else 0.0
            # 起點對齊附近的場景切換
            for c in cuts:
                if 0 <= c - s < 1.0:
                    s = c
                    break
            s = max(0.0, min(s, dur - L))
            e = s + L
            if any(not (e <= a or s >= b) for a, b in used):
                continue
            used.append((s, e))
            cands.append(Segment(p, round(s, 2), round(e, 2), float(csum[idx])))
            if len(used) >= 20:
                break
    # 每支影片至少一段最佳，再依分數補滿
    chosen, total = [], 0.0
    best = {}
    for c in cands:
        if c.path not in best or c.score > best[c.path].score:
            best[c.path] = c
    for c in sorted(best.values(), key=lambda c: -c.score):
        if total >= target_total:
            break
        chosen.append(c); total += c.length
    for c in sorted(cands, key=lambda c: -c.score):
        if total >= target_total:
            break
        if c not in chosen:
            chosen.append(c); total += c.length
    # 依影片順序與時間排序
    chosen.sort(key=lambda c: (paths.index(c.path), c.start))
    if progress:
        progress(len(paths), len(paths), "")
    return chosen


# ---------------- 輸出 ----------------
@dataclasses.dataclass
class ExportOptions:
    aspect: str = "16:9"        # 16:9 / 9:16 / 1:1
    resolution: str = "1080p"   # 1080p / 4K
    fps: int = 30
    crossfade: float = 0.5      # 0 = 無轉場
    music: str = ""
    music_volume: float = 0.6
    keep_original_audio: bool = True
    original_volume: float = 1.0
    fade_out: float = 1.5
    hw_encode: bool = False     # True: macOS h264_videotoolbox / Windows h264_mf（失敗自動退回 libx264）
    reframe: str = "smart"      # smart：跟著主體裁切（直式/方形時）；center：置中裁切
    projection: str = ""        # 360 素材：equirect / dfisheye；空字串 = 一般影片
    h_fov: float = 100.0        # 360 轉一般畫面的水平視角
    title: str = ""             # 片頭標題（空 = 不加）
    subtitle: str = ""          # 片頭副標（例如日期）
    music_start: float = 0.0    # 音樂從第幾秒開始（對齊第一個拍點）
    title_png: str = ""         # ffmpeg 沒有 drawtext 時，改疊這張預先畫好的透明 PNG
    look: str = ""              # 濾鏡：見 LOOKS
    auto_enhance: bool = False  # 每段自動調亮度/對比/飽和度
    loudnorm: bool = False      # 社群平台常見建議約 -14 LUFS（分享預設會開）
    title_style: str = "經典"   # 文字效果：見 TITLE_STYLES（非「經典」一律用 Qt 畫 PNG）
    title_anim: str = "淡入"    # 淡入 / 上滑 / 放大
    stickers: list = dataclasses.field(default_factory=list)   # [(png, 位置)]，位置見 STICKER_POS；全片顯示、0.4 秒淡入
    effect: str = ""            # R23 特效模板：見 EFFECTS（空 = 無）
    effect_times: list = dataclasses.field(default_factory=list)  # 特效觸發時間（輸出時間軸秒數）；空 = 用剪接點
    vcodec: str = ""            # R66：最終編碼 ""/h264、hevc、prores（片段匯出用）
    audio: bool = True          # R66：False＝輸出不含音軌（-an）


EFFECTS = ["", "節拍放大", "閃白", "故障"]
EFFECT_MAX = 80   # 運算式長度上限：最多 80 個觸發點


def effect_filter(name, times, W, H):
    """R23：在觸發時間點做短暫效果。回傳 filter 字串（空 = 不加）。
    節拍放大：0.25 秒內 1.08→1.0 倍放大；閃白：0.15 秒亮度 +0.45 衰減；故障：0.1 秒 RGB 錯位＋雜訊。"""
    ts = sorted(round(float(t), 3) for t in times if t >= 0)[:EFFECT_MAX]
    if not name or not ts:
        return ""
    def pulse(d):
        return "+".join(f"max(0,1-abs(t-{t:.3f})/{d})*gte(t,{t:.3f})" for t in ts)
    if name == "節拍放大":
        z = f"(1+0.08*min(1,{pulse(0.25)}))"
        return (f"scale=w='2*trunc({W}*{z}/2)':h='2*trunc({H}*{z}/2)':eval=frame,"
                f"crop={W}:{H}:(iw-{W})/2:(ih-{H})/2,setsar=1")
    if name == "閃白":
        return f"eq=brightness='0.45*min(1,{pulse(0.15)})':eval=frame"
    if name == "故障":
        en = "+".join(f"between(t,{t:.3f},{t + 0.1:.3f})" for t in ts)
        sh = max(2, W // 160)
        return (f"rgbashift=rh={sh}:bh=-{sh}:gv={sh // 2}:enable='{en}',"
                f"noise=alls=25:allf=t:enable='{en}'")
    raise ValueError(f"未知特效：{name}")


def effect_preview(name, out, img=None, W=192, H=108):
    """R29：特效預覽條。用一張畫面（沒有就用測試圖）在 t=0.1 觸發一次，取觸發前、觸發瞬間、0.05 秒後、0.15 秒後 4 格並排成一張 PNG。
    回傳 out；name 為空時回傳 None。"""
    if not name:
        return None
    vf = effect_filter(name, [0.1], W, H)
    src = (["-loop", "1", "-t", "0.4", "-r", "20", "-i", img] if img and os.path.exists(img)
           else ["-f", "lavfi", "-i", f"testsrc2=d=0.4:s={W}x{H}:r=20"])
    chain = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps=20,{vf},"
             "select='" + "+".join(f"lt(abs(t-{x:.2f})\\,0.01)" for x in (0.05, 0.1, 0.15, 0.25)) + "',tile=4x1:padding=2:color=0x101418")
    r = _run([find_ffmpeg(), "-y", "-v", "error", *src, "-filter_complex", chain, "-frames:v", "1", "-fps_mode", "passthrough", out])
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError(f"特效預覽失敗：{(r.stderr or '')[-300:]}")
    return out


STICKER_ANIMS = ["無", "彈跳", "浮動"]


def sticker_xy(pos, anim="無"):
    """R24：貼圖 overlay 的 x/y 運算式。pos 可以是 STICKER_POS 的名稱，或拖曳得到的 (fx, fy)＝貼圖中心佔畫面比例。
    彈跳：前 0.8 秒由上方落下並回彈；浮動：上下 ±1.5% 緩慢擺動。"""
    if isinstance(pos, (tuple, list)):
        fx = min(1.0, max(0.0, float(pos[0]))); fy = min(1.0, max(0.0, float(pos[1])))
        x = f"clip(W*{fx:.4f}-w/2,0,W-w)"; y = f"clip(H*{fy:.4f}-h/2,0,H-h)"
    else:
        x, y = STICKER_POS.get(pos, STICKER_POS["右上"])
    if anim == "彈跳":
        y = f"({y})-H*0.25*exp(-5*t)*abs(cos(9*t))"
    elif anim == "浮動":
        y = f"({y})+H*0.015*sin(2*PI*t/2.5)"
    return x, y


TITLE_STYLES = ["經典", "霓虹", "標籤", "電影"]
TITLE_ANIMS = ["淡入", "上滑", "放大"]
STICKER_MAX = 5   # R28：一次最多幾張貼圖
STICKER_POS = {"右上": ("W-w-W*0.04", "H*0.04"), "左上": ("W*0.04", "H*0.04"),
               "右下": ("W-w-W*0.04", "H-h-H*0.10"), "左下": ("W*0.04", "H-h-H*0.10")}


def title_overlay(ti, td, W, H, anim):
    """片頭 PNG 疊加的 filter（回傳 [tp] 標籤前的鏈與 overlay 參數）。"""
    fade = f"fade=t=in:st=0:d=0.5:alpha=1,fade=t=out:st={max(0, td - 0.5):.3f}:d=0.5:alpha=1"
    if anim == "放大":
        # 先放大 1.15 倍再用 zoompan 式縮放太慢；改為 scale 隨時間（eval=frame）0.85→1.0
        pre = (f"[{ti}:v]format=rgba,scale=w='{W}*(0.85+0.15*min(1,t/0.6))':h=-1:eval=frame,{fade}[tp]")
        return pre, "overlay=x=(W-w)/2:y=(H-h)/2:eval=frame:eof_action=pass"
    pre = f"[{ti}:v]scale={W}:{H},format=rgba,{fade}[tp]"
    if anim == "上滑":
        return pre, f"overlay=x=0:y='{H}*0.06*max(0,1-t/0.6)':eval=frame:eof_action=pass"
    return pre, "overlay=0:0:eof_action=pass"


# 分享預設：只設定比例／解析度／fps／建議長度／音量標準化。平台的實際長度上限會變動，這裡只當「建議」，未逐一查證。
SHARE_PRESETS = {
    "IG Reels": dict(aspect="9:16", resolution="1080p", fps=30, target=30, suffix="Reels"),
    "YouTube Shorts": dict(aspect="9:16", resolution="1080p", fps=30, target=60, suffix="Shorts"),
    "TikTok": dict(aspect="9:16", resolution="1080p", fps=30, target=30, suffix="TikTok"),
    "YouTube（橫式）": dict(aspect="16:9", resolution="1080p", fps=30, target=60, suffix="YouTube"),
}


LOOKS = {
    "": "",
    "鮮豔": "eq=saturation=1.35:contrast=1.06,vibrance=intensity=0.15",
    "電影": "curves=preset=medium_contrast,colorbalance=rs=-0.04:bs=0.05:rh=0.06:bh=-0.04,eq=saturation=0.88",
    "暖色": "colortemperature=temperature=5200,eq=saturation=1.08",
    "冷色": "colortemperature=temperature=8500",
    "復古": "curves=preset=vintage,eq=saturation=0.85",
    "黑白": "hue=s=0,eq=contrast=1.12",
}


_FRIENDLY = [
    (("No space left", "ENOSPC", "磁碟空間"), "磁碟空間不足。請清出空間，或改存到其他磁碟。"),
    (("PermissionError", "Permission denied", "Errno 13"), "沒有權限寫入或讀取這個位置。請換一個資料夾，或檢查檔案是否被其他程式開啟。"),
    (("FileNotFoundError", "No such file", "Errno 2"), "找不到檔案。影片可能被移動、改名，或外接硬碟已拔除。"),
    (("Invalid data found", "moov atom not found", "could not find codec"), "這支影片無法讀取，可能已損毀或格式不支援。"),
    (("ffmpeg", "Conversion failed", "Error while"), "影片處理失敗。可以重試，或把這段從時間軸移除再輸出。"),
]


def friendly_error(msg):
    """把原始例外字串轉成一般人看得懂的說明；原文留給「詳細資料」。（REVIEW_r10 B7）"""
    for keys, text in _FRIENDLY:
        if any(k.lower() in (msg or "").lower() for k in keys):
            return text
    return "發生未預期的錯誤。可以重試；如果一直發生，請把「詳細資料」內容回報給開發者。"


def parse_cube(path):
    """檢查 .cube 3D LUT：回傳格點數 N；格式不對就丟 ValueError（中文訊息）。"""
    n, rows = 0, 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            t = ln.strip()
            if not t or t.startswith("#"):
                continue
            k = t.split()[0].upper()
            if k == "LUT_3D_SIZE":
                n = int(t.split()[1])
            elif k == "LUT_1D_SIZE":
                raise ValueError("只支援 3D LUT（LUT_3D_SIZE）")
            elif k[0].isdigit() or k[0] in "-.":
                if len(t.split()) != 3:
                    raise ValueError("資料列不是 3 個數字")
                rows += 1
    if not (2 <= n <= 256) or rows != n ** 3:
        raise ValueError(f"LUT 大小不符（宣告 {n}，資料 {rows} 列）")
    return n


def _ff_path(p):
    """給 filtergraph 用的路徑：反斜線轉正斜線、冒號與單引號跳脫（Windows 的 C: 也能用）。"""
    p = os.path.abspath(p).replace("\\", "/")
    return "'" + p.replace("'", "'\\''").replace(":", "\\:") + "'"


def look_filter(name):
    """回傳濾鏡字串；ffmpeg 少了某個 filter 時就略過那一段，不讓輸出失敗。
    name 可以是 LOOKS 的名稱，或 "lut:<.cube 路徑>"。"""
    if name and name.startswith("lut:"):
        p = name[4:]
        return f"lut3d=file={_ff_path(p)}" if os.path.exists(p) and has_filter("lut3d") else ""
    parts = [p for p in LOOKS.get(name or "", "").split(",") if p]
    return ",".join(p for p in parts if has_filter(p.split("=", 1)[0]))


def preview_look(path, t, look="", auto=False, out_png=None, w=320):
    """濾鏡即時預覽：取 t 秒那一格，套上自動調色＋濾鏡，輸出小 PNG。回傳 PNG 路徑或 None。"""
    vf = ",".join(f for f in (f"scale={w}:-2", auto_enhance_filter(path, max(0, t - 0.5), t + 0.5) if auto else "",
                              look_filter(look)) if f)
    out_png = out_png or os.path.join(tempfile.gettempdir(), f"look_{os.getpid()}.png")
    r = _run([find_ffmpeg(), "-y", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", path, "-frames:v", "1",
              "-vf", vf, out_png])
    return out_png if r.returncode == 0 and os.path.exists(out_png) else None


def auto_enhance_filter(path, a, b):
    """R18：同一段（檔案＋時間＋mtime）只量一次；長片一次約 0.45 秒、與位置無關（量測見 ROUNDS R18）。"""
    try:
        st = os.stat(path); key = (st.st_mtime, st.st_size)
    except OSError:
        key = None
    return _auto_enhance_cached(path, round(a, 2), round(b, 2), key)


@functools.lru_cache(512)
def _auto_enhance_cached(path, a, b, _key):
    """取片段中 3 張小圖量亮度/對比/飽和度，回傳溫和的 eq 修正（偏暗、灰濛時才會明顯）。"""
    vals = []
    for t in (a + (b - a) * f for f in (0.2, 0.5, 0.8)):
        r = _run([find_ffmpeg(), "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                  "-vf", "scale=64:36", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
        if r.returncode == 0 and len(r.stdout) == 64 * 36 * 3:
            vals.append(np.frombuffer(r.stdout, np.uint8).reshape(-1, 3).astype(np.float32) / 255)
    if not vals:
        return ""
    px = np.concatenate(vals)
    y = px @ np.array([0.299, 0.587, 0.114], np.float32)
    mean, std = float(y.mean()), float(y.std())
    sat = float((px.max(1) - px.min(1)).mean())
    ct = float(np.clip(0.2 / max(std, 1e-3), 1.0, 1.35))
    after = (mean - 0.5) * ct + 0.5                 # eq 以 0.5 為中心拉對比，先算拉完的平均亮度
    br = float(np.clip((0.46 - after) * 0.6, -0.08, 0.2))
    sa = float(np.clip(0.25 / max(sat, 1e-3), 1.0, 1.3))
    if abs(br) < 0.01 and ct < 1.02 and sa < 1.02:
        return ""
    return f"eq=brightness={br:.3f}:contrast={ct:.3f}:saturation={sa:.3f}"


import functools


@functools.lru_cache(None)
def hw_encoder():
    """回傳可用的硬體 H.264 編碼器名稱或 None。"""
    want = "h264_videotoolbox" if sys.platform == "darwin" else ("h264_mf" if os.name == "nt" else None)
    if not want:
        return None
    r = _run([find_ffmpeg(), "-hide_banner", "-f", "lavfi", "-i", "color=s=256x144:d=0.2",
              "-c:v", want, "-f", "null", "-"])
    return want if r.returncode == 0 else None


def _venc(opts, final):
    vc = getattr(opts, "vcodec", "") if final else ""
    if vc == "hevc":
        return ["-c:v", "libx265", "-preset", "fast", "-crf", "22", "-tag:v", "hvc1", "-x265-params", "log-level=error"]
    if vc == "prores":
        return ["-c:v", "prores_ks", "-profile:v", "2", "-vendor", "apl0"]
    enc = hw_encoder() if opts.hw_encode else None
    if enc == "h264_videotoolbox":
        return ["-c:v", enc, "-b:v", "40M" if opts.resolution == "4K" else "12M", "-allow_sw", "1"]
    if enc == "h264_mf":
        return ["-c:v", enc, "-b:v", "40M" if opts.resolution == "4K" else "12M"]
    return ["-c:v", "libx264", "-preset", "medium" if final else "veryfast", "-crf", "20" if final else "18"]


def out_size(aspect, res):
    base = {"4K": 2160, "720p": 720}.get(res, 1080)
    long = base * 16 // 9
    return {"16:9": (long, base), "9:16": (base, long), "1:1": (base, base)}[aspect]


class Cancelled(Exception):
    pass


def _run_progress(args, duration, cb, cancel):
    p = subprocess.Popen(args + ["-progress", "pipe:1", "-nostats"], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, creationflags=_NOWIN, text=True,
                         encoding="utf-8", errors="replace")
    import threading
    errbuf = []
    t = threading.Thread(target=lambda: errbuf.extend(p.stderr), daemon=True)
    t.start()
    for line in p.stdout:
        if cancel and cancel():
            p.kill(); p.wait()
            raise Cancelled()
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                us = int(line.split("=")[1])
                if cb and duration > 0:
                    cb(min(1.0, us / 1e6 / duration))
            except ValueError:
                pass
    p.wait(); t.join(1)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg 失敗：\n" + "".join(errbuf[-15:]))


def export(segments, out_path, opts=None, progress=None, cancel=None):
    """先輸出到 <out>.part.mp4，成功才 os.replace 成正式檔；取消或失敗只刪暫存檔，原有同名檔不受影響。"""
    part = out_path + ".part" + (os.path.splitext(out_path)[1] or ".mp4")
    try:
        _export(segments, part, opts, progress, cancel)
        os.replace(part, out_path)
        return out_path
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass


def _export(segments, out_path, opts=None, progress=None, cancel=None):
    """progress(fraction 0..1, message)。"""
    opts = opts or ExportOptions()
    segs = [s for s in segments if s.length > 0.1]
    if not segs:
        raise ValueError("沒有可輸出的片段")
    ff = find_ffmpeg()
    W, H = out_size(opts.aspect, opts.resolution)
    tmp = tempfile.mkdtemp(prefix="hlexp_")
    n = len(segs)
    weight_seg = 0.7
    say = progress or (lambda f, m: None)
    try:
        parts, jobs, concats = [], [], []
        from . import smart
        for i, s in enumerate(segs):
            info = probe(s.path)
            out = os.path.join(tmp, f"p{i:04d}.mp4")
            ramp = getattr(s, "ramp", None)
            curve = getattr(s, "curve", None)
            subs = smart.curve_pieces(s.start, s.end, curve) if curve else smart.ramp_pieces(s.start, s.end, ramp)
            track = smart.load_track(getattr(s, "track", None))
            use_orig = opts.keep_original_audio and info.has_audio
            files, plen = [], 0.0
            for k, (a, b, sp) in enumerate(subs):
                L = b - a
                if L <= 0.05:
                    continue
                proj = opts.projection
                if proj == "auto":
                    proj = detect_projection(s.path, info)
                if proj == "fisheye":
                    tx = float(np.median(track["x"])) if (track and opts.reframe == "smart") else 0.5
                    ty = float(np.median(track["y"])) if (track and opts.reframe == "smart" and track.get("y")) else 0.5
                    geo = fisheye_view(W, H, tx, ty)
                    if os.environ.get("IE_FISHEYE_FOLLOW", "1") != "0":   # R39–R41：逐格跟拍＋水平＋構圖
                        from . import fisheye as FE
                        fy = float(geo.split("yaw=")[1].split(":")[0]); fp = float(geo.split("pitch=")[1].split(":")[0])
                        cam, cinfo = FE.camera_path(getattr(s, "analysis_path", None) or s.path, a, L, W, H, FISHEYE_FOV,
                                                    FISHEYE_VIEW, follow=opts.reframe == "smart",
                                                    manual_roll=getattr(s, "roll", None), fallback=(fy, fp))
                        cmdf = os.path.join(tmp, f"cam{i:04d}_{k}.txt")
                        with open(cmdf, "w") as fh:
                            fh.write(FE.sendcmd_text(cam))
                        s.cam_info = cinfo
                        t0, y0, p0, r0 = cam[0]
                        # R45：來源解析度有限（LRV 640²，畫面只用到約 1/2 的圓）→ v360 在較小尺寸算，再 lanczos 放大
                        sc = min(1.0, max(0.5, max(info.width, info.height) * FISHEYE_VIEW / FISHEYE_FOV * 1.5 / max(W, H)))
                        rw, rh = (W, H) if sc >= 0.99 else (int(W * sc) // 2 * 2, int(H * sc) // 2 * 2)
                        geo = (f"sendcmd=f={cmdf},"
                               + re.sub(r":yaw=[-\d.]+:pitch=[-\d.]+", f":yaw={y0:.2f}:pitch={p0:.2f}:roll={r0:.2f}:rorder=rpy",
                                        fisheye_view(rw, rh, fov=FISHEYE_FOV)).replace("v360=", "v360@cam=", 1)
                               + ("" if (rw, rh) == (W, H) else f",scale={W}:{H}:flags=lanczos"))
                elif proj:
                    yaw = (float(np.median(track["x"])) - 0.5) * 360 if (track and opts.reframe == "smart") else 0
                    import math
                    vfov = math.degrees(2 * math.atan(math.tan(math.radians(opts.h_fov / 2)) * H / W))
                    fish = ":ih_fov=200:iv_fov=200" if proj == "dfisheye" else ""   # 鏡頭參數依機型，未逐一驗證
                    geo = (f"v360=input={'e' if proj == 'equirect' else 'dfisheye'}{fish}:output=flat:"
                           f"h_fov={opts.h_fov:.1f}:v_fov={vfov:.1f}:yaw={yaw:.1f}:w={W}:h={H}")
                else:
                    x = smart.crop_x_expr(track, a, L) if opts.reframe == "smart" and track else "(iw-ow)/2"
                    geo = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:{x}:(ih-oh)/2"
                col = [f for f in (auto_enhance_filter(s.path, s.start, s.end) if opts.auto_enhance else "",   # 整段同一組（慢動作分段不跳色）
                                   look_filter(opts.look)) if f]
                # 裁切軌跡的 t 是原始時間，所以 setpts 要放在裁切之後（R17 修正：慢動作段跟拍不再變慢一半）
                vf = (geo + "".join("," + f for f in col) + (f",setpts=PTS/{sp}" if sp != 1.0 else "") +
                      f",setsar=1,fps={opts.fps},format=yuv420p")
                olen = L / sp
                sub = os.path.join(tmp, f"p{i:04d}_{k}.mp4") if len(subs) > 1 else out
                args = [ff, "-y", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{L:.3f}", "-i", s.path]
                if not use_orig:
                    args += ["-f", "lavfi", "-t", f"{olen:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
                args += ["-map", "0:v:0", "-map", "0:a:0" if use_orig else "1:a:0", "-vf", vf]
                if use_orig:
                    tempo = (smart.atempo_chain(sp) + ",") if sp != 1.0 else ""
                    args += ["-af", f"{tempo}volume={opts.original_volume},aresample=48000,"
                                    "aformat=channel_layouts=stereo,apad"]
                args += ["-t", f"{olen:.3f}"]
                args += _venc(opts, False) + ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", sub]
                jobs.append((i, args, olen))
                files.append(sub); plen += olen
            if len(files) > 1:
                lst = os.path.join(tmp, f"p{i:04d}.txt")
                with open(lst, "w", encoding="utf-8") as fh:
                    fh.writelines(f"file '{f}'\n" for f in files)
                concats.append(([ff, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out], plen))
            parts.append((out, plen))
        # R45：片段平行輸出（IE_JOBS，預設 min(3, CPU/2)）；進度以完成秒數加總
        nj = max(1, int(os.environ.get("IE_JOBS", "0")) or min(3, max(1, (os.cpu_count() or 2) // 2)))
        tot = sum(j[2] for j in jobs) or 1.0
        done = {}
        import threading
        lock = threading.Lock()

        def _job(j):
            i, args, olen = j

            def cb(f):
                with lock:
                    done[id(j)] = f * olen
                    say(weight_seg * sum(done.values()) / tot, f"處理片段（{nj} 路平行）")
            _run_progress(args, olen, cb, cancel)
            cb(1.0)
        say(0.0, "處理片段")
        if nj == 1:
            for j in jobs:
                _job(j)
        else:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(nj) as ex:
                futs = [ex.submit(_job, j) for j in jobs]
                for f in futs:
                    f.result()
        for args, plen in concats:
            _run_progress(args, plen, None, cancel)

        # 合併
        xf = opts.crossfade if n > 1 else 0.0
        xf = min(xf, min(l for _, l in parts) / 2 - 0.05) if xf > 0 else 0.0
        xf = max(0.0, xf)
        total = sum(l for _, l in parts) - xf * (n - 1)
        args = [ff, "-y", "-v", "error"]
        for p, _ in parts:
            args += ["-i", p]
        fc = []
        if xf > 0:
            vlast, alast, off = "[0:v]", "[0:a]", 0.0
            for i in range(1, n):
                off += parts[i - 1][1] - xf
                fc.append(f"{vlast}[{i}:v]xfade=transition=fade:duration={xf:.3f}:offset={off:.3f}[v{i}]")
                fc.append(f"{alast}[{i}:a]acrossfade=d={xf:.3f}[a{i}]")
                vlast, alast = f"[v{i}]", f"[a{i}]"
        else:
            ins = "".join(f"[{i}:v][{i}:a]" for i in range(n))
            fc.append(f"{ins}concat=n={n}:v=1:a=1[vc][ac]")
            vlast, alast = "[vc]", "[ac]"
        if opts.music and os.path.exists(opts.music):
            mi = n
            args += ["-stream_loop", "-1", "-ss", f"{max(0.0, opts.music_start):.3f}", "-i", opts.music]
            fc.append(f"[{mi}:a]aresample=48000,aformat=channel_layouts=stereo,"
                      f"volume={opts.music_volume},atrim=0:{total:.3f}[mus]")
            if opts.keep_original_audio:
                fc.append(f"{alast}[mus]amix=inputs=2:duration=first:normalize=0[amx]")
            else:
                fc.append(f"{alast}volume=0[sil];[sil][mus]amix=inputs=2:duration=first:normalize=0[amx]")
            alast = "[amx]"
        if opts.effect:
            et = list(opts.effect_times)
            if not et:   # 沒有拍點：用剪接點（轉場中間）
                acc = 0.0
                for k in range(n - 1):
                    acc += parts[k][1] - xf; et.append(acc + xf / 2)
            ef = effect_filter(opts.effect, [t for t in et if t < total], W, H)
            if ef:
                fc.append(f"{vlast}{ef}[vfx]"); vlast = "[vfx]"
        td = min(3.0, total / 2)
        use_dt = opts.title and has_filter("drawtext") and opts.title_style == "經典" and opts.title_anim == "淡入"
        tf = smart.title_filter(opts.title, opts.subtitle, td, H) if use_dt else None
        extra_in = n + (1 if opts.music and os.path.exists(opts.music) else 0)
        if tf:
            fc.append(f"{vlast}{tf}[vt]"); vlast = "[vt]"
        elif opts.title and opts.title_png and os.path.exists(opts.title_png):
            ti = extra_in; extra_in += 1
            args += ["-loop", "1", "-framerate", str(opts.fps), "-t", f"{td:.3f}", "-i", opts.title_png]
            pre, ov = title_overlay(ti, td, W, H, opts.title_anim)
            fc.append(pre); fc.append(f"{vlast}[tp]{ov}[vt]"); vlast = "[vt]"
        for k, (png, pos, *rest) in enumerate(st for st in opts.stickers if os.path.exists(st[0])):
            si = extra_in; extra_in += 1
            args += ["-loop", "1", "-framerate", str(opts.fps), "-t", f"{total:.3f}", "-i", png]
            x, y = sticker_xy(pos, rest[0] if rest else "無")
            sz = int(min(W, H) * 0.16)
            fc.append(f"[{si}:v]format=rgba,scale={sz}:{sz}:force_original_aspect_ratio=decrease,"
                      f"fade=t=in:st=0:d=0.4:alpha=1[sk{k}]")
            fc.append(f"{vlast}[sk{k}]overlay=x='{x}':y='{y}':eval=frame:eof_action=pass[vs{k}]"); vlast = f"[vs{k}]"
        if opts.loudnorm and has_filter("loudnorm"):
            fc.append(f"{alast}loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aln]"); alast = "[aln]"
        fo = min(opts.fade_out, total / 2) if opts.fade_out > 0 else 0
        if fo > 0:
            st = max(0.0, total - fo)
            fc.append(f"{vlast}fade=t=out:st={st:.3f}:d={fo:.3f}[vf]")
            fc.append(f"{alast}afade=t=out:st={st:.3f}:d={fo:.3f}[af]")
            vlast, alast = "[vf]", "[af]"
        pro = getattr(opts, "vcodec", "") == "prores"
        aud = ["-map", alast, "-c:a", "pcm_s16le" if pro else "aac"] + ([] if pro else ["-b:a", "192k"]) \
            if getattr(opts, "audio", True) else ["-an"]
        if not getattr(opts, "audio", True):
            fc.append(f"{alast}anullsink")
        args += ["-filter_complex", ";".join(fc), "-map", vlast, *aud,
                 *_venc(opts, True), "-pix_fmt", "yuv422p10le" if pro else "yuv420p",
                 *([] if pro else ["-movflags", "+faststart"]),
                 "-t", f"{total:.3f}", out_path]
        say(weight_seg, "合併與轉場…")
        _run_progress(args, total, lambda f: say(weight_seg + (1 - weight_seg) * f, "合併與轉場…"),
                      cancel)
        say(1.0, "完成")
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


SEG_LEN = float(os.environ.get("IE_SEG_LEN", 6.5))     # R50：真實挑選中位數 6.7 s（原 4 s）
SECOND_REL = float(os.environ.get("IE_SECOND_REL", 0.0))  # R50：第二段分數 ≥ 這個門檻（相對分數差）才給「可選第二段」
# R55+：檔內定位（對 123 支真實剪輯精確範圍調校，train split seed 49）
POS = dict(short_whole=float(os.environ.get("IE_SHORT_WHOLE", 0.0)),   # 短於此秒數的影片整支當一段
           pos_w=float(os.environ.get("IE_POS_W", 0.0)),               # 位置先驗權重（相對檔內分數標準差）
           pos_mu=float(os.environ.get("IE_POS_MU", 0.45)),            # 先驗中心（片長比例）
           pos_sigma=float(os.environ.get("IE_POS_SIGMA", 0.25)))


def candidates_for_video(path, count=2, seg_len=None, step=0.5, dup=0.93, prefs=None, enabled=None, cfg=None):
    """單支影片推薦：預設 1 段最佳 + 1 段可選（seg.optional=True 時預設不勾）。長片每 30 秒多 1 段（上限 40）。
    每段附帶 sig（去重用小圖）、peak（最精彩的秒數，慢動作用）、track（主體水平位置軌跡）；
    回傳的 list 另有 .worth（整支影片值不值得留，見 file_worth）。"""
    info = probe(path)
    f = features(path, step, info)
    return candidates_from_features(f, path, info.duration, count, seg_len, step, dup, prefs=prefs, enabled=enabled, cfg=cfg)


class _Cands(list):
    features = None
    worth = 0.0
    person = 0.0
    bad = 0.0


def candidates_from_features(f, path, duration, count=2, seg_len=None, step=0.5, dup=0.93, prefs=None, enabled=None, cfg=None):
    seg_len = SEG_LEN if seg_len is None else seg_len
    # R42：長片（實測 19 分鐘 LRV）只給少數幾段太少 → 每 30 秒至少 1 段，上限 40
    count = max(count, min(40, int(duration // 30)))
    L = min(seg_len, duration)
    if POS["short_whole"] > 0 and duration < POS["short_whole"]:
        L = duration                                   # R55：短片整支保留
    win = max(1, int(round(L / step)))
    sc = f.score
    csum = np.convolve(sc, np.ones(win), mode="valid") / win if len(sc) >= win else np.array([sc.mean()])
    sel = csum
    if POS["pos_w"] > 0 and len(csum) > 1:             # R57：選窗時加位置先驗（不影響 raw 分數 / worth）
        c = (np.arange(len(csum)) * step + L / 2) / max(duration, 1e-6)
        prior = np.exp(-0.5 * ((c - POS["pos_mu"]) / POS["pos_sigma"]) ** 2)
        sel = csum + POS["pos_w"] * (float(np.std(csum)) + 1e-3) * prior
    used, out = [], _Cands()
    span = max(duration, 1e-6)
    for _ in range(count):
        best, bi = None, None
        for idx in np.argsort(-sel)[:400]:
            s = float(f.times[idx]) if idx < len(f.times) else 0.0
            for c in f.cuts:
                if 0 <= c - s < 1.0:
                    s = c; break
            s = max(0.0, min(s, duration - L)); e = s + L
            if any(not (e <= a or s >= b) for a, b, *_ in used):
                continue
            i0, i1 = int(s / step), max(int(s / step) + 1, int(e / step))
            sig = f.thumbs[min(len(f.thumbs) - 1, (i0 + i1) // 2)]
            if any(similar(sig, u[2]) > dup for u in used):
                continue
            # 時間分散：離已選片段越近，分數打折（MMR）
            near = min([abs(s - u[0]) / span for u in used] + [1.0])
            val = float(sel[idx]) - 0.15 * (1 - near) ** 4
            if best is None or val > best[0]:
                best, bi = (val, s, e, sig, float(csum[idx])), (i0, i1)
            if len(used) == 0:
                break
        if best is None:
            break
        _, s, e, sig, raw = best; i0, i1 = bi
        seg = Segment(path, round(s, 2), round(e, 2), raw)
        loc = sc[i0:i1]
        seg.peak = round(s + (int(np.argmax(loc)) if len(loc) else 0) * step + step / 2, 2)
        lo_i, hi_i = max(0, i0 - 2), min(len(f.focus_x), i1 + 2)
        seg.track = {"t0": round(lo_i * step, 3), "step": step,
                     "x": [round(float(x), 3) for x in f.focus_x[lo_i:hi_i]]}
        if getattr(f, "focus_y", None) is not None:
            seg.track["y"] = [round(float(y), 3) for y in f.focus_y[lo_i:hi_i]]
        if f.face is not None and np.any(f.face[lo_i:hi_i] > 0):
            seg.track["c"] = [round(float(v), 2) for v in f.face[lo_i:hi_i]]   # 有臉的取樣點（可信度）
        seg.sig = sig
        seg.quality = {"sharp": float(f.sharp[i0:i1].mean()) if i1 > i0 else 1.0,
                       "shake": float(f.shake[i0:i1].mean()) if i1 > i0 else 0.0}
        # R50：第 1 段一定勾；之後的段只有分數接近最佳段（差 ≤ SECOND_REL）才不是 optional
        seg.optional = bool(out) and (raw < out[0].score - SECOND_REL)
        seg.rank = len(out)
        used.append((s, e, sig)); out.append(seg)
    out.worth = file_worth(f, duration, out)
    pe = getattr(f, "person", None)
    out.person = float(np.percentile(pe, 90)) if pe is not None and len(pe) else 0.0
    pen = penalties(f)
    out.bad = float(np.mean(np.max(np.stack([pen[0], pen[1] * 0.5, pen[2], pen[3]]), 0))) if len(f.times) else 0.0
    if STRATEGIES and duration <= STRAT_MAX_DUR:
        out = strategy_candidates(f, path, duration, out, prefs=prefs, step=step, enabled=enabled, cfg=cfg)
    out.sort(key=lambda c: c.start)
    out.features = f            # R66：library 存成快取，改策略時只重算候選、不重新解碼
    return out


# ---------------- R59+：多策略候選（R66：7 種策略、每策略 len/n 參數） ----------------
STRATEGIES = os.environ.get("IE_STRATEGIES", "1") != "0"
STRAT_MAX_DUR = float(os.environ.get("IE_STRAT_MAX_DUR", 1e9))   # R66：清單模式所有影片都用策略（長片也受每支 ≤12 段與策略開關控制）
STRAT_ORDER = ["start", "people", "action", "whole", "uniform", "loud", "scene"]
STRAT_NAMES = {"start": "從頭開始", "people": "AI 人物", "action": "精彩動作", "whole": "整支（短片）",
               "uniform": "均勻取樣", "loud": "音量高峰", "scene": "場景變換", "manual": "手動"}
STRAT_TIPS = {"start": "影片開頭一段，適合開場、交代地點", "people": "人物最清楚、最靠近鏡頭的時候",
              "action": "動作、聲音最激烈的高潮", "whole": "短於門檻的影片整支保留，不切",
              "uniform": "平均分佈抓幾段", "loud": "笑聲、歡呼、尖叫等最大聲的時刻",
              "scene": "換景後的第一個畫面，適合長片"}
STRAT_ALIAS = {"middle": "uniform"}       # R66：舊資料庫的「中段」顯示為「均勻取樣」


def strat_key(k):
    return STRAT_ALIAS.get(k, k)


# 預設值與範圍（SPEC §2）：len＝片段長度（whole 為門檻），n＝每支最多
STRAT_PER = {"start": dict(on=True, len=7.0, n=1), "people": dict(on=True, len=6.5, n=1),
             "action": dict(on=True, len=6.5, n=2), "whole": dict(on=True, len=10.0, n=1),
             "uniform": dict(on=True, len=6.5, n=1), "loud": dict(on=False, len=5.0, n=2),
             "scene": dict(on=False, len=4.0, n=3)}
STRAT_RANGE = {"start": ((3, 15), (1, 1)), "people": ((3, 15), (1, 3)), "action": ((3, 15), (1, 5)),
               "whole": ((5, 30), (1, 1)), "uniform": ((2, 15), (1, 1)), "loud": ((2, 15), (1, 5)),
               "scene": ((2, 10), (1, 10))}
STRAT_TOTAL_MAX = 12
# 先驗：train split（seed 49）上各策略 IoU≥0.5 的比例（R60 量測；uniform 沿用 middle；loud/scene 為 R67 train 量測）
STRAT_PRIOR = {"whole": 0.96, "people": 0.575, "start": 0.517, "uniform": 0.494, "action": 0.494,
               "loud": 0.54, "scene": 0.32}
STRAT_PRIOR_N = 30.0      # 先驗等同幾次「顯示」（R61：10 時學習太快，模擬中會被合併標籤帶偏）
STRAT_CFG = dict(start_len=7.0, mid_mu=0.45, win=6.5, whole_max=10.0, merge_iou=0.6, show_min=2, show_max=STRAT_TOTAL_MAX,
                 nms_iou=0.3, loud_pos=0.4, scene_off=0.5, scene_thr=float(os.environ.get("IE_SCENE_THR", 0.05)),
                 scene_k=float(os.environ.get("IE_SCENE_K", 2.0)),
                 people=dict(person=0.5, near=2.0, occ=0.5, shake=0.0, motion=0.0, sharp=0.0),    # R60 train 調校
                 action=dict(motion=0.5, peak=1.2, audio=0.4, shake=0.5, occ=1.5))


def strategy_config(cfg=None, enabled=None):
    """合併使用者設定與預設：{key: {on, len, n}}（範圍外的值夾回範圍）。enabled（舊 API）＝只開這些。"""
    out = {}
    cfg = {strat_key(k): v for k, v in (cfg or {}).items()}
    for k, d in STRAT_PER.items():
        c = dict(d); c.update({a: b for a, b in (cfg.get(k) or {}).items() if a in ("on", "len", "n")})
        (l0, l1), (n0, n1) = STRAT_RANGE[k]
        c["len"] = float(min(l1, max(l0, float(c["len"])))); c["n"] = int(min(n1, max(n0, int(c["n"]))))
        c["on"] = bool(c["on"]); out[k] = c
    if enabled:
        en = {strat_key(k) for k in enabled}
        for k in out:
            out[k]["on"] = k in en
    return out


def strategy_weights(prefs=None):
    """每個策略的偏好分數 = (勾選次數 + N·先驗) / (顯示次數 + N)。prefs = {策略: {"picks": n, "shown": n}}。"""
    prefs = {strat_key(k): v for k, v in (prefs or {}).items()}
    out = {}
    for k, p0 in STRAT_PRIOR.items():
        st = prefs.get(k) or {}
        out[k] = (float(st.get("picks", 0)) + STRAT_PRIOR_N * p0) / (float(st.get("shown", 0)) + STRAT_PRIOR_N)
    return out


def _z(v):
    v = np.asarray(v, np.float64)
    return (v - v.mean()) / (v.std() + 1e-6) if len(v) else v


def _best_window(sig, L, duration, step):
    w = _top_windows(sig, L, duration, step, 1)
    return w[0] if w else 0.0


def _top_windows(sig, L, duration, step, n, nms=0.3):
    """R66：訊號的 top-N 窗口起點（窗口平均最高、彼此 IoU < nms）。"""
    win = max(1, int(round(L / step)))
    if len(sig) < win:
        return [0.0]
    c = np.convolve(sig, np.ones(win), mode="valid") / win
    out = []
    for idx in np.argsort(-c, kind="stable"):
        s = float(min(max(0.0, int(idx) * step), max(0.0, duration - L)))
        if all(_iou((s, s + L), (o, o + L)) < nms for o in out):
            out.append(s)
            if len(out) >= n:
                break
    return out


def _peak_windows(sig, times, L, duration, n, pos=0.4, nms=0.3):
    """R66：訊號最高點（峰值）放在窗口 pos 處的 top-N 窗口，彼此 IoU < nms。"""
    out = []
    for idx in np.argsort(-np.asarray(sig), kind="stable"):
        s = float(min(max(0.0, float(times[idx]) - pos * L), max(0.0, duration - L)))
        if all(_iou((s, s + L), (o, o + L)) < nms for o in out):
            out.append(s)
            if len(out) >= n:
                break
    return out


def has_audio_signal(f):
    a = getattr(f, "audio", None)
    return a is not None and len(a) > 1 and float(np.std(a)) > 1e-6 and float(np.max(a)) > 1e-4


def scene_changes(f, thr=None, k=None):
    """R66：場景變換點 [(秒, 變化量)]，依變化量排序。用相鄰縮圖（9×16 RGB）的平均絕對差；
    門檻＝max(thr, 中位數 + k·MAD)（魚眼 LRV 小晃動不算換景）。"""
    th = getattr(f, "thumbs", None)
    if th is None or len(th) < 3:
        return []
    T = np.asarray(th, np.float32).reshape(len(th), -1)
    if T.max() > 1.5:
        T = T / 255.0
    d = np.abs(np.diff(T, axis=0)).mean(1)
    # 兩格平均，避免單格閃爍
    d = np.maximum(d, 0)
    thr = STRAT_CFG["scene_thr"] if thr is None else thr
    k = STRAT_CFG["scene_k"] if k is None else k
    med = float(np.median(d)); mad = float(np.median(np.abs(d - med))) + 1e-6
    lim = max(thr, med + k * mad)
    times = np.asarray(f.times)
    pts = [(float(times[min(i + 1, len(times) - 1)]), float(v)) for i, v in enumerate(d) if v > lim]
    return sorted(pts, key=lambda x: -x[1])


def _iou(a, b):
    i = max(0.0, min(a[1], b[1]) - max(a[0], b[0])); u = max(a[1], b[1]) - min(a[0], b[0])
    return i / u if u > 0 else 0.0


def strategy_windows(f, duration, cfg=None, step=0.5):
    """R66：每個開啟的策略各自的窗口 [(策略, start, end, 策略內名次)]（尚未合併）。"""
    C = STRAT_CFG; D = float(duration); P = cfg if cfg is not None else strategy_config()
    g = lambda k: np.asarray(getattr(f, k)) if getattr(f, k, None) is not None and len(getattr(f, k)) == len(f.times) \
        else np.zeros(len(f.times))
    occ = penalties(f)[0] if len(f.times) else np.zeros(0)
    nms = C["nms_iou"]
    wins = []
    on = lambda k: P[k]["on"]
    Lk = lambda k: min(P[k]["len"], D)
    if on("whole") and D < P["whole"]["len"]:
        wins.append(("whole", 0.0, D, 0))
    if on("start"):
        wins.append(("start", 0.0, Lk("start"), 0))
    if on("uniform"):
        L = Lk("uniform"); n = P["uniform"]["n"]
        cs = [C["mid_mu"] * D] if n == 1 else [(i + 0.5) / n * D for i in range(n)]
        for r, c in enumerate(cs):
            s = max(0.0, min(D - L, c - L / 2)); wins.append(("uniform", s, s + L, r))
    if len(f.times):
        if on("people"):
            pw = C["people"]; L = Lk("people")
            sp = (pw["person"] * _z(g("person")) + pw["near"] * _z(g("near")) - pw["occ"] * _z(occ)
                  - pw["shake"] * _z(g("shake")) - pw["motion"] * _z(g("motion")) + pw["sharp"] * _z(g("sharp")))
            for r, s in enumerate(_top_windows(sp, L, D, step, P["people"]["n"], nms)):
                wins.append(("people", s, s + L, r))
        if on("action"):
            aw = C["action"]; L = Lk("action")
            sa = (aw["motion"] * _z(g("motion")) + aw["peak"] * _z(g("peak")) + aw["audio"] * _z(g("audio"))
                  - aw["shake"] * _z(g("shake")) - aw["occ"] * _z(occ))
            for r, s in enumerate(_top_windows(sa, L, D, step, P["action"]["n"], nms)):
                wins.append(("action", s, s + L, r))
        if on("loud") and has_audio_signal(f):
            L = Lk("loud"); a = g("audio")
            sm = np.convolve(a, np.ones(3) / 3, mode="same") if len(a) >= 3 else a   # 1.5 秒平滑，避免單點爆音
            for r, s in enumerate(_peak_windows(sm, f.times, L, D, P["loud"]["n"], C["loud_pos"], nms)):
                wins.append(("loud", s, s + L, r))
        if on("scene"):
            L = Lk("scene"); got = []
            for t, _v in scene_changes(f):
                s = max(0.0, min(D - L, t + C["scene_off"]))
                if all(_iou((s, s + L), (o, o + L)) < nms for o in got):
                    got.append(s)
                    if len(got) >= P["scene"]["n"]:
                        break
            for r, s in enumerate(got):
                wins.append(("scene", s, s + L, r))
    return [(k, round(max(0.0, s), 2), round(min(D, e), 2), r) for k, s, e, r in wins if e - s > 0.05]


def strategy_candidates(f, path, duration, legacy=None, prefs=None, step=0.5, enabled=None, cfg=None):
    """R59/R66：每支影片依開啟的策略產生候選（每策略 1–N 段）。IoU>merge_iou 的合併（保留所有標籤）；
    依 strategy_weights 與策略內名次排序，每支總數 ≤ STRAT_TOTAL_MAX；第 1 段預設勾選（library 再依分數判斷）。
    每段 .strategies = [策略...]；.score 用原本精彩分數的區間平均；worth/person/bad 沿用舊候選。"""
    C = STRAT_CFG; D = float(duration)
    P = strategy_config(cfg, enabled)
    wins = strategy_windows(f, D, P, step)
    W = strategy_weights(prefs)
    segs = []
    for name, s, e, r in sorted(wins, key=lambda w: (w[3], -W[w[0]])):
        hit = next((x for x in segs if _iou((x.start, x.end), (s, e)) > C["merge_iou"]), None)
        if hit is not None:
            if name not in hit.strategies:
                hit.strategies.append(name)
            continue
        i0, i1 = int(s / step), max(int(s / step) + 1, int(e / step))
        sc = f.score[i0:i1] if len(f.score) else np.zeros(0)
        seg = Segment(path, s, e, float(sc.mean()) if len(sc) else 0.0)
        seg.strategies = [name]
        seg.peak = round(s + (int(np.argmax(sc)) if len(sc) else 0) * step + step / 2, 2)
        lo_i, hi_i = max(0, i0 - 2), min(len(f.focus_x), i1 + 2)
        seg.track = {"t0": round(lo_i * step, 3), "step": step, "x": [round(float(x), 3) for x in f.focus_x[lo_i:hi_i]]}
        if getattr(f, "focus_y", None) is not None:
            seg.track["y"] = [round(float(y), 3) for y in f.focus_y[lo_i:hi_i]]
        seg.sig = f.thumbs[min(len(f.thumbs) - 1, (i0 + i1) // 2)] if len(f.thumbs) else None
        seg.quality = {"sharp": float(f.sharp[i0:i1].mean()) if i1 > i0 and len(getattr(f, "sharp", [])) else 1.0,
                       "shake": float(f.shake[i0:i1].mean()) if i1 > i0 and len(getattr(f, "shake", [])) else 0.0}
        segs.append(seg)
    uni = lambda sg: set(getattr(sg, "strategies", None) or []) == {"uniform"}
    segs = [sg for sg in segs if not uni(sg)] + [sg for sg in segs if uni(sg)]   # R70：保底的均勻取樣排最後
    segs = segs[:STRAT_TOTAL_MAX]
    for i, seg in enumerate(segs):
        seg.rank = i; seg.optional = i > 0 or uni(seg)                          # R70：只有均勻取樣 → 不自動勾
    out = _Cands(segs)
    if legacy is not None:
        out.worth, out.person, out.bad = legacy.worth, legacy.person, legacy.bad
    return out


def file_worth(f, duration, cands=None):
    """R51：整支影片「值不值得留」分數（越高越值得）；長度加權、< 3 秒極低。之後由 ranking.rank_files 做跨檔處理。"""
    best = max([c.score for c in (cands or [])] + [float(np.max(f.score)) if len(f.score) else 0.0])
    return best


def _flat_vf(path, w, h):
    """預覽/縮圖用：圓形魚眼先攤平成 16:9（R38），其他維持原樣縮放。"""
    if detect_projection(path) == "fisheye":
        return fisheye_view(w, h)
    return None


def thumbnail(path, t, out_png, width=240):
    vf = _flat_vf(path, width, width * 9 // 16 // 2 * 2) or f"scale={width}:-2"
    _run([find_ffmpeg(), "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
          "-vf", vf, out_png])
    return out_png if os.path.exists(out_png) else None


def list_music(folder):
    exts = (".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg")
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(exts))


def preview_proxy(seg, out_mp4, height=180):
    """候選片段的低解析度、靜音預覽 MP4（卡片內循環播放用）。"""
    _run([find_ffmpeg(), "-y", "-v", "error", "-ss", f"{seg.start:.2f}", "-t", f"{seg.length:.2f}",
          "-i", seg.path, "-an", "-vf", (_flat_vf(seg.path, height * 16 // 9 // 2 * 2, height) or f"scale=-2:{height}") + ",fps=15,format=yuv420p",
          "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-movflags", "+faststart", out_mp4])
    return out_mp4 if os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 0 else None


def fit_to_target(segments, target, min_len=1.5):
    """成品長度超過 target 時，各片段依比例從兩端等量縮短（每段最短 min_len 秒）。
    回傳 (新片段, 仍超過的秒數)；仍超過 > 0 時 UI 顯示「仍超過 n 秒，建議取消勾選 k 段」。"""
    if not target or target <= 0:
        return list(segments), 0.0
    lens = [s.end - s.start for s in segments]
    excess = sum(lens) - target
    new = lens[:]
    while excess > 1e-6:
        free = [i for i, l in enumerate(new) if l > min_len + 1e-9]
        if not free:
            break
        tot = sum(new[i] for i in free)
        cut_all = 0.0
        for i in free:
            cut = min(excess * new[i] / tot, new[i] - min_len)
            new[i] -= cut; cut_all += cut
        excess -= cut_all
        if cut_all < 1e-9:
            break
    out = []
    for s, l0, l in zip(segments, lens, new):
        d = (l0 - l) / 2
        out.append(Segment(s.path, s.start + d, s.end - d, s.score))
    return out, max(0.0, round(excess, 3))


def suggest_drop_count(segments, overflow):
    """仍超過時，建議取消勾選幾段（從分數最低的開始算）。"""
    n, acc = 0, 0.0
    for s in sorted(segments, key=lambda s: s.score):
        if acc >= overflow - 1e-9:
            break
        acc += s.end - s.start; n += 1
    return n


@dataclasses.dataclass
class ClipOptions:
    """R66：片段匯出設定（右側「匯出設定」面板）。"""
    pattern: str = "seq"        # seq：影片名_策略_序號；time：影片名_時間_策略；date：日期_序號
    fmt: str = "mp4"            # mp4（H.264）/ hevc（MP4 HEVC）/ prores（MOV ProRes 422）
    aspect: str = "orig"        # orig / 16:9 / 9:16 / 1:1
    resolution: str = "orig"    # orig / 1080p / 720p
    audio: bool = True          # False：不含音軌
    subfolders: bool = True     # 依影片建立子資料夾
    overwrite: bool = False     # 同名覆寫（仍先寫 .part，成功才取代）
    ascii_only: bool = False    # 檔名只用英數（策略用英文 key）
    hw_encode: bool = False
    reframe: str = "smart"
    projection: str = ""


CLIP_FORMATS = {"mp4": ("MP4（H.264）", ".mp4"), "hevc": ("MP4（HEVC）", ".mp4"), "prores": ("MOV（ProRes）", ".mov")}
CLIP_PATTERNS = {"seq": "影片名_策略_序號", "time": "影片名_時間_策略", "date": "日期_序號"}
_BAD = r'[\\/:*?"<>|\x00-\x1f]'


def strat_label(strategies, ascii_only=False):
    k = strat_key((strategies or ["manual"])[0])
    if ascii_only:
        return k
    return re.sub(r"（.*?）|\s", "", STRAT_NAMES.get(k, k))


def video_date(src):
    m = re.search(r"(20\d{6})[_-]?\d{0,6}", os.path.basename(src))
    if m:
        return m.group(1)
    try:
        import time
        return time.strftime("%Y%m%d", time.localtime(os.path.getmtime(src)))
    except OSError:
        return "00000000"


def clip_filename(src, start, end, strategies=None, ext=".mp4", pattern="time", seq=1, ascii_only=False):
    """單段匯出檔名。pattern：
    time（R65 舊規則）＝<來源>_<0m12_5s>-<0m19_0s>_<策略+策略>；seq＝<來源>_<第一個策略中文名>_<01>；date＝<日期>_<01>。
    非法字元換成 _；ascii_only 時非 ASCII 字元也換成 _（策略用英文 key）。"""
    def t(x):
        m, sec = divmod(max(0.0, float(x)), 60)
        return f"{int(m)}m{sec:04.1f}s".replace(".", "_")
    base = os.path.splitext(os.path.basename(src))[0]
    if pattern == "seq":
        name = f"{base}_{strat_label(strategies, ascii_only)}_{int(seq):02d}"
    elif pattern == "date":
        name = f"{video_date(src)}_{int(seq):02d}"
    else:
        st = "+".join(strat_key(s) for s in (strategies or [])) or "manual"
        name = f"{base}_{t(start)}-{t(end)}_{st}"
    name = re.sub(_BAD, "_", name)
    if ascii_only:
        name = re.sub(r"[^\x20-\x7e]", "_", name)
    return name + ext


def plan_clip_names(items, co=None):
    """R66：每段的相對輸出路徑（含子資料夾），序號＝同一支影片、同一策略內依時間 01…（date 規則：同一天內）。
    同一批內重名加 _2。不檢查磁碟（export_clips 再處理）。"""
    co = co or ClipOptions()
    ext = CLIP_FORMATS.get(co.fmt, CLIP_FORMATS["mp4"])[1]
    order = sorted(range(len(items)), key=lambda i: (items[i][0].path, items[i][0].start))
    cnt, seqs = {}, {}
    for i in order:
        seg, st = items[i]
        key = (video_date(seg.path),) if co.pattern == "date" else (seg.path, strat_label(st, True))
        cnt[key] = cnt.get(key, 0) + 1; seqs[i] = cnt[key]
    out, used = [], set()
    for i, (seg, st) in enumerate(items):
        n = clip_filename(seg.path, seg.start, seg.end, st, ext, co.pattern, seqs[i], co.ascii_only)
        sub = re.sub(_BAD, "_", os.path.splitext(os.path.basename(seg.path))[0]) if co.subfolders else ""
        if co.ascii_only:
            sub = re.sub(r"[^\x20-\x7e]", "_", sub)
        rel = os.path.join(sub, n) if sub else n; k = 2
        while rel in used:
            rel = os.path.join(sub, n[:-len(ext)] + f"_{k}{ext}") if sub else n[:-len(ext)] + f"_{k}{ext}"; k += 1
        used.add(rel); out.append(rel)
    return out


def _clip_direct(seg, out_path, co, cb, cancel):
    """原始比例：直接裁時間＋（可選）縮小，不做魚眼展開／裁切。輸出時長誤差 ≤ 1 格。"""
    ff = find_ffmpeg(); info = probe(seg.path)
    L = max(0.05, seg.end - seg.start)
    pro = co.fmt == "prores"
    vf = []
    b = {"1080p": 1080, "720p": 720}.get(co.resolution)
    if b and min(info.width or b, info.height or b) > b:
        vf.append(f"scale='if(gte(iw,ih),-2,{b})':'if(gte(iw,ih),{b},-2)'")
    vf.append("format=yuv422p10le" if pro else "format=yuv420p")
    args = [ff, "-y", "-v", "error", "-ss", f"{seg.start:.3f}", "-t", f"{L:.3f}", "-i", seg.path, "-map", "0:v:0"]
    if co.audio and info.has_audio:
        args += ["-map", "0:a:0", "-c:a", "pcm_s16le" if pro else "aac"] + ([] if pro else ["-b:a", "192k"])
    else:
        args += ["-an"]
    eo = ExportOptions(); eo.vcodec = "" if co.fmt == "mp4" else co.fmt; eo.hw_encode = co.hw_encode
    args += ["-vf", ",".join(vf), *_venc(eo, True), "-t", f"{L:.3f}"]
    if not pro:
        args += ["-movflags", "+faststart"]
    if co.fmt != "prores":
        args += ["-f", "mp4"]
    else:
        args += ["-f", "mov"]
    _run_progress(args + [out_path], L, cb, cancel)


def _clip_reframed(seg, out_path, co, cb, cancel):
    eo = ExportOptions(aspect=co.aspect, resolution="720p" if co.resolution == "720p" else "1080p",
                       crossfade=0.0, music="", fade_out=0, title="", effect="", keep_original_audio=co.audio,
                       hw_encode=co.hw_encode, reframe=co.reframe, projection=co.projection)
    eo.vcodec = "" if co.fmt == "mp4" else co.fmt; eo.audio = co.audio
    _export([seg], out_path, eo, (lambda f, m: cb(f)) if cb else None, cancel)


def export_clip(seg, out_path, co=None, progress=None, cancel=None):
    """R66：輸出一段到 out_path。一律先寫 <名稱>.part<副檔名>，成功才 os.replace；
    取消或失敗只刪自己的 .part——原本存在的同名檔絕不會被刪（SPEC 驗收 #4）。"""
    co = co or ClipOptions()
    want = float(seg.end) - float(seg.start)
    seg, src = clamp_segment(seg)
    root, ext = os.path.splitext(out_path)
    part = root + ".part" + (ext or ".mp4")
    cb = (lambda f: progress(f)) if progress else None
    try:
        if co.aspect == "orig" and not getattr(seg, "ramp", None) and not getattr(seg, "curve", None):
            _clip_direct(seg, part, co, cb, cancel)
        else:
            _clip_reframed(seg, part, co, cb, cancel)
        validate_clip(part, seg, co, src)
        os.replace(part, out_path)
        return ClipPath(out_path, want, seg.end - seg.start)
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass


class ClipInvalid(RuntimeError):
    """R70：輸出檔驗證失敗（沒有影像/聲音或太短）——不可回報成功。"""


CLIP_MIN_SEC = 0.3


class ClipPath(str):
    """R71：export_clip 的回傳值——仍是路徑字串，另帶 want（要求秒數）與 got（夾到素材長度後的秒數），
    讓完成對話框能標出「已截短」。"""
    def __new__(cls, path, want=None, got=None):
        o = super().__new__(cls, path); o.want, o.got = want, got; return o

    @property
    def truncated(self):
        return bool(self.want and self.got is not None and self.got < self.want - 0.05)


def clamp_segment(seg):
    """R70：入點/出點夾回素材實際長度（資料庫裡的時間可能超出檔尾，或素材被換過）。
    回傳 (新 Segment 副本, MediaInfo)；夾完長度不足 CLIP_MIN_SEC 時丟 ClipInvalid。"""
    import copy
    src = probe(seg.path)
    D = float(src.duration or 0)
    s0 = max(0.0, min(float(seg.start), D)); e0 = max(0.0, min(float(seg.end), D))
    if e0 - s0 < CLIP_MIN_SEC:
        raise ClipInvalid(f"入點／出點超出素材長度（素材 {D:.2f} 秒，片段 {seg.start:.2f}–{seg.end:.2f} 秒）")
    if (s0, e0) != (seg.start, seg.end):
        seg = copy.copy(seg); seg.start, seg.end = s0, e0
    return seg, src


def validate_clip(path, seg, co, src=None):
    """R70：匯出後檢查：要有影像串流；保留原聲且素材有聲音時要有音軌；長度不能明顯短於預期。"""
    try:
        info = probe(path)
    except Exception as e:  # noqa: BLE001
        raise ClipInvalid(f"輸出檔無法讀取或沒有影像：{e}") from None
    if getattr(co, "audio", False) and (src is None or src.has_audio) and not info.has_audio:
        raise ClipInvalid("輸出檔沒有聲音")
    want = seg.end - seg.start
    if not (getattr(seg, "ramp", None) or getattr(seg, "curve", None)):
        need = max(CLIP_MIN_SEC, want - max(0.5, 0.1 * want))
    else:
        need = CLIP_MIN_SEC          # 變速片段長度會變，只擋幾乎是空檔
    if info.duration < need:
        raise ClipInvalid(f"輸出檔太短（{info.duration:.2f} 秒，預期約 {want:.2f} 秒）")
    return info


def _as_clip_options(opts):
    if isinstance(opts, ClipOptions):
        return opts
    co = ClipOptions(pattern="time", subfolders=False)
    if isinstance(opts, ExportOptions):      # R65 舊呼叫：只沿用比例/解析度/原聲（音樂、轉場一律忽略）
        co.aspect, co.audio = opts.aspect, opts.keep_original_audio
        co.resolution = opts.resolution if opts.resolution in ("1080p", "720p") else "1080p"
        co.hw_encode, co.reframe, co.projection = opts.hw_encode, opts.reframe, opts.projection
    return co


def export_clips(items, folder, opts=None, progress=None, cancel=None):
    """R65/R66：每個已選片段各自輸出成一支檔案（不合併、不加音樂、轉場、字幕）。
    items: [(Segment, strategies)]；opts: ClipOptions（也接受舊的 ExportOptions/None）。
    同名：overwrite=False 時加 _2、_3；True 時成功後才取代。progress(fraction, "i/n …")。
    回傳 [(path 或 None, 錯誤訊息或 None)]；取消時丟 Cancelled（已完成的保留、不留 .part、舊檔不動）。"""
    co = _as_clip_options(opts)
    os.makedirs(folder, exist_ok=True)
    names = plan_clip_names(items, co)
    out, n = [], max(1, len(items))
    taken = set()
    for i, ((seg, strats), rel) in enumerate(zip(items, names)):
        if cancel and cancel():
            raise Cancelled()
        p = os.path.join(folder, rel)
        if not co.overwrite:
            stem, ext = os.path.splitext(p); k = 2
            while os.path.exists(p) or p in taken:
                p = f"{stem}_{k}{ext}"; k += 1
        taken.add(p)
        if progress:
            progress(i / n, f"{i + 1}/{n}")
        sub = (lambda f, i=i: progress((i + f) / n, f"{i + 1}/{n}")) if progress else None
        try:
            os.makedirs(os.path.dirname(p) or folder, exist_ok=True)
            out.append((export_clip(seg, p, co, sub, cancel), None))
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001 — 單段失敗不影響其他段
            out.append((None, f"{type(e).__name__}: {e}"))
    if progress:
        progress(1.0, "完成")
    return out
