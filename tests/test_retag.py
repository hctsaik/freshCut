"""R29：標籤器版本變了 → 自動重貼舊標籤；版本沒變 → 不重算。不需要真的 CLIP（替換成假的）。"""
import os, sys, tempfile, subprocess, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from app import core, semantic
from app.library import Library
ff = core.find_ffmpeg(); d = tempfile.mkdtemp(); media = os.path.join(d, "m"); os.makedirs(media)
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=d=12:s=640x360:r=30", "-pix_fmt", "yuv420p",
                f"{media}/a.mp4"], check=True)
lib = Library(os.path.join(d, "lib")); lib.add_folder(media, watch=False); lib.analyze_pending(count=2, seg_len=2.0)
calls = []
semantic.has_clip = lambda: True
semantic.embed_images = lambda ps: [np.ones(4, np.float32) for _ in ps]
LABEL = ["海"]
semantic.auto_tags = lambda E, **k: (calls.append(len(E)), [list(LABEL) for _ in E])[1]
VER = ["v1"]; semantic.tagger_version = lambda: VER[0]
n = len(lib.clip_rows()); assert n >= 1
assert lib.tag_clips() == n and lib.get("tagger_version") == "v1"
assert lib.tag_clips() == 0, "版本沒變不該重算"
LABEL[0] = "雪"; VER[0] = "v2"
assert lib.tag_clips() == n, "版本變了要全部重貼"
assert all(json.loads(r["tags"]) == ["雪"] for r in lib.clip_rows()) and lib.get("tagger_version") == "v2"
assert lib.tag_clips() == 0
print("RETAG OK", calls)
