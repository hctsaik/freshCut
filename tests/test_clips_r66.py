"""R66：7 策略候選（uniform/loud/scene 新產生器、top-N+NMS、總數上限）＋片段匯出（檔名規則、無音軌、取消安全）。
對應 SPEC 驗收 #1 #2 #3 #4 的核心部分（GUI 部分見 test_clips_gui.py）。"""
import os, sys, tempfile, subprocess, glob, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from app import core


class F: pass


def feats(T=80, seed=1, audio=True):
    r = np.random.RandomState(seed); f = F(); f.times = np.arange(T) * 0.5
    for a in ("person", "near", "shake", "motion", "sharp", "peak"):
        setattr(f, a, r.rand(T) * 0.2)
    f.audio = r.rand(T) * 0.05 if audio else np.zeros(T)
    f.score = r.rand(T); f.focus_x = np.full(T, .5); f.focus_y = np.full(T, .5)
    f.thumbs = np.tile(r.rand(1, 9, 16, 3) * 0.2 + 0.4, (T, 1, 1, 1)) + r.rand(T, 9, 16, 3) * 0.01
    return f


ONLY = lambda k, **kw: {s: dict(on=(s == k), **(kw if s == k else {})) for s in core.STRAT_PER}
D = 40.0
# ---- 設定合併與範圍
P = core.strategy_config({"action": {"n": 99, "len": 1}, "middle": {"on": True}})
assert P["action"]["n"] == 5 and P["action"]["len"] == 3.0 and P["uniform"]["on"], P
assert [k for k, v in core.strategy_config().items() if v["on"]] == ["start", "people", "action", "whole", "uniform"]
assert core.strat_key("middle") == "uniform" and core.STRAT_NAMES["action"] == "精彩動作"

# ---- uniform：N=1 在 45%，N=3 在 (i+.5)/N
f = feats()
w = core.strategy_windows(f, D, core.strategy_config(ONLY("uniform", n=1, len=5)))
assert w == [("uniform", 15.5, 20.5, 0)], w
w = core.strategy_windows(f, D, core.strategy_config(ONLY("uniform", n=3, len=4)))
assert [round((s + e) / 2, 2) for _, s, e, _ in w] == [6.67, 20.0, 33.33] or \
       [round((s + e) / 2, 1) for _, s, e, _ in w] == [6.7, 20.0, 33.3], w

# ---- loud：最大聲處在窗口 40%；沒有聲音就不產生
f = feats(); f.audio[30] = 1.0; f.audio[29] = f.audio[31] = 0.6; f.audio[60] = 0.8; f.audio[59] = f.audio[61] = 0.5
w = core.strategy_windows(f, D, core.strategy_config(ONLY("loud", n=2, len=5)))
assert len(w) == 2 and w[0][0] == "loud", w
assert abs((15.0 - w[0][1]) / 5 - 0.4) < 0.05 and abs((30.0 - w[1][1]) / 5 - 0.4) < 0.05, w
assert core.strategy_windows(feats(audio=False), D, core.strategy_config(ONLY("loud"))) == []
c = core.strategy_candidates(feats(audio=False), "x.mp4", D, cfg=ONLY("loud"))
assert len(c) == 0, "沒有聲音：音量高峰 0 段"

# ---- scene：在換景點 +0.5 秒開始；只有雜訊時不產生
f = feats()
for t0, col in ((24, 0.9), (50, 0.05), (66, 0.6)):
    f.thumbs[t0:] = col
ch = core.scene_changes(f)
assert sorted(round(t, 1) for t, _ in ch) == [12.0, 25.0, 33.0], ch
w = core.strategy_windows(f, D, core.strategy_config(ONLY("scene", n=2, len=4)))
assert [x[1] for x in w] == [25.5, 33.5], w           # 變化最大的兩個（0.9→0.05、0.05→0.6）
assert core.scene_changes(feats()) == [], "只有小雜訊不算換景"

# ---- people/action top-N + NMS（彼此 IoU < 0.3）
f = feats(); f.motion[10:20] = 1; f.peak[10:20] = 1; f.motion[50:60] = 0.9; f.peak[50:60] = 0.9
w = core.strategy_windows(f, D, core.strategy_config(ONLY("action", n=3)))
assert len(w) == 3 and all(core._iou(a[1:3], b[1:3]) < 0.3 for i, a in enumerate(w) for b in w[i + 1:]), w
assert 3 <= w[0][1] <= 6 and 23 <= w[1][1] <= 26, w

# ---- 驗收 #1（核心）：只開精彩動作 n=2 → 每支 ≤2 段、只有 action 標籤
for seed in range(5):
    c = core.strategy_candidates(feats(seed=seed), "v.mp4", D, cfg=ONLY("action", n=2))
    assert 1 <= len(c) <= 2 and all(s.strategies == ["action"] for s in c), [s.strategies for s in c]

