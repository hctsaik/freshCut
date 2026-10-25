"""R51–R55：跨檔案的「這支值不值得留」排序（依 Thai 真實挑選資料調，見 review/ROUNDS.md R51+）。

file_worth（core）只看單支影片；這裡再做：
- 長度加權：< 3 秒幾乎不留（真實資料 15 支只留 1 支），10 秒以上最常留。
- 跨檔正規化（R55）：每支影片最佳段分數換成全媒體庫百分位，不同場景/亮度/音量的影片才能互相比。
- 連拍群組（相鄰兩支間隔 > BURST_GAP 秒就是新的一組）：同組只有最好的一支保持原分，其餘扣分（一組一支）。
- 近乎重複：同組內小圖很像較好那支的再扣分。
"""
import os, re, datetime
import numpy as np

BURST_GAP = float(os.environ.get("IE_BURST_GAP", 180))
RW = dict(len=1.0, short=1.0, q=0.3, person=0.4, burst=0.2, dup=0.3, dup_t=0.8, keep=0.3, bad=0.2)
RANK_MIN = 5
NORM = os.environ.get("IE_RANK_NORM", "pct")   # pct：跨檔百分位；raw：不正規化


def _ts(item):
    if item.get("time") is not None:
        return float(item["time"])
    m = re.search(r"(\d{8})_(\d{6})", os.path.basename(str(item.get("path", ""))))
    if m:
        try:
            return datetime.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").timestamp()
        except ValueError:
            pass
    return None


def length_weight(d):
    """0（< 3 s 給負分）… 1（≥ 20 s）。"""
    if d < 3:
        return -1.0
    return float(np.clip(np.log(d / 3) / np.log(20 / 3), 0, 1))


def _pct(v):
    v = np.asarray(v, float)
    if len(v) < 2:
        return np.full(len(v), 0.5)
    return (np.argsort(np.argsort(v)) + 0.5) / len(v)


def bursts(items, gap=None):
    gap = BURST_GAP if gap is None else gap
    order = sorted(range(len(items)), key=lambda i: (_ts(items[i]) is None, _ts(items[i]) or 0, str(items[i].get("path"))))
    b, last, out = -1, None, [0] * len(items)
    for i in order:
        t = _ts(items[i])
        if t is None or last is None or t - last > gap:
            b += 1
        out[i] = b; last = t if t is not None else last
    return out


def rank_files(items, rw=None):
    """items：list of dict(path, worth, duration, sig[, person, time])。就地寫入 worth_n（越高越值得）、keep、burst。"""
    from .core import similar
    P = dict(RW, **(rw or {}))
    if not items:
        return items
    wv = np.array([float(it.get("worth", 0.0)) for it in items])
    q = _pct(wv) if NORM == "pct" else wv                               # R54：跨檔百分位
    per = np.array([float(it.get("person", 0.0)) for it in items])
    bad = np.array([float(it.get("bad", 0.0)) for it in items])
    base = []
    for it, qq, pp in zip(items, q, per):
        lw = length_weight(float(it.get("duration", 0.0)))
        v = P["len"] * lw if lw >= 0 else -P["short"]
        base.append(v + P["q"] * qq + P["person"] * pp)
    base = np.array(base) - P["bad"] * bad
    B = bursts(items)
    worth = base.copy()
    for b in set(B):
        idx = sorted([i for i in range(len(items)) if B[i] == b], key=lambda i: -base[i])
        for r, i in enumerate(idx):
            if r == 0:
                continue
            worth[i] -= P["burst"]
            s_i = items[i].get("sig")
            if s_i is not None and any(items[j].get("sig") is not None and similar(s_i, items[j]["sig"]) > P["dup_t"]
                                       for j in idx[:r]):
                worth[i] -= P["dup"]
    for it, w, b in zip(items, worth, B):
        it["worth_n"] = float(w); it["burst"] = b; it["keep"] = bool(w >= P["keep"])
    return items
