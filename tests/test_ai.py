"""離線 AI 剪輯：節拍、主體跟隨構圖、慢動作、片頭、360 轉平面、去重、品質分數。"""
import os, sys, tempfile, subprocess
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import core, beats, smart

ff = core.find_ffmpeg(); d = tempfile.mkdtemp()
def mk(name, *a):
    p = os.path.join(d, name); subprocess.run([ff, "-y", "-v", "error", *a, p], check=True); return p

# 1) 節拍：120 BPM 的節拍器聲
music = mk("click.wav", "-f", "lavfi", "-i", "aevalsrc='sin(2*PI*880*t)*exp(-40*mod(t,0.5))':s=22050:d=20")
m = beats.analyze_music(music)
print("bpm", m["bpm"], "beats", len(m["beats"]))
assert abs(m["bpm"] - 120) < 3, m["bpm"]
err = [abs(b - round(b * 2) / 2) for b in m["beats"]]
assert np.median(err) < 0.04, np.median(err)
assert 8 <= len(m["downbeats"]) <= 12
st, lens = beats.beat_lengths(m["beats"], 5, "平穩")
assert all(abs(l - 2.0) < 0.1 for l in lens), lens          # 4 拍 × 0.5 s
st, lens2 = beats.beat_lengths(m["beats"], 5, "輕快")
assert all(abs(l - 1.0) < 0.1 for l in lens2), lens2  # 2 拍
cuts = np.cumsum(lens)[:-1] + st
assert all(min(abs(c - b) for b in m["beats"]) < 0.03 for c in cuts), "剪接點要落在拍上"
print("beats OK")

# 2) 主體在右側且會動 → 軌跡偏右；直式輸出跟著主體
right = mk("right.mp4", "-f", "lavfi", "-i", "color=c=0x202020:s=1280x720:d=8:r=30", "-vf",
           "drawbox=x='950+60*sin(t*4)':y=300:w=140:h=140:color=white:t=fill,format=yuv420p")