# ---- 驗收 #2（核心）：同一段同時是 people+action → 1 段 2 個標籤
f = feats(); f.person[20:33] = 1; f.near[20:33] = 1; f.motion[20:33] = 1; f.peak[20:33] = 1
c = core.strategy_candidates(f, "v.mp4", D, cfg={"start": {"on": False}, "whole": {"on": False}, "uniform": {"on": False}, "action": {"n": 1}})
assert len(c) == 1 and sorted(c[0].strategies) == ["action", "people"], [(s.start, s.strategies) for s in c]

# ---- 每支總數 ≤ 12；關掉的策略不會出現在任何標籤
allon = {k: dict(on=True, n=core.STRAT_RANGE[k][1][1]) for k in core.STRAT_PER}
f = feats(T=400); f.audio = np.random.RandomState(3).rand(400)
for t0 in range(20, 400, 40):
    f.thumbs[t0:] = (t0 % 80) / 100 + 0.1
c = core.strategy_candidates(f, "v.mp4", 200.0, cfg=allon)
assert len(c) == 12 and len({k for s in c for k in s.strategies}) >= 4, len(c)
off = dict(allon); off["people"] = {"on": False}; off["start"] = {"on": False}
c = core.strategy_candidates(f, "v.mp4", 200.0, cfg=off)
assert not any(k in ("people", "start") for s in c for k in s.strategies)
# 舊 API enabled=[…] 仍可用；舊的 middle 視為 uniform
c = core.strategy_candidates(feats(), "v.mp4", D, enabled=["middle"])
assert c and all(s.strategies == ["uniform"] for s in c)

# ---- 檔名規則
src = "/x/VID_20240825_023257_349.mp4"
assert core.clip_filename(src, 1, 2, ["people", "action"], pattern="seq", seq=3) == "VID_20240825_023257_349_AI人物_03.mp4"
assert core.clip_filename(src, 1, 2, ["whole"], pattern="seq") == "VID_20240825_023257_349_整支_01.mp4"
assert core.clip_filename(src, 1, 2, None, pattern="seq") == "VID_20240825_023257_349_手動_01.mp4"
assert core.clip_filename(src, 1, 2, ["loud"], pattern="seq", ascii_only=True) == "VID_20240825_023257_349_loud_01.mp4"
assert core.clip_filename(src, 1, 2, ["scene"], pattern="date", seq=7) == "20240825_07.mp4"
assert core.clip_filename("/x/海邊:日落?.mp4", 1, 2, ["scene"], pattern="seq") == "海邊_日落__場景變換_01.mp4"
assert core.clip_filename("/x/海邊.mp4", 1, 2, ["scene"], pattern="seq", ascii_only=True) == "___scene_01.mp4"
S = core.Segment
items = [(S("/a/A.mp4", 9, 12, 1), ["action"]), (S("/a/A.mp4", 1, 3, 1), ["action", "people"]),
         (S("/a/A.mp4", 5, 7, 1), ["people"]), (S("/a/B.mp4", 0, 2, 1), None)]
co = core.ClipOptions()
assert core.plan_clip_names(items, co) == [os.path.join("A", "A_精彩動作_02.mp4"), os.path.join("A", "A_精彩動作_01.mp4"),
                                           os.path.join("A", "A_AI人物_01.mp4"), os.path.join("B", "B_手動_01.mp4")]
co.subfolders = False; co.fmt = "prores"
assert core.plan_clip_names(items, co)[3] == "B_手動_01.mov"

# ---- 實際輸出（驗收 #3）
ff = core.find_ffmpeg(); d = tempfile.mkdtemp()
srcs = []
for k in range(3):
    p = os.path.join(d, f"VID_2024082{k}_10000{k}_00{k}.mp4"); srcs.append(p)
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:d=12:r=30", "-f", "lavfi", "-i",
                    "sine=f=440:d=12", "-shortest", "-pix_fmt", "yuv420p", p], check=True)


def streams(p):
    r = subprocess.run([ff, "-hide_banner", "-i", p], capture_output=True, text=True).stderr
    return ("Video:" in r), ("Audio:" in r)


