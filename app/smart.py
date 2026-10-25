"""離線 AI 剪輯：主體跟隨直式重新構圖、精彩點慢動作、風格範本、一鍵成片規劃、跨影片去重。"""
import json
import numpy as np
from . import core

TEMPLATES = {
    # 名稱: 節奏, 轉場秒, 每段預設秒數, 慢動作倍率(0=不用), 成品目標秒數
    "Vlog": {"pacing": "平穩", "crossfade": 0.4, "seg_len": 4.0, "slowmo": 0.0, "target": 60, "title": True},
    "運動": {"pacing": "輕快", "crossfade": 0.0, "seg_len": 3.0, "slowmo": 0.5, "target": 30, "title": False},
    "旅行": {"pacing": "史詩", "crossfade": 0.6, "seg_len": 5.0, "slowmo": 0.0, "target": 60, "title": True},
}


def load_track(raw):
    if not raw:
        return None
    t = json.loads(raw) if isinstance(raw, str) else raw
    return t if isinstance(t, dict) and t.get("x") else None


def fill_face_gaps(xs, conf, max_gap=4):
    """臉偶爾漏偵測時（max_gap 個取樣點內），用前後兩次有臉的位置內插，不要跳回動態重心。"""
    xs = list(xs)
    if not conf:
        return xs
    idx = [i for i, c in enumerate(conf[:len(xs)]) if c > 0]
    for a, b in zip(idx, idx[1:]):
        if 1 < b - a <= max_gap + 1:
            for i in range(a + 1, b):
                xs[i] = xs[a] + (xs[b] - xs[a]) * (i - a) / (b - a)
    return xs


def smooth_path(xs, alpha=0.25, max_step=0.06, dead=0.05, conf=None):
    """像攝影師推鏡：主體在中央 ±dead 的範圍內鏡頭不動（去抖動），超出才跟；
    EMA＋每步限速，再正反各跑一次抵消延遲。有臉的取樣點跟得比較快。"""
    xs = fill_face_gaps(xs, conf)

    def run(seq, cs):
        out, cur, tgt = [], None, None
        for x, c in zip(seq, cs):
            if cur is None:
                cur = tgt = float(np.median(seq[:5]))          # R17：起點用前幾點中位數，避免第一點雜訊造成整段漂移
            elif abs(x - tgt) > dead:
                tgt = x - dead * (1 if x > tgt else -1) * 0.5
            a = min(0.6, alpha * (1.6 if c > 0 else 1.0))
            cur += max(-max_step, min(max_step, a * (tgt - cur)))
            out.append(cur)
        return out
    cs = list(conf[:len(xs)]) + [0] * max(0, len(xs) - len(conf)) if conf else [0] * len(xs)
    f = run(xs, cs)
    b = run(xs[::-1], cs[::-1])[::-1]
    m = np.array([(p + q) / 2 for p, q in zip(f, b)], float)
    if len(m) >= 5:                                           # R17：零相位 5 點平滑，再壓掉殘餘抖動
        k = np.array([1, 2, 3, 2, 1], float) / 9
        m = np.convolve(np.pad(m, 2, mode="edge"), k, mode="valid")
    return [float(v) for v in m]


def crop_x_expr(track, seg_start, seg_len, keys=12):
    """回傳 ffmpeg crop 的 x 運算式（t 從 0 開始），主體水平中心隨時間線性內插。"""
    if not track:
        return "(iw-ow)/2"
    step, t0, xs = track["step"], track["t0"], smooth_path(track["x"], conf=track.get("c"))
    pts = []
    for i, x in enumerate(xs):
        t = t0 + i * step + step / 2 - seg_start
        if -step <= t <= seg_len + step:
            pts.append((round(t, 3), x))
    if not pts:
        return "(iw-ow)/2"
    if len(pts) > keys:                       # 抽樣成最多 keys 個關鍵點
        idx = np.linspace(0, len(pts) - 1, keys).round().astype(int)
        pts = [pts[i] for i in idx]
    e = f"{pts[-1][1]:.4f}"
    for (ta, xa), (tb, xb) in reversed(list(zip(pts, pts[1:]))):
        lerp = f"({xa:.4f}+({xb:.4f}-{xa:.4f})*(t-{ta:.3f})/{max(1e-3, tb - ta):.3f})"
        e = f"if(lt(t\\,{tb:.3f})\\,{lerp}\\,{e})"
    e = f"if(lt(t\\,{pts[0][0]:.3f})\\,{pts[0][1]:.4f}\\,{e})"
    return f"max(0\\,min(iw-ow\\,({e})*iw-ow/2))"


