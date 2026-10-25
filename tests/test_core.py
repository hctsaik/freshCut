import os, sys, tempfile, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import core

d = tempfile.mkdtemp()
ff = core.find_ffmpeg()
def gen(name, src, dur, size, audio=True, ext="mp4"):
    p = os.path.join(d, f"{name}.{ext}")
    a = ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}"] if audio else []
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"{src}=duration={dur}:size={size}:rate=30",
                    *a, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", "-f", "mp4", p], check=True)
    return p
v1 = gen("a", "testsrc2", 12, "1920x1080")
v2 = gen("b", "rgbtestsrc", 10, "1280x720", audio=False, ext="mov")
v3 = gen("c", "testsrc", 8, "1080x1920", ext="LRV")
music = os.path.join(d, "m.mp3")
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=5", music], check=True)
for v in (v1, v2, v3):
    print(core.probe(v))
segs = core.suggest_segments([v1, v2, v3], target_total=12, seg_len=3)
print("suggested", [(os.path.basename(s.path), s.start, s.end, round(s.score, 2)) for s in segs])
assert segs
for aspect in ("16:9", "9:16", "1:1"):
    out = os.path.join(d, f"out_{aspect.replace(':','x')}.mp4")
    o = core.ExportOptions(aspect=aspect, music=music if aspect != "1:1" else "",
                           keep_original_audio=aspect != "9:16", crossfade=0.5 if aspect != "1:1" else 0)
    core.export(segs, out, o, progress=lambda f, m: None)
    info = core.probe(out)
    print(aspect, info)
    assert info.has_audio and abs(info.duration - sum(s.length for s in segs)) < 3
print("ALL OK", d)
# 自動流程：每支影片候選 -> 勾選 -> 產生成品
cands = []
for v in (v1, v2, v3):
    c = core.candidates_for_video(v, count=4, seg_len=2.5)
    assert 1 <= len(c) <= 4, c
    assert core.thumbnail(v, c[0].start, os.path.join(d, "t.png"))
    cands += c[:2]
mdir = os.path.dirname(music)
assert core.list_music(mdir)
out = os.path.join(d, "final.mp4")
core.export(cands, out, core.ExportOptions(music=core.list_music(mdir)[0]))
print("final", core.probe(out)); print("FLOW OK")


def test_run_cancel():
    import threading, time
    ff = core.find_ffmpeg(); flag = [False]
    core.set_cancel(lambda: flag[0])
    threading.Timer(0.5, lambda: flag.__setitem__(0, True)).start()
    t = time.time()
    try:
        core._run([ff, "-v", "error", "-re", "-f", "lavfi", "-i", "testsrc2=duration=60", "-f", "null", "-"])
        raise AssertionError("沒有被取消")
    except core.Cancelled:
        pass
    finally:
        core.set_cancel(None)
    assert time.time() - t < 2.0
    r = core._run([ff, "-version"]); assert r.returncode == 0   # 未設定時照舊
    print("run cancel OK")


test_run_cancel()
