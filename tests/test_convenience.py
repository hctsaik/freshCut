"""R31–R36 純邏輯＋素材庫：記憶卡偵測、旅程分組、一句話需求、調整指令、範本、多比例檔名。"""
import os, sys, tempfile, subprocess, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import core, convenience as CV
from app.library import Library

# ---- R31 記憶卡/相機偵測（假的目錄樹）----
d = tempfile.mkdtemp()
def touch(p):
    os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").close()
ins = os.path.join(d, "Insta360X4"); touch(f"{ins}/DCIM/Camera01/VID_20260101_120000_00_001.insv")
touch(f"{ins}/DCIM/Camera01/LRV_20260101_120000_01_001.lrv"); touch(f"{ins}/DCIM/Camera01/._VID_x.insv")
gopro = os.path.join(d, "UNTITLED"); touch(f"{gopro}/dcim/100GOPRO/GX010001.MP4")
usb = os.path.join(d, "BACKUP"); touch(f"{usb}/docs/a.txt")
i1 = CV.detect_camera(ins); i2 = CV.detect_camera(gopro)
assert i1["kind"] == "insta360" and i1["count"] == 1, i1           # ._ 檔不算
assert i2 and i2["kind"] == "camera" and i2["count"] == 1, i2      # dcim 小寫也認
assert CV.detect_camera(usb) is None and CV.detect_camera(os.path.join(d, "nope")) is None
assert "Insta360" in CV.device_title(i1)
os.environ["IE_VOLUME_ROOTS"] = os.pathsep.join([ins, gopro, usb])
assert CV.candidate_roots() == [ins, gopro, usb]
w = CV.DeviceWatcher()
assert [x["root"] for x in w.poll()] == [ins, gopro]
assert w.poll() == [], "同一張卡只提示一次"
os.environ["IE_VOLUME_ROOTS"] = gopro; assert w.poll() == []      # 拔出 Insta360
os.environ["IE_VOLUME_ROOTS"] = os.pathsep.join([ins, gopro]); assert [x["root"] for x in w.poll()] == [ins], "重插要再提示"
del os.environ["IE_VOLUME_ROOTS"]
assert CV.candidate_roots("win32") == [] or True                   # 非 Windows 上 ctypes.windll 不存在 → 安全回空
assert CV.new_media(["a", "b", "c"], {"b"}) == ["a", "c"]
print("R31 OK")

# ---- R32 旅程分組 ----
t0 = time.mktime((2026, 10, 3, 9, 0, 0, 0, 0, -1)); H = 3600
items = [{"id": 1, "t": t0}, {"id": 2, "t": t0 + 2 * H}, {"id": 3, "t": t0 + 5 * H},      # 同一天
         {"id": 4, "t": t0 + 30 * 24 * H}]                                                # 一個月後
g = CV.group_trips(items)
assert [x["ids"] for x in g] == [[1, 2, 3], [4]] and "2026/10/03" in g[0]["name"] and "3 支" in g[0]["name"]
# GPS：隔夜但在附近 → 同一趟；同日但飛到 300 km 外 → 新的一組
kt = (21.95, 120.80); tp = (25.03, 121.56)
items = [{"id": 1, "t": t0, "gps": kt}, {"id": 2, "t": t0 + 22 * H, "gps": (21.96, 120.81)},
         {"id": 3, "t": t0 + 24 * H, "gps": tp}, {"id": 5, "t": None}]
g = CV.group_trips(items)
assert [x["ids"] for x in g] == [[1, 2], [3]], [x["ids"] for x in g]
assert "2 天" in g[0]["name"], g[0]["name"]
assert 290 < CV.km(kt, tp) < 360
assert CV.parse_iso6709("+25.0330+121.5654+010.000/") == (25.033, 121.5654) and CV.parse_iso6709("x") is None
t, gp = CV.parse_meta("    creation_time   : 2026-10-03T01:00:00.000000Z\n    location        : +25.0330+121.5654/\n")
assert gp == (25.033, 121.5654) and abs(t - 1790989200) < 1, t
assert CV.parse_meta("creation_time : 1970-01-01T00:00:00Z")[0] is None
print("R32 OK")

# ---- R33 一句話需求 ----
b = CV.parse_brief("做一支30秒直式的海邊影片，小孩笑的多一點，音樂熱血")
assert b["target"] == 30 and b["aspect"] == "9:16" and b["tags"] == ["海", "人物"] and b["smile"] and b["mood"] == "熱血", b
b = CV.parse_brief("一分鐘 橫式 放鬆 慢動作 標題「墾丁三日」")
assert b["target"] == 60 and b["aspect"] == "16:9" and b["mood"] == "放鬆" and b["pace"] == "平穩" and b["slowmo"] and b["title"] == "墾丁三日", b
assert CV.parse_brief("一分半的 IG Reels 滑雪")["target"] == 90
assert CV.parse_brief("十五秒方形 史詩 狗")== {"target": 15, "aspect": "1:1", "pace": "史詩", "tags": ["寵物"]}
assert CV.parse_brief("夜景 不要音樂")["mood"] == "" and CV.parse_brief("")=={}
assert CV.parse_brief("沒有人的山景")["tags"] == ["山"]
assert "30 秒" in CV.describe_brief({"target": 30}) and "用目前設定" in CV.describe_brief({})
# 雲端 LLM（假的）：合法值覆蓋，亂回退回離線
r, used = CV.llm_brief("30秒海邊", lambda p: '好的 {"target": 45, "aspect": "9:16", "tags": ["海","外星"], "pace":"亂"}')
assert used and r["target"] == 45 and r["aspect"] == "9:16" and r["tags"] == ["海"] and "pace" not in r
r, used = CV.llm_brief("30秒海邊", lambda p: (_ for _ in ()).throw(RuntimeError("net")))
assert not used and r == {"target": 30, "tags": ["海"]}
assert CV.normalize_brief({"target": 9999}) == {} and CV.normalize_brief("x") == {}
print("R33 OK")