def ramp_for(seg, factor=0.5, width=1.0):
    """在精彩點附近 width 秒放慢 factor 倍，回傳 (a, b, factor)。"""
    p = getattr(seg, "peak", None)
    if not p or factor <= 0 or factor >= 1 or seg.length < width + 1.0:
        return None
    a = max(seg.start + 0.3, p - width / 2); b = min(seg.end - 0.3, a + width)
    return (round(a, 3), round(b, 3), factor) if b - a > 0.3 else None


EASE = 0.25   # R17：慢動作前後各 0.25 秒用中間速度過渡，不再一下子變速


def ramp_pieces(start, end, ramp):
    """把一段切成 [(a, b, 速度)]：1 → 中間 → factor → 中間 → 1。"""
    if not ramp:
        return [(start, end, 1.0)]
    a, b, f = ramp; m = round((1 + f) / 2, 3)
    ea, eb = max(start, a - EASE), min(end, b + EASE)
    out = [(start, ea, 1.0), (ea, a, m), (a, b, f), (b, eb, m), (eb, end, 1.0)]
    return [p for p in out if p[1] - p[0] > 0.05]


SPEED_MIN, SPEED_MAX = 0.25, 4.0
CURVE_U = (0.0, 0.25, 0.5, 0.75, 1.0)   # R26：手動速度曲線的 5 個控制點（片段內相對位置）
SPEED_PRESETS = {
    "無": None,
    "中段慢動作": [1.0, 1.0, 0.4, 1.0, 1.0],
    "蒙太奇（快→慢→快）": [2.0, 1.0, 0.5, 1.0, 2.0],
    "漸慢": [1.5, 1.0, 0.75, 0.5, 0.4],
    "快轉": [2.0, 2.0, 2.0, 2.0, 2.0],
}


def clamp_speed(v):
    return round(min(SPEED_MAX, max(SPEED_MIN, float(v))), 3)


def curve_speed(curve, u):
    """速度曲線（5 點，線性內插）在 u∈[0,1] 的速度。"""
    u = min(1.0, max(0.0, u))
    for i in range(len(CURVE_U) - 1):
        if u <= CURVE_U[i + 1]:
            f = (u - CURVE_U[i]) / (CURVE_U[i + 1] - CURVE_U[i])
            return curve[i] + (curve[i + 1] - curve[i]) * f
    return curve[-1]


def curve_pieces(start, end, curve, step=0.5):
    """把速度曲線離散成 [(a, b, 速度)]：每 step 秒（原始時間）一段，取中點速度並量化到 0.05；相鄰同速合併。"""
    L = end - start
    if not curve or L <= 0:
        return [(start, end, 1.0)]
    n = max(1, int(round(L / step)))
    out = []
    for k in range(n):
        a, b = start + L * k / n, start + L * (k + 1) / n
        sp = clamp_speed(round(curve_speed(curve, (k + 0.5) / n) / 0.05) * 0.05)
        if out and abs(out[-1][2] - sp) < 1e-6:
            out[-1] = (out[-1][0], b, sp)
        else:
            out.append((a, b, sp))
    return [(round(a, 3), round(b, 3), sp) for a, b, sp in out]


def curve_length(start, end, curve):
    """套用速度曲線後的輸出秒數。"""
    return sum((b - a) / sp for a, b, sp in curve_pieces(start, end, curve))


def atempo_chain(sp):
    """atempo 單一實例只接受 0.5–100；0.25 倍要串兩個 0.5。"""
    parts = []
    while sp < 0.5 - 1e-9:
        parts.append(0.5); sp /= 0.5
    parts.append(sp)
    return ",".join(f"atempo={x:.4g}" for x in parts if abs(x - 1) > 1e-9)


def ramp_extra(factor, width):
    """慢動作（含過渡）讓片段多出的秒數。"""
    if not (0 < factor < 1):
        return 0.0
    return (1.0 / factor - 1) * width + 2 * EASE * (2 / (1 + factor) - 1)


