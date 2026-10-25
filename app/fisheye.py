"""R39–R41：圓形魚眼的逐格跟拍、水平校正、構圖。

- 人物偵測：OpenCV DNN + NanoDet-Plus（opencv_zoo，Apache-2.0，3.8 MB，隨 app 附帶在 app/models/）。
  先把魚眼攤成等距柱狀（equirect），在上面找人，座標直接就是 yaw/pitch（度）。
- 路徑：deadzone + 緩動追隨 + 移動平均平滑 → v360 的 sendcmd（每 0.1 秒一筆 yaw/pitch）。
- 水平：在攤平後的畫面找接近垂直的直線（桿子、樹幹、建築），長度加權中位數 → roll。
找不到人時退回舊的 focus_x/focus_y（動態重心）。
"""
import math, os, subprocess
import numpy as np

MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "nanodet_2022nov.onnx")
EQW, EQH = 1440, 720          # equirect 360×180 → 每度 4 像素
_NET = {}
_CACHE = {}


def _ff():
    from .core import find_ffmpeg
    return find_ffmpeg()


def has_detector():
    try:
        import cv2
        return os.path.exists(MODEL) and hasattr(cv2, "dnn")
    except Exception:
        return False


class _NanoDet:
    """opencv_zoo object_detection_nanodet 的精簡版後處理（COCO 80 類，0 = person）。"""
    def __init__(self, path):
        import cv2
        self.cv2 = cv2; self.net = cv2.dnn.readNet(path)
        self.strides, self.size, self.reg = (8, 16, 32, 64), 416, 7
        self.mean = np.array([103.53, 116.28, 123.675], np.float32).reshape(1, 1, 3)
        self.std = np.array([57.375, 57.12, 58.395], np.float32).reshape(1, 1, 3)
        self.anchors = []
        for s in self.strides:
            n = self.size // s
            xv, yv = np.meshgrid(np.arange(n) * s, np.arange(n) * s)
            self.anchors.append(np.column_stack((xv.ravel() + 0.5 * (s - 1), yv.ravel() + 0.5 * (s - 1))))

    def people(self, bgr, thr=None):
        thr = float(os.environ.get("IE_DET_T", "0.3")) if thr is None else thr
        cv2 = self.cv2; h, w = bgr.shape[:2]
        img = (cv2.resize(bgr, (self.size, self.size)).astype(np.float32) - self.mean) / self.std
        self.net.setInput(cv2.dnn.blobFromImage(img))
        outs = self.net.forward(self.net.getUnconnectedOutLayersNames())
        boxes, scores = [], []
        for s, cls, reg, anc in zip(self.strides, outs[::2], outs[1::2], self.anchors):
            cls = cls.reshape(-1, cls.shape[-1]); reg = reg.reshape(-1, 4 * (self.reg + 1))
            e = np.exp(reg.reshape(-1, self.reg + 1)); d = (e / e.sum(1, keepdims=True)) @ np.arange(self.reg + 1)
            d = d.reshape(-1, 4) * s
            boxes.append(np.clip(np.column_stack([anc[:, 0] - d[:, 0], anc[:, 1] - d[:, 1],
                                                  anc[:, 0] + d[:, 2], anc[:, 1] + d[:, 3]]), 0, self.size))
            scores.append(cls[:, 0])
        b = np.concatenate(boxes); sc = np.concatenate(scores)
        k = sc > thr
        b, sc = b[k], sc[k]
        if not len(b):
            return []
        wh = b.copy(); wh[:, 2:] -= wh[:, :2]
        idx = np.array(cv2.dnn.NMSBoxes(wh.tolist(), sc.tolist(), thr, 0.5)).ravel()
        f = np.array([w / self.size, h / self.size, w / self.size, h / self.size])
        return [(*(b[i] * f), float(sc[i])) for i in idx]


def _net():
    if "n" not in _NET:
        _NET["n"] = _NanoDet(MODEL) if has_detector() else None
    return _NET["n"]


MAGIC = b"8db42d694ccc418790edff439fe026bf"
_IMU = {}


