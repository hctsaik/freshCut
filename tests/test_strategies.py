"""R55-R62：多策略候選（從頭／中段／AI 人物／AI 動作／整支）、合併、排序、偏好學習、GUI chip。"""
import os, sys, json, tempfile, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from app import core
from app.library import Library

ff = core.find_ffmpeg()
root = tempfile.mkdtemp(); media = os.path.join(root, "m"); os.makedirs(media)
def gen(p, dur):
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=duration={dur}:size=320x180:rate=30",
                    "-f", "lavfi", "-i", f"sine=duration={dur}", "-shortest", "-pix_fmt", "yuv420p", p], check=True)
gen(media + "/long.mp4", 30); gen(media + "/short.mp4", 8)

# 1. 候選：每個都有策略標籤，2-4 段，彼此 IoU<=0.6，rank 0 唯一非 optional
for name, dur in (("long.mp4", 30), ("short.mp4", 8)):
    c = core.candidates_for_video(media + "/" + name, 3, 6.5)
    assert 1 <= len(c) <= core.STRAT_CFG["show_max"], (name, len(c))
    for s in c:
        assert s.strategies and all(k in core.STRAT_NAMES for k in s.strategies), s.strategies
    for i in range(len(c)):
        for j in range(i + 1, len(c)):
            assert core._iou((c[i].start, c[i].end), (c[j].start, c[j].end)) <= core.STRAT_CFG["merge_iou"] + 1e-6
    assert sorted(s.rank for s in c) == list(range(len(c)))     # R66：清單依時間排序，rank 保留推薦順位
    assert [s.start for s in c] == sorted(s.start for s in c)
    r0 = min(c, key=lambda s: s.rank); assert not r0.optional and all(s.optional for s in c if s is not r0)
    if name == "long.mp4":
        assert len(c) >= 2
        assert any("start" in s.strategies for s in c) and any(("action" in s.strategies or "people" in s.strategies) for s in c)
        st = [s for s in c if "start" in s.strategies][0]; assert st.start < 0.5
    else:
        assert any("whole" in s.strategies for s in c)   # <10 秒：整支
        w = [s for s in c if "whole" in s.strategies][0]; assert w.end - w.start > 7

# 2. 偏好：一直勾「從頭開始」的使用者 → start 排第一
w0 = core.strategy_weights({})
assert abs(w0["start"] - core.STRAT_PRIOR["start"]) < 1e-9
fan = {"start": {"picks": 50, "shown": 50}, "middle": {"picks": 0, "shown": 50},
       "people": {"picks": 0, "shown": 50}, "action": {"picks": 0, "shown": 50}}
w1 = core.strategy_weights(fan)
assert w1["start"] > max(w1[k] for k in ("uniform", "people", "action"))
c = core.candidates_for_video(media + "/long.mp4", 3, 6.5, prefs=fan)
assert "start" in c[0].strategies, [s.strategies for s in c]

# 3. Library：寫入 strategy 欄、shown 計數、手動勾選 → picks 計數
lib = Library(os.path.join(root, "lib"))
ids = lib.add_folder(media)
lib.analyze_pending(count=3, seg_len=6.5)
st = lib.strategy_prefs(); assert sum(v["shown"] for v in st.values()) > 0, st
clips = [c for f in ids for c in lib.clips(f)]
assert all(json.loads(c["strategy"]) for c in clips if c["source"] == "ai")
un = [c for c in clips if not c["checked"] and c["strategy"]][0]
before = {k: v["picks"] for k, v in st.items()}
lib.set_checked(un["id"], True)
after = lib.strategy_prefs()
for k in json.loads(un["strategy"]):
    assert after[k]["picks"] == before.get(k, 0) + 1
lib.set_checked(un["id"], True)                      # 已勾選再勾不重複計
assert lib.strategy_prefs() == after

# 4. GUI chip
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from app.gui.widgets import ClipCard
import inspect
cl = dict(lib.clips(ids[0])[0])
sig = inspect.signature(ClipCard.__init__).parameters
args = {"clip": cl}
card = ClipCard(**{k: v for k, v in (("clip", cl), ("vname", "long.mp4")) if k in sig}) if "vname" in sig else ClipCard(cl)
assert card.strategies and all(n in card.stratl.text() for n in (__import__("app.core", fromlist=["x"]).STRAT_NAMES[k] for k in card.strategies[:2])) and card.stratl.text().count("<span") == min(len(card.strategies), 2) + (len(card.strategies) > 2)
assert "策略" in card.stratl.accessibleName() and "策略" in card.name
print("ok")