def dedupe(clips, thr=0.93):
    """clips: [(id, score, sig ndarray)]；回傳要取消勾選的近乎重複 id（保留分數高的）。"""
    keep, drop = [], []
    for cid, sc, sig in sorted(clips, key=lambda c: -c[1]):
        if sig is not None and any(core.similar(sig, k[2]) > thr for k in keep if k[2] is not None):
            drop.append(cid)
        else:
            keep.append((cid, sc, sig))
    return drop


def auto_pick(clips, target, per_file_min=1, locked=(), avoid=()):
    """一鍵成片的挑選：每支至少 1 段最佳，再依分數補到 target 秒，避開近乎重複，依拍攝時間排序。
    clips: dict 需有 id, file_id, start, end, score, sig(ndarray 或 None), ftime。
    locked：一定保留（「鎖定」的片段）；avoid：上一批的片段，分數打 5 折，讓「換一批」真的換掉。"""
    locked, avoid = set(locked), set(avoid)
    raw = {c["id"]: c["score"] for c in clips}
    clips = [dict(c, score=c["score"] * (0.5 if c["id"] in avoid else 1.0) + (10 if c["id"] in locked else 0))
             for c in clips]
    drop = set(dedupe([(c["id"], c["score"], c.get("sig")) for c in clips])) - locked
    top = max(raw.values() or [0])
    # B5：低於最高分 45% 的片段不進一鍵成片（除非鎖定，或整個媒體庫都沒有更好的）
    pool = [c for c in clips if c["id"] not in drop and (c["id"] in locked or raw[c["id"]] >= 0.45 * top)]
    chosen = [c for c in pool if c["id"] in locked]
    total = sum(c["end"] - c["start"] for c in chosen)
    best = {}
    for c in pool:
        if c["file_id"] not in best or c["score"] > best[c["file_id"]]["score"]:
            best[c["file_id"]] = c
    for c in sorted(best.values(), key=lambda c: -c["score"]):
        if c in chosen or any(x["file_id"] == c["file_id"] for x in chosen):
            continue
        if total >= target:
            break
        chosen.append(c); total += c["end"] - c["start"]
    for c in sorted(pool, key=lambda c: -c["score"]):
        if total >= target:
            break
        if c not in chosen:
            chosen.append(c); total += c["end"] - c["start"]
    chosen.sort(key=lambda c: (c.get("ftime") or 0, c["file_id"], c["start"]))
    return [c["id"] for c in chosen]


def find_font():
    import os
    for p in ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc",
              r"C:\Windows\Fonts\msjh.ttc", r"C:\Windows\Fonts\msyh.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        if os.path.exists(p):
            return p
    return None


def title_filter(text, sub="", dur=3.0, H=1080):
    """片頭標題（含日期副標），淡入淡出。找不到中文字型就不加。"""
    font = find_font()
    if not font or not text:
        return None
    esc = lambda s: s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\u2019").replace("%", "\\%")
    fp = font.replace("\\", "/").replace(":", "\\:")
    a = f"alpha='if(lt(t,0.5),t/0.5,if(lt(t,{dur - 0.5}),1,max(0,({dur}-t)/0.5)))'"
    fs = int(H * 0.07)
    f = (f"drawtext=fontfile='{fp}':text='{esc(text)}':fontsize={fs}:fontcolor=white:"
         f"borderw={max(2, fs // 18)}:bordercolor=black@0.6:x=(w-text_w)/2:y=h*0.42:{a}:enable='lt(t,{dur})'")
    if sub:
        f += (f",drawtext=fontfile='{fp}':text='{esc(sub)}':fontsize={fs // 2}:fontcolor=white:"
              f"borderw=2:bordercolor=black@0.6:x=(w-text_w)/2:y=h*0.42+{int(fs * 1.3)}:{a}:enable='lt(t,{dur})'")
    return f