def read_imu(path):
    """R40：Insta360 檔尾的 IMU 資料（GO 3 實測：record 3 = 每 1 ms 一筆 u64 微秒 + 6×u16（減 32768；前 3 個是加速度，|g|≈1000），
    record 4 = 每格曝光時間戳，第一筆＝影片 t=0）。不是 Insta360 或格式不認得 → None。MP4 與 LRV 都有同一份。"""
    import struct
    key = os.path.realpath(path)
    if key in _IMU:
        return _IMU[key]
    res = None
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2); N = fh.tell()
            fh.seek(N - 72); tail = fh.read(72)
            if tail[-32:] == MAGIC:
                extra = struct.unpack("<I", tail[32:36])[0]
                recs, off = {}, 72
                while off < extra:
                    fh.seek(N - off - 6); fmt, rid, size = struct.unpack("<BBI", fh.read(6))
                    if size <= 0 or size > extra:
                        break
                    if rid in (3, 4):
                        fh.seek(N - off - 6 - size); recs[rid] = fh.read(size)
                    off += size + 6
                g = recs.get(3)
                if g and len(g) % 20 == 0:
                    a = np.frombuffer(g, np.dtype([("t", "<u8"), ("v", "<u2", 6)]))
                    acc = a["v"][:, :3].astype(np.float64) - 32768
                    nrm = np.linalg.norm(acc, axis=1)
                    if 600 < np.median(nrm) < 1600:                  # 真的是加速度（約 1 g）
                        t0 = struct.unpack("<Q", recs[4][:8])[0] if recs.get(4) else int(a["t"][0])
                        res = {"t": (a["t"].astype(np.float64) - t0) / 1e6, "acc": acc}
    except (OSError, struct.error, ValueError):
        res = None
    _IMU[key] = res
    return res


def roll_series(path, start, length, rate=10, smooth=0.4):
    """依重力算每 1/rate 秒的 roll（度）；GO 3 實測 roll = atan2(ax, ay) 時畫面變水平。沒有 IMU → None。"""
    imu = read_imu(path)
    if not imu:
        return None
    t, acc = imu["t"], imu["acc"]
    k = max(1, int(smooth * 1000))                               # 1 kHz → 0.4 秒移動平均
    ax = np.convolve(acc[:, 0], np.ones(k) / k, mode="same"); ay = np.convolve(acc[:, 1], np.ones(k) / k, mode="same")
    ts = start + np.linspace(0, length, max(2, int(round(length * rate)) + 1))
    if ts[0] > t[-1] or ts[-1] < t[0]:
        return None
    return np.degrees(np.arctan2(np.interp(ts, t, ax), np.interp(ts, t, ay)))


