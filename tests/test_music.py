import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import music, beats

d = tempfile.mkdtemp()
for mood, (bpm, *_r) in music.MOODS.items():
    p = music.ensure(d, mood, 30)
    m = beats.analyze_music(p)
    # 對拍要可靠：偵測到的 BPM 要等於（或倍頻/半頻）合成的 BPM
    ok = any(abs(m["bpm"] - bpm * f) < 3 for f in (0.5, 1, 2))
    print(mood, bpm, "→", m["bpm"], len(m["beats"]))
    assert ok and len(m["beats"]) > 10, (mood, m["bpm"])
    mt = os.path.getmtime(p); assert music.ensure(d, mood, 30) == p and os.path.getmtime(p) == mt  # 快取
assert music.pick_mood_from_folder(["/a/Chill Lofi.mp3", "/a/epic.mp3"], "熱血") == "/a/epic.mp3"
assert music.pick_mood_from_folder(["/a/x.mp3"], "放鬆") is None
print("MUSIC OK")