strs = [["start"], ["action", "people"], ["loud"]]
items = [(S(p, a, a + L, 1), strs[j]) for p in srcs for j, (a, L) in enumerate(((0, 3.0), (4.2, 2.5), (8.1, 3.3)))]
assert len(items) == 9
out = os.path.join(d, "out")
co = core.ClipOptions(audio=False)
prog = []
res = core.export_clips(items, out, co, progress=lambda f, m: prog.append((f, m)))
files = [p for p, e in res]
assert all(files) and len(set(files)) == 9 and len(glob.glob(os.path.join(out, "*", "*.mp4"))) == 9, res
assert os.path.basename(files[1]) == os.path.basename(srcs[0])[:-4] + "_精彩動作_01.mp4", files[1]
assert all(os.path.dirname(p).endswith(os.path.basename(s)[:-4]) for (p, _), (sg, _) in zip(res, items) for s in [sg.path])
for p, (sg, _) in zip(files, items):
    v, a = streams(p)
    assert v and not a, ("關掉聲音時不可有音軌", p)
    du = core.probe(p).duration
    assert abs(du - (sg.end - sg.start)) <= 0.1, (p, du, sg.end - sg.start)
assert prog[-1][0] == 1.0 and any(m == "5/9" for _, m in prog)
# 保留聲音：有原聲、沒有別的音樂（單一音軌、440 Hz 正弦）
res = core.export_clips(items[:1], out, core.ClipOptions(audio=True, subfolders=False))
assert streams(res[0][0]) == (True, True) and core.probe(res[0][0]).duration == core.probe(res[0][0]).duration
assert abs(core.probe(res[0][0]).duration - 3.0) <= 0.1
# HEVC / ProRes、9:16 重新構圖、720p
for o in (core.ClipOptions(fmt="hevc", subfolders=False), core.ClipOptions(fmt="prores", subfolders=False),
          core.ClipOptions(aspect="9:16", resolution="720p", audio=False, subfolders=False)):
    p, e = core.export_clips(items[:1], os.path.join(d, "fmt"), o)[0]
    assert p and not e, e
    info = core.probe(p)
    assert abs(info.duration - 3.0) <= 0.1, (o, info.duration)
    if o.aspect == "9:16":
        assert (info.width, info.height) == (720, 1280) and streams(p) == (True, False), (info.width, info.height)
    if o.fmt == "prores":
        assert p.endswith(".mov")
# 同名不覆寫 → _2；覆寫 → 取代
p0 = core.export_clips(items[:1], os.path.join(d, "dup"), core.ClipOptions(subfolders=False))[0][0]
p1 = core.export_clips(items[:1], os.path.join(d, "dup"), core.ClipOptions(subfolders=False))[0][0]
assert p1.endswith("_2.mp4") and os.path.exists(p0)

# ---- 驗收 #4：中途取消 → 已完成的保留、不留 .part、原本就存在的同名檔絕不刪
for overwrite in (False, True):
    cd = os.path.join(d, f"cancel{int(overwrite)}")
    co = core.ClipOptions(subfolders=False, overwrite=overwrite)
    names = core.plan_clip_names(items[:4], co)
    os.makedirs(cd, exist_ok=True)
    pre = {}
    for n in names:     # 每個目標檔名都先放一個「使用者原本的檔案」
        with open(os.path.join(cd, n), "wb") as fh:
            fh.write(b"ORIGINAL " + n.encode())
        pre[n] = b"ORIGINAL " + n.encode()
    # 在第 3 段編碼「途中」取消（進度回呼看到 3/4 之後才回傳 True）
    state = {"go": False}

    def prog(f, m):
        if m == "3/4" and f > 0.5 + 0.01:
            state["go"] = True
    try:
        core.export_clips(items[:4], cd, co, progress=prog, cancel=lambda: state["go"]); raise SystemExit("沒有取消")
    except core.Cancelled:
        pass
    left = sorted(os.listdir(cd))
    assert not [x for x in left if ".part" in x], left
    for n, b in pre.items():
        if overwrite and n in names[:2]:
            assert open(os.path.join(cd, n), "rb").read() != b, "覆寫模式：已完成的段取代舊檔"
        else:
            assert open(os.path.join(cd, n), "rb").read() == b, ("舊檔被動到", n)
    done = [x for x in left if x not in pre]
    assert (len(done) == 0) if overwrite else (len(done) == 2), (overwrite, left)
    for x in done:
        assert core.probe(os.path.join(cd, x)).duration > 1
# 單段失敗（例如來源不見）不影響其他段，也不刪舊檔
cd = os.path.join(d, "fail"); os.makedirs(cd)
bad = (S(os.path.join(d, "nope.mp4"), 0, 2, 1), ["action"])
n = core.plan_clip_names([bad], core.ClipOptions(subfolders=False, overwrite=True))[0]
open(os.path.join(cd, n), "wb").write(b"KEEP")
res = core.export_clips([bad, items[0]], cd, core.ClipOptions(subfolders=False, overwrite=True))
assert res[0][0] is None and res[0][1] and res[1][0] and open(os.path.join(cd, n), "rb").read() == b"KEEP"
assert not glob.glob(os.path.join(cd, "*.part*"))
print("test_clips_r66 OK")