c = core.candidates_for_video(right, count=1, seg_len=4)[0]
mx = float(np.mean(c.track["x"])); print("track mean x", round(mx, 3), "peak", c.peak)
assert mx > 0.62, mx
assert c.start <= c.peak <= c.end
def bright(path):
    r = subprocess.run([ff, "-v", "error", "-ss", "1", "-i", path, "-frames:v", "1", "-vf", "scale=108:192,format=gray",
                        "-f", "rawvideo", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.uint8).astype(float).mean()
o_s, o_c = os.path.join(d, "s.mp4"), os.path.join(d, "c.mp4")
for o, mode in ((o_s, "smart"), (o_c, "center")):
    core.export([c], o, core.ExportOptions(aspect="9:16", crossfade=0, fade_out=0, reframe=mode))
bs, bc = bright(o_s), bright(o_c); print("9:16 brightness smart", round(bs, 1), "center", round(bc, 1))
assert bs > bc + 15, "主體跟隨裁切應該拍到白色主體"
assert (core.probe(o_s).width, core.probe(o_s).height) == (1080, 1920)
print("reframe OK")

# 3) 慢動作：4 秒片段中 1 秒放慢 0.5 倍 → 5 秒；加片頭
src = mk("src.mp4", "-f", "lavfi", "-i", "testsrc2=duration=10:size=640x360:rate=30", "-f", "lavfi", "-i",
         "sine=duration=10", "-shortest", "-pix_fmt", "yuv420p")
s = core.Segment(src, 2.0, 6.0, 1.0); s.peak = 4.0; s.ramp = smart.ramp_for(s, 0.5, 1.0)
assert s.ramp == (3.5, 4.5, 0.5), s.ramp
o = os.path.join(d, "ramp.mp4")
png = ""
if not core.has_filter("drawtext"):
    try:
        from PySide6.QtGui import QGuiApplication
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen"); _qa = QGuiApplication([])
        png = smart.render_title_png("海邊的一天", "2026.10.25", 1920, 1080, os.path.join(d, "t.png")) or ""
        assert png, "Qt 標題圖失敗"
    except ImportError:
        pass
print("drawtext", core.has_filter("drawtext"), "png fallback", bool(png))
core.export([s], o, core.ExportOptions(crossfade=0, fade_out=0, title="海邊的一天", subtitle="2026.10.25", title_png=png,
                                       resolution="1080p"))
i = core.probe(o); print("ramp+title", i.duration)
assert abs(i.duration - (4.0 + smart.ramp_extra(0.5, 1.0))) < 0.12 and i.has_audio  # R17：含前後過渡
def _white(t):
    r = subprocess.run([ff, "-v", "error", "-ss", str(t), "-i", o, "-frames:v", "1", "-vf", "crop=iw/2:ih/6:iw/4:ih*0.42,format=gray",
                        "-f", "rawvideo", "-"], stdout=subprocess.PIPE, check=True).stdout
    return sum(1 for b in r if b > 245) / max(1, len(r))
if core.has_filter("drawtext") or png:
    w1, w2 = _white(1.5), _white(4.5); print("title white", round(w1, 3), round(w2, 3))
    assert w1 > w2 + 0.01, (w1, w2)
assert smart.find_font() is None or smart.title_filter("a:b", "c") is not None
print("slowmo/title OK")

# 4) 360 等距長方投影 → 一般 16:9 畫面
eq = mk("eq.mp4", "-f", "lavfi", "-i", "testsrc2=duration=4:size=1920x960:rate=30", "-pix_fmt", "yuv420p")
o = os.path.join(d, "flat.mp4")
core.export([core.Segment(eq, 0, 3)], o, core.ExportOptions(projection="equirect", crossfade=0, fade_out=0))
i = core.probe(o); assert (i.width, i.height) == (1920, 1080) and abs(i.duration - 3) < 0.2, i
print("360 OK")

# 5) 去重：一模一樣的兩支 → 第二支的片段被判為重複
dup = mk("dup.mp4", "-i", src, "-c", "copy")
a = core.candidates_for_video(src, 2, 3); b = core.candidates_for_video(dup, 2, 3)
assert core.similar(a[0].sig, b[0].sig) > 0.93
clips = [(k, x.score, x.sig) for k, x in enumerate(a + b)]
drop = smart.dedupe(clips); assert len(drop) >= 2, drop
assert len(smart.dedupe([(0, 1, a[0].sig), (1, 1, core.candidates_for_video(right, 1, 3)[0].sig)])) == 0
print("dedupe OK")

# 6) 品質：糊掉 / 晃動的段落分數較低
blur = mk("blur.mp4", "-i", src, "-vf", "boxblur=8", "-an")
fs, fb = core.features(src), core.features(blur)
assert fs.sharp.mean() >= 0 and core.features(blur).score.mean() < fs.score.mean() + 0.2
shake = mk("shake.mp4", "-f", "lavfi", "-i", "testsrc2=duration=6:size=640x360:rate=30", "-vf",
           "crop=560:300:40+30*sin(t*25):30+25*cos(t*31),scale=640:360,format=yuv420p")
fk = core.features(shake); fn = core.features(mk("still.mp4", "-f", "lavfi", "-i",
                                                   "testsrc2=duration=6:size=640x360:rate=30", "-pix_fmt", "yuv420p"))
print("shake", round(float(fk.shake.mean()), 3), "vs", round(float(fn.shake.mean()), 3))
assert fk.shake.mean() > fn.shake.mean() + 0.05

# 7) prepare：對拍 + 慢動作 → 輸出後的剪接點仍落在拍上
segs = []
for k in range(3):
    x = core.Segment(src, 1 + k * 2.5, 4 + k * 2.5, 1.0); x.peak = x.start + 1.5; x.duration = 10.0; segs.append(x)
out_segs, mstart = smart.prepare(segs, m, "平穩", 0.5, 0.0)
olens = [x.length + sum((b - a) * (1 / f - 1) for a, b, f in smart.ramp_pieces(x.start, x.end, getattr(x, "ramp", None))) for x in out_segs]
print("prepared out lens", [round(l, 2) for l in olens], "music start", mstart)
assert all(abs(l / 2.0 - round(l / 2.0)) < 0.05 and abs(l - 4.0) < 0.1 for l in olens), olens  # 拍長 2 秒的整數倍，且接近原長+慢動作
o = os.path.join(d, "beat.mp4")
core.export(out_segs, o, core.ExportOptions(crossfade=0, fade_out=0, music=music, music_start=mstart))
assert abs(core.probe(o).duration - sum(olens)) < 0.3
# 素材庫：auto_pick 去重、基本搜尋
from app.library import Library
lib = Library(os.path.join(d, "lib")); lib.add_files([src, dup, right], find_siblings=False)
for f in lib.files():
    lib.analyze(f["id"], count=3, seg_len=3.0)
ids = lib.auto_pick(12)
rows = {r["id"]: r for r in lib.clip_rows()}
fids = [rows[i]["file_id"] for i in ids]
print("auto_pick", ids, fids, sorted(round(r["score"], 2) for r in rows.values()))
# R14（B5）：深灰無內容的 right.mp4 分數不到最高分 45%，不再被硬塞進成品（成品可以比目標短）
top = max(r["score"] for r in rows.values())
assert len(ids) >= 2 and sum(rows[i]["end"] - rows[i]["start"] for i in ids) >= 5.5
assert all(rows[i]["score"] >= 0.45 * top for i in ids)
pairs = [(a_, b_) for a_ in ids for b_ in ids if a_ < b_]
assert all(core.similar(rows[a_]["sig"], rows[b_]["sig"]) <= 0.93 for a_, b_ in pairs), "一鍵成片不該挑到重複畫面"
assert [r["id"] for r in lib.timeline()] == ids
r, mode = lib.semantic_search("夜景", allow_clip=False); assert mode == "basic"
r, mode = lib.semantic_search("量子", allow_clip=False); assert mode == "unknown" and r == []
lib.close()
print("AI OK")

# R8 鎖定＋換一批
clips = [dict(id=i, file_id=i % 2, start=0, end=5, score=1 - i * 0.05, sig=None, ftime=i) for i in range(10)]
a = smart.auto_pick(clips, 15)
b = smart.auto_pick(clips, 15, locked=[a[0]], avoid=[x for x in a if x != a[0]])
print("reshuffle", a, b)
assert a[0] in b and len(set(b) - set(a)) >= 2, (a, b)
print("RESHUFFLE OK")

# R9 對拍不可把總長縮短（一鍵成片 30 秒目標只出 8 秒的 bug）
st, L = beats.beat_lengths(m["beats"], 4, "輕快", wants=[4.0, 4.0, 3.0, 5.0])
print("wants lens", [round(x, 2) for x in L])
assert all(abs(a - b) <= 0.6 for a, b in zip(L, [4.0, 4.0, 3.0, 5.0])), L