def prepare(segs, beats_info=None, pacing="平穩", slowmo=0.0, crossfade=0.0, width=1.0):
    """輸出前的 AI 步驟：(1) 剪接點對齊音樂節拍 (2) 精彩點慢動作。回傳 (片段, 音樂起點秒)。
    慢動作會讓片段變長 extra 秒，所以對齊節拍時先把該段的原始長度扣掉 extra，輸出後剪接點仍在拍上。"""
    from . import beats as B
    start = 0.0
    extra = ramp_extra(slowmo, width)
    if beats_info and len(beats_info.get("beats", [])) >= 4 and segs:
        start, lens = B.beat_lengths(beats_info["beats"], len(segs), pacing, crossfade=crossfade,
                                    wants=[s.end - s.start + extra for s in segs])
        slow = [bool(extra) and l - extra >= width + 1.0 for l in lens]
        lens = [l - extra if f else l for l, f in zip(lens, slow)]
        segs = B.snap_segments(segs, lens, [getattr(s, "duration", None) or s.end for s in segs])
    else:
        slow = [bool(extra)] * len(segs)
    for s, f in zip(segs, slow):
        if f and not getattr(s, "curve", None):   # 手動速度曲線優先，不再自動加慢動作
            r = ramp_for(s, slowmo, width)
            if r:
                s.ramp = r
    return segs, start


STICKERS = ["❤️", "🌊", "⛰️", "❄️", "🌙", "😎", "📍", "✈️", "🐶", "⭐"]


def render_sticker_png(emoji, path, size=256):
    """用 Qt 把 emoji 畫成透明 PNG（系統沒有彩色 emoji 字型時會是單色字形）。"""
    try:
        from PySide6.QtGui import QImage, QPainter, QFont, QGuiApplication
        from PySide6.QtCore import Qt, QRect
        if QGuiApplication.instance() is None:
            return None
        img = QImage(size, size, QImage.Format_ARGB32); img.fill(Qt.transparent)
        p = QPainter(img); p.setRenderHint(QPainter.Antialiasing)
        f = QFont(); f.setFamilies(["Noto Color Emoji", "Apple Color Emoji", "Segoe UI Emoji"])
        f.setPixelSize(int(size * 0.8)); p.setFont(f)
        p.drawText(QRect(0, 0, size, size), Qt.AlignCenter, emoji); p.end()
        return path if img.save(path) else None
    except Exception:
        return None


def render_title_png(text, sub, W, H, path, style="經典"):
    """ffmpeg 沒有 drawtext 時的替代方案：用 Qt 畫一張透明 PNG（需要已有 QGuiApplication）。
    成功回傳 path，否則回傳 None（呼叫端就不加標題並提示使用者）。"""
    try:
        from PySide6.QtGui import QImage, QPainter, QFont, QColor, QPainterPath, QPen, QGuiApplication
        from PySide6.QtCore import Qt, QPointF
        if QGuiApplication.instance() is None:
            return None
        img = QImage(W, H, QImage.Format_ARGB32); img.fill(Qt.transparent)
        p = QPainter(img); p.setRenderHint(QPainter.Antialiasing)
        for txt, size, y in ((text, H * 0.07, H * 0.42), (sub, H * 0.035, H * 0.42 + H * 0.09)):
            if not txt:
                continue
            f = QFont(); f.setPixelSize(max(8, int(size))); f.setBold(True); p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(txt)
            x0 = (W - w) / 2
            path_ = QPainterPath(); path_.addText(QPointF(x0, y + size), f, txt)
            if style == "霓虹":                       # 外發光：多層半透明粗描邊
                for wd, a in ((size / 3, 40), (size / 6, 80), (size / 12, 160)):
                    p.setPen(QPen(QColor(0, 220, 255, a), wd, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)); p.drawPath(path_)
                p.fillPath(path_, QColor("#F0FFFF"))
            elif style == "標籤":                     # 黃底黑字膠帶
                pad = size * 0.25
                p.fillRect(int(x0 - pad), int(y + size * 0.1), int(w + 2 * pad), int(size * 1.15), QColor("#FFC400"))
                p.fillPath(path_, QColor("#111111"))
            elif style == "電影":                     # 上下黑邊＋細字距白字
                if size > H * 0.05:
                    p.fillRect(0, 0, W, int(H * 0.1), QColor(0, 0, 0, 230))
                    p.fillRect(0, int(H * 0.9), W, int(H * 0.1) + 1, QColor(0, 0, 0, 230))
                p.fillPath(path_, QColor("#F5F5F5"))
            else:
                p.setPen(QPen(QColor(0, 0, 0, 150), max(2, size / 18))); p.drawPath(path_)
                p.fillPath(path_, QColor("white"))
        p.end()
        return path if img.save(path) else None
    except Exception:
        return None