def frames_equirect(path, start, length, fov, fps=5, roll=0.0):
    """攤成 equirect 的 BGR 畫面（只取鏡頭範圍內那一塊）。roll 先轉正（rorder=rpy，跟輸出一致）。回傳 (frames, x0)。"""
    half = min(180, fov / 2 + 5)
    x0 = int((180 - half) * EQW / 360); x1 = EQW - x0
    r = subprocess.run([_ff(), "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", path,
                        "-vf", f"fps={fps},v360=input=fisheye:ih_fov={fov:.0f}:iv_fov={fov:.0f}:output=equirect:"
                               f"roll={roll:.2f}:rorder=rpy:w={EQW}:h={EQH},crop={x1 - x0}:{EQH}:{x0}:0",
                        "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
    fw = x1 - x0; n = len(r.stdout) // (fw * EQH * 3)
    return np.frombuffer(r.stdout[: n * fw * EQH * 3], np.uint8).reshape(n, EQH, fw, 3), x0


def _deg(x, y, x0):
    return (x + x0) * 360 / EQW - 180, 90 - y * 180 / EQH


def track(path, start, length, fov, fps=5, roll=0.0):
    """每 1/fps 秒一筆主體 (t, yaw, top, bottom, conf)；找不到人時 conf=0。
    主體：第一次用「面積×可信度×靠近中心」選；之後選離上一次最近、大小相近的人（不會跳到路人）。"""
    key = (path, round(start, 2), round(length, 2), fov, fps, round(roll, 1))
    if key in _CACHE:
        return _CACHE[key]
    net = _net(); out = []
    if net is None:
        return out
    fr, x0 = frames_equirect(path, start, length, fov, fps, roll)
    prev = None; sal = []
    for i, im in enumerate(fr):
        cands = []
        for (a, b, c, d, s) in net.people(im):
            ya, pt = _deg(a, b, x0); yb, pb = _deg(c, d, x0)
            cands.append(((ya + yb) / 2, pt, pb, yb - ya, s))
        pick = None
        if cands:
            if prev is None:
                pick = max(cands, key=lambda q: q[3] * (q[1] - q[2]) * q[4] * (1 - min(0.9, abs(q[0]) / 110)))
            else:
                def cost(q):
                    return (abs(q[0] - prev[0]) + abs((q[1] + q[2]) / 2 - (prev[1] + prev[2]) / 2)
                            + 0.5 * abs((q[1] - q[2]) - (prev[1] - prev[2])))
                q = min(cands, key=cost)
                pick = q if cost(q) < 40 else None
        if pick:
            prev = pick; out.append((i / fps, pick[0], pick[1], pick[2], pick[4]))
        else:
            out.append((i / fps, 0, 0, 0, 0.0))
        sal.append(_saliency(fr[i - 1] if i else None, im, x0))
    # R48：整段幾乎找不到人（<20%）→ 用「畫面中動得最多的地方」當目標（conf 0.01，info 標 saliency）
    if out and sum(1 for q in out if q[4] > 0) < 0.2 * len(out) and os.environ.get("IE_SALIENCY", "1") != "0":
        out = [q if q[4] > 0 else ((q[0],) + sal[k] + (0.01,) if sal[k] else q) for k, q in enumerate(out)]
    _CACHE[key] = out
    return out


def _saliency(a, b, x0):
    """兩張攤平畫面差異最大的 5% 像素重心 → (yaw, top, bottom)；動得太少回傳 None。"""
    if a is None:
        return None
    d = np.abs(a.astype(np.int16) - b.astype(np.int16)).sum(2).astype(np.float32)
    h = d.shape[0]; d[: h // 8] = 0; d[-h // 8:] = 0          # 天空/腳下不算
    th = np.percentile(d, 95)
    if th < 30:
        return None
    ys, xs = np.nonzero(d >= th)
    yaw, pit = _deg(float(np.median(xs)), float(np.median(ys)), x0)
    return (yaw, pit + 12, pit - 12)


def view_fov(W, H, view):
    if W >= H:
        hf = view; vf = math.degrees(2 * math.atan(math.tan(math.radians(hf / 2)) * H / W))
    else:
        vf = view; hf = math.degrees(2 * math.atan(math.tan(math.radians(vf / 2)) * W / H))
    return hf, vf


def frame_target(top, bot, vf, headroom=0.08):
    """構圖（R41）：整個人放得下時置中，但頭上至少留 headroom×畫面高；放不下時保頭（腳可能被切）。"""
    c = (top + bot) / 2
    return max(c, top + headroom * vf - vf / 2) if (top - bot) + 2 * headroom * vf <= vf else top + headroom * vf - vf / 2


def plan(tr, W, H, fov, view, length, rate=10, deadzone=3.0, ease=0.25, headroom=0.08, fallback=(0.0, 0.0)):
    """把偵測結果變成平滑的鏡頭路徑：[(t, yaw, pitch)]，每 1/rate 秒一筆。
    deadzone：目標移動小於這個角度就不動（避免抖）；ease：每 0.1 秒追上剩餘差距的比例。"""
    hf, vf = view_fov(W, H, view)
    my = max(0.0, fov / 2 - hf / 2 - 5); mp = max(0.0, fov / 2 - vf / 2 - 5)
    ok = [q for q in tr if q[4] > 0]
    n = max(2, int(round(length * rate)) + 1)
    ts = np.linspace(0, length, n)
    if ok:
        tt = np.array([q[0] for q in ok])
        ty = np.interp(ts, tt, [q[1] for q in ok])
        tp = np.interp(ts, tt, [frame_target(q[2], q[3], vf, headroom) for q in ok])
    else:
        ty = np.full(n, fallback[0]); tp = np.full(n, fallback[1])
    ty = np.clip(ty, -my, my); tp = np.clip(tp, -mp, mp)
    cy, cp = [ty[0]], [tp[0]]
    for i in range(1, n):
        for arr, tgt in ((cy, ty[i]), (cp, tp[i])):
            d = tgt - arr[-1]
            arr.append(arr[-1] + (math.copysign(abs(d) - deadzone, d) * ease if abs(d) > deadzone else 0.0))
    k = 5
    sm = lambda a: np.convolve(np.pad(a, k // 2, mode="edge"), np.ones(k) / k, mode="valid")
    return [(float(t), float(y), float(p)) for t, y, p in zip(ts, sm(np.array(cy)), sm(np.array(cp)))]


def sendcmd_text(cam, name="v360@cam", min_deg=None, min_gap=None):
    """cam：[(t, yaw, pitch, roll)] → sendcmd 檔案內容。
    注意（實測 ffmpeg 7.0）：v360 每收到一個 yaw/pitch/roll 指令就把旋轉「疊加」上去，畫面會越轉越歪；
    所以每行最後一定要送 reset_rot 1，讓它歸零後只套用一次目前的 yaw/pitch/roll（與靜態濾鏡逐像素相同）。
    R45 加速：v360 每收到一次指令就要重算整張對應表（1080×1920 約 0.2 秒），所以角度變化 < min_deg
    或距上次 < min_gap 秒就不送（IE_CMD_DEG / IE_CMD_GAP 可調）。"""
    md = float(os.environ.get("IE_CMD_DEG", "0.6")) if min_deg is None else min_deg
    mg = float(os.environ.get("IE_CMD_GAP", "0.2")) if min_gap is None else min_gap
    out, last = [], None
    for i, (t, y, p, r) in enumerate(cam):
        if last is not None and i != len(cam) - 1:
            if t - last[0] < mg or max(abs(y - last[1]), abs(p - last[2]), abs(r - last[3])) < md:
                continue
        if last is not None and max(abs(y - last[1]), abs(p - last[2]), abs(r - last[3])) < 0.05:
            continue
        out.append(f"{t:.2f} {name} yaw {y:.2f}, {name} pitch {p:.2f}, {name} roll {r:.2f}, {name} reset_rot 1;\n")
        last = (t, y, p, r)
    return "".join(out)


def camera_path(path, start, length, W, H, fov, view, follow=True, manual_roll=None, fallback=(0.0, 0.0), rate=10):
    """R39–R41 整合：[(t, yaw, pitch, roll)]，t 從 0 起算（相對片段開頭）。另外回傳說明 dict（來源、roll 來源）。"""
    rs = None if manual_roll is not None else roll_series(path, start, length, rate)
    info = {"roll": "manual" if manual_roll is not None else ("imu" if rs is not None else "none")}
    if rs is None:
        r0 = float(manual_roll or 0.0)
        if manual_roll is None and os.environ.get("IE_ROLL_LINES") == "1":
            e = estimate_roll(path, start + length / 2, fov)
            if e is not None:
                r0 = -e; info["roll"] = "lines"
        n = max(2, int(round(length * rate)) + 1); rs = np.full(n, r0)
    rmed = float(np.median(rs))
    tr = track(path, start, length, fov, roll=rmed) if follow else []
    info["detector"] = "nanodet" if tr else ("off" if not follow else "none")
    info["found"] = round(sum(1 for q in tr if q[4] >= 0.05) / len(tr), 2) if tr else 0.0
    info["saliency"] = round(sum(1 for q in tr if 0 < q[4] < 0.05) / len(tr), 2) if tr else 0.0
    pts = plan(tr, W, H, fov, view, length, rate=rate, fallback=fallback)
    rs = np.interp(np.linspace(0, length, len(pts)), np.linspace(0, length, len(rs)), rs)
    return [(t, y, p, float(r)) for (t, y, p), r in zip(pts, rs)], info


def estimate_roll(path, t, fov, yaw=0.0, pitch=0.0, size=640, view=100):
    """在攤平的畫面上找接近垂直的直線，回傳要套用的 roll（度，正 = 畫面順時針轉）。找不到夠多直線回傳 None。"""
    import cv2
    vf = f"v360=input=fisheye:ih_fov={fov:.0f}:iv_fov={fov:.0f}:output=flat:h_fov={view}:v_fov={view}:yaw={yaw:.1f}:pitch={pitch:.1f}:w={size}:h={size}"
    r = subprocess.run([_ff(), "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-vf", vf + ",format=gray",
                        "-f", "rawvideo", "-"], capture_output=True)
    if len(r.stdout) < size * size:
        return None
    g = np.frombuffer(r.stdout[: size * size], np.uint8).reshape(size, size)
    e = cv2.Canny(cv2.GaussianBlur(g, (5, 5), 0), 60, 160)
    L = cv2.HoughLinesP(e, 1, np.pi / 360, 60, minLineLength=size // 8, maxLineGap=6)
    if L is None:
        return None
    ang, wt = [], []
    for x1, y1, x2, y2 in L[:, 0]:
        a = math.degrees(math.atan2(x2 - x1, y2 - y1))       # 與垂直線的夾角
        a = (a + 90) % 180 - 90
        if abs(a) < 30:
            ang.append(a); wt.append(math.hypot(x2 - x1, y2 - y1))
    if len(ang) < 3 or sum(wt) < size * 0.6:
        return None
    o = np.argsort(ang); c = np.cumsum(np.array(wt)[o])
    return float(np.array(ang)[o][np.searchsorted(c, c[-1] / 2)])


PEOPLE_FPS = float(os.environ.get("IE_PEOPLE_FPS", 1.0))


def people_series(path, duration, fov=None, fps=None):
    """R52：整支魚眼影片每 1/fps 秒在「攤平後」畫面找人（不是在原始魚眼圓上找，邊緣的人會被扭曲到偵測不到）。
    魚眼 → equirect（3 px/度，只取鏡頭範圍、仰角 ±60°）→ 左右兩塊各自丟 NanoDet。
    回傳 (t, conf, near)：conf＝最可信的人 0..1；near＝最大的人有多近（框高 15°→0、55°→1）。沒有偵測器 → None。"""
    net = _net()
    if net is None or duration <= 0:
        return None
    from .core import FISHEYE_FOV
    fov = fov or FISHEYE_FOV
    fps = fps or PEOPLE_FPS
    W, H = 1080, 540                       # 3 px / 度
    half = min(180, fov / 2 + 5)
    x0 = int((180 - half) * W / 360); x1 = W - x0
    y0, y1 = int(30 * H / 180), int(150 * H / 180)   # 仰角 +60° .. -60°
    fw, fh = x1 - x0, y1 - y0
    p = subprocess.Popen([_ff(), "-v", "error", "-i", path, "-an",
                          "-vf", f"fps={fps},v360=input=fisheye:ih_fov={fov:.0f}:iv_fov={fov:.0f}:output=equirect:"
                                 f"w={W}:h={H},crop={fw}:{fh}:{x0}:{y0}",
                          "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    ts, conf, near = [], [], []
    try:
        i = 0
        while True:
            buf = p.stdout.read(fw * fh * 3)
            if len(buf) < fw * fh * 3:
                break
            im = np.frombuffer(buf, np.uint8).reshape(fh, fw, 3)
            c = n_ = 0.0
            half_w = fw // 2
            for xs in (0, half_w - fw // 6, fw - half_w):       # 三塊重疊，避免人剛好被切在中線
                tile = np.ascontiguousarray(im[:, xs: xs + half_w])
                for (a, b, cc, d, s) in net.people(tile):
                    hdeg = (d - b) / 3.0
                    if hdeg < 4:
                        continue
                    c = max(c, s); n_ = max(n_, float(np.clip((hdeg - 15) / 40, 0, 1)) * min(1.0, s / 0.5))
            ts.append(i / fps); conf.append(c); near.append(n_); i += 1
    finally:
        p.stdout.close(); p.wait()
    return np.array(ts), np.array(conf, np.float32), np.array(near, np.float32)


def tilt_series(path, times):
    """R53：每個取樣時間的 (pitch, roll) 度數（IMU 重力方向；pitch＝鏡頭朝天/朝地多少）。沒有 IMU → None。"""
    imu = read_imu(path)
    if not imu or not len(times):
        return None
    t, acc = imu["t"], imu["acc"]
    k = 200
    a = np.stack([np.convolve(acc[:, j], np.ones(k) / k, mode="valid") for j in range(3)], 1)
    tt = t[k // 2: k // 2 + len(a)]
    if len(tt) < 2:
        return None
    ax, ay, az = (np.interp(times, tt, a[:, j]) for j in range(3))
    g = np.sqrt(ax ** 2 + ay ** 2 + az ** 2) + 1e-6
    pitch = np.degrees(np.arcsin(np.clip(az / g, -1, 1)))
    roll = np.degrees(np.arctan2(ax, ay))
    return pitch.astype(np.float32), roll.astype(np.float32)
