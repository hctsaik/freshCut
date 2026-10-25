"""R68：策略設定改變 → 只重算候選（特徵快取），保留使用者動過的片段；驗收 #1（Library 層）。"""
import os, sys, tempfile, subprocess, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import core
from app.library import Library

ff = core.find_ffmpeg(); d = tempfile.mkdtemp()
src = os.path.join(d, "VID_20240825_023257_349.mp4")
subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=24:r=30", "-f", "lavfi", "-i",
                "sine=d=24", "-shortest", "-pix_fmt", "yuv420p", src], check=True)
lib = Library(os.path.join(d, "lib"))
lib.add_files([src]); fid = lib.files()[0]["id"]
lib.analyze(fid)
assert os.path.exists(lib._feat_path(fid)), "分析後要存特徵快取"
rows = lib.clips(fid); assert rows
# 舊設定遷移
lib.db.execute("DELETE FROM kv WHERE k='strategy_cfg'"); lib.set("strategies_enabled", ["start", "middle"]); lib.db.commit()
cfg = lib.strategy_cfg(); assert cfg["start"]["on"] and cfg["uniform"]["on"] and not cfg["people"]["on"], cfg
# 使用者親手勾選一段（touched）→ 重算後保留
keep_id = rows[-1]["id"]; lib.set_checked(keep_id, True)
# 驗收 #1：只開「精彩動作」、每支 2 段
cfg = {k: dict(v, on=(k == "action")) for k, v in core.strategy_config(None).items()}; cfg["action"]["n"] = 2
lib.set_strategy_cfg(cfg)
t = time.time(); lib.recompute_strategies([fid], proxies=False); dt = time.time() - t
rows = lib.clips(fid)
ai = [r for r in rows if r["id"] != keep_id]
assert len(ai) <= 2, ai
assert all(json.loads(r["strategy"] or "[]") == ["action"] for r in ai), [r["strategy"] for r in ai]
assert any(r["id"] == keep_id and r["checked"] for r in rows), "親手勾選的不可被重算刪掉"
assert dt < 5, f"用快取重算應該很快：{dt:.1f}s"
# 全部關掉 → 只剩保留的
lib.set_strategy_cfg({k: dict(v, on=False) for k, v in cfg.items()})
lib.recompute_strategies([fid], proxies=False)
assert [r["id"] for r in lib.clips(fid)] == [keep_id]
# 打開 start → 預設勾第一段？已有勾選的保留段 → 不再自動勾
lib.set_strategy_cfg({k: dict(v, on=(k == "start")) for k, v in cfg.items()})
lib.recompute_strategies([fid], proxies=False)
rs = lib.clips(fid); assert sum(r["checked"] for r in rs) == 1
print("R68 recompute OK", round(dt, 2), "s")