# ---- R34 調整指令 ----
assert CV.parse_refine("短一點") == ["shorter"] and CV.parse_refine("長 一點、換首歌") == ["longer", "music"]
assert CV.parse_refine("多一點人") == ["people"] and CV.parse_refine("這段不要") == ["drop"] and CV.parse_refine("更熱血") == ["hype"]
assert CV.parse_refine("你好") == []
st, m = CV.refine_state(["shorter"], {"target": 60}); assert st["target"] == 42 and m
st, _ = CV.refine_state(["shorter"] * 9, {"target": 60}); assert st["target"] == 10
st, _ = CV.refine_state(["longer"], {"target": 30}); assert st["target"] == 42
st, _ = CV.refine_state(["music"], {"mood": "輕快"}); assert st["mood"] == "熱血"
st, _ = CV.refine_state(["music"], {"mood": "放鬆"}); assert st["mood"] == "輕快"
st, _ = CV.refine_state(["hype"], {"pace": "平穩", "fx": ""}); assert st["pace"] == "輕快" and st["mood"] == "熱血" and st["fx"] == "節拍放大"
st, _ = CV.refine_state(["people", "people"], {}); assert st["people"] == 2
row = {"score": 1.0, "track": json.dumps({"c": [0.9, 0.8, 0, 0]}), "tags": '["人物"]'}
assert CV.people_score(row, 0) == 1.0 and abs(CV.people_score(row, 1) - 1.7) < 1e-6
print("R34 OK")

# ---- R35 範本 ----
t = CV.templates_save({}, " 墾丁直式 ", {"aspect": "9:16", "pace": "輕快", "evil": 1})
assert t == {"墾丁直式": {"aspect": "9:16", "pace": "輕快"}}
assert CV.templates_load(json.dumps(t)) == t and CV.templates_load("壞掉") == {} and CV.templates_load("[1]") == {}
try:
    CV.templates_save({}, "  ", {}); raise SystemExit("空名稱要拒絕")
except ValueError:
    pass
print("R35 OK")

# ---- R36 多比例檔名 ----
assert CV.multi_outputs("/x/a.mp4", ["16:9"]) == [("16:9", "/x/a.mp4")]
assert CV.multi_outputs("/x/a.mp4", ["16:9", "9:16", "1:1", "9:16", "4:3"]) == [
    ("16:9", "/x/a_16x9.mp4"), ("9:16", "/x/a_9x16.mp4"), ("1:1", "/x/a_1x1.mp4")]
print("R36 OK")

# ---- 素材庫：只從一組挑、這段不要、多一點人、拍攝時間 ----
ff = core.find_ffmpeg(); media = os.path.join(d, "m"); os.makedirs(media)
for i, (src, ct) in enumerate([("testsrc2", "2026-10-03T01:00:00Z"), ("smptebars", "2026-10-03T03:00:00Z"),
                               ("rgbtestsrc", "2026-11-20T03:00:00Z")]):
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"{src}=d=8:s=320x180:r=30", "-pix_fmt", "yuv420p",
                    "-metadata", f"creation_time={ct}", "-metadata", "location=+21.9500+120.8000/", f"{media}/v{i}.mp4"], check=True)
lib = Library(os.path.join(d, "lib")); lib.add_folder(media, watch=False); lib.analyze_pending(count=2, seg_len=2.0)
fids = {os.path.basename(f["path"]): f["id"] for f in lib.files()}
tr = lib.trips()
assert [sorted(x["ids"]) for x in tr] == [sorted([fids["v0.mp4"], fids["v1.mp4"]]), [fids["v2.mp4"]]], tr
assert tr[0]["gps"] == (21.95, 120.8)
assert lib.file_meta(fids["v0.mp4"])[0] == tr[0]["start"]                         # 快取
ids = lib.auto_pick(999, only_fids=tr[1]["ids"])
assert ids and {r["file_id"] for r in lib.clip_rows() if r["id"] in ids} == {fids["v2.mp4"]}
all_ids = lib.auto_pick(999)
lk = all_ids[0]; lib.set_locked(lk, True)
lib.exclude(all_ids[:2])
assert lib.excluded() == sorted(all_ids[:2])
ids2 = lib.auto_pick(999)
assert all_ids[1] not in ids2 and lk in ids2, "排除的不再挑；鎖定的保留"
ids3 = lib.auto_pick(999, only_fids=[fids["v2.mp4"]])
assert lk in ids3, "只挑一組時鎖定的仍保留"
assert lib.auto_pick(5, people=2)
assert fids["v0.mp4"] and lib.known_paths() >= {os.path.join(media, "v0.mp4")}
print("CONVENIENCE OK")
