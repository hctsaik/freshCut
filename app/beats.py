"""離線節拍偵測（只用 numpy + ffmpeg 解碼）：頻譜通量 onset → 自相關估 BPM → 動態規劃追拍 → 重拍。"""
import numpy as np
from . import core

SR, HOP, NFFT = 22050, 512, 2048


def _decode(path, max_s=600):
    r = core._run([core.find_ffmpeg(), "-v", "error", "-t", str(max_s), "-i", path, "-vn", "-ac", "1",
                   "-ar", str(SR), "-f", "f32le", "-"])
    return np.frombuffer(r.stdout, np.float32)


def onset_envelope(y):
    if len(y) < NFFT:
        return np.zeros(1)
    n = 1 + (len(y) - NFFT) // HOP
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    S = np.abs(np.fft.rfft(y[idx] * np.hanning(NFFT), axis=1))
    S = np.log1p(100 * S)
    flux = np.clip(np.diff(S, axis=0), 0, None).sum(1)
    flux = np.concatenate([[0], flux])
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")
    flux = np.clip(flux, 0, None)
    return flux / (flux.max() + 1e-9)


def tempo(env, lo=70, hi=180):
    fps = SR / HOP
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    lags = np.arange(len(ac))
    bpm = np.where(lags > 0, 60 * fps / np.maximum(lags, 1), 0)
    w = np.exp(-0.5 * (np.log2(np.maximum(bpm, 1) / 120) / 0.9) ** 2)   # 偏好 ~120 BPM 附近
    ok = (bpm >= lo) & (bpm <= hi)
    if not ok.any():
        return 120.0
    v = ac * w
    lag = int(lags[ok][np.argmax(v[ok])])
    if 1 <= lag < len(v) - 1:                      # 拋物線內插取得小數 lag
        a, b, c = v[lag - 1], v[lag], v[lag + 1]
        den = a - 2 * b + c
        lag = lag + (0.5 * (a - c) / den if den else 0)
    return float(60 * fps / lag)


def track(env, bpm, tight=100.0):
    """Ellis 2007 動態規劃追拍，回傳拍點的 frame index。"""
    fps = SR / HOP
    period = 60 * fps / bpm
    n = len(env)
    score = env.copy(); back = -np.ones(n, int)
    lo, hi = int(round(period / 2)), int(round(period * 2))
    for i in range(n):
        a, b = max(0, i - hi), i - lo
        if b <= a:
            continue
        prev = np.arange(a, b)
        pen = -tight * np.log((i - prev) / period) ** 2
        j = np.argmax(score[prev] + pen)
        score[i] += score[prev[j]] + pen[j]; back[i] = prev[j]
    i = int(np.argmax(score[max(0, n - int(period * 2)):]) + max(0, n - int(period * 2)))
    out = []
    while i >= 0:
        out.append(i); i = back[i]
    return np.array(out[::-1])


def analyze_music(path):
    """回傳 dict(bpm, beats[秒], downbeats[秒])。"""
    y = _decode(path)
    env = onset_envelope(y)
    if env.max() <= 0:
        return {"bpm": 0.0, "beats": [], "downbeats": []}
    bpm = tempo(env)
    b = track(env, bpm)
    t = (b * HOP + NFFT / 2) / SR          # 視窗中心
    # 重拍：4 拍一小節，挑 onset 能量最強的相位
    ph = max(range(4), key=lambda k: env[b[k::4]].sum() if len(b[k::4]) else 0)
    return {"bpm": round(bpm, 1), "beats": [round(float(x), 3) for x in t],
            "downbeats": [round(float(x), 3) for x in t[ph::4]]}


PACING = {"輕快": 2, "平穩": 4, "史詩": 8}       # 每段幾拍


def beat_lengths(beats, n, style="平穩", min_len=0.9, crossfade=0.0, wants=None):
    """依節拍決定 n 段的長度，讓每個剪接點都落在拍點上。回傳 (起始偏移, [每段秒數])。
    有轉場時每段多留 crossfade 秒，扣掉重疊後剪接點仍在拍上。"""
    if len(beats) < 4 or n == 0:
        return 0.0, []
    period = float(np.median(np.diff(beats)))
    k = PACING.get(style, 4)
    while k > 1 and k * period > 6:          # 很慢的歌不要讓一段太長
        k //= 2
    while k * period < min_len:
        k *= 2
    start = beats[0]
    lens = []
    i = 0
    for j in range(n):
        # 每段用「節奏單位」的整數倍，最接近原本長度（不超過），整支片長才不會被對拍縮短
        m = max(1, int((wants[j] + 0.25 * k * period) // (k * period))) if wants else 1
        tgt = min(i + k * m, len(beats) - 1)
        if tgt <= i:                          # 歌不夠長就用平均拍長延伸
            lens.append(k * m * period)
        else:
            lens.append(beats[tgt] - beats[i]); i = tgt
    lens = [l + (crossfade if j < n - 1 else 0) for j, l in enumerate(lens)]
    return float(start), lens


def snap_segments(segs, lens, durations):
    """把每段改成指定長度，以精彩點(peak)為中心，不超出原影片。"""
    out = []
    for s, L, D in zip(segs, lens, durations):
        c = getattr(s, "peak", None) or (s.start + s.end) / 2
        a = max(0.0, min(c - L / 2, D - L)); b = min(D, a + L)
        n = core.Segment(s.path, round(a, 3), round(b, 3), s.score)
        for k in ("peak", "track", "sig", "ramp"):
            if hasattr(s, k):
                setattr(n, k, getattr(s, k))
        out.append(n)
    return out
