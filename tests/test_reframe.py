import os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import smart

rng = np.random.default_rng(1)
jit = list(0.7 + rng.uniform(-0.04, 0.04, 40))           # 主體不動、偵測抖動
sm = smart.smooth_path(jit)
d = np.abs(np.diff(sm)); print("jitter: max step %.4f std %.4f" % (d.max(), np.std(sm)))
assert d.max() < 0.006 and abs(np.mean(sm) - 0.7) < 0.05, "去抖動"
step = [0.3] * 15 + [0.75] * 25                          # 主體移動
sm = smart.smooth_path(step)
print("step end %.3f" % sm[-1]); assert abs(sm[-1] - 0.75) < 0.05 and max(np.abs(np.diff(sm))) <= 0.0601
# 臉漏偵測 2 點：不要跳回動態重心 0.2
xs = [0.8, 0.8, 0.8, 0.2, 0.2, 0.8, 0.8, 0.8]; c = [1, 1, 1, 0, 0, 1, 1, 1]
assert smart.fill_face_gaps(xs, c)[3] == 0.8
sm = smart.smooth_path(xs, conf=c); assert min(sm) > 0.75, sm
e = smart.crop_x_expr({"t0": 0, "step": 0.5, "x": step, "c": [0] * 40}, 2.0, 6.0)
assert e.startswith("max(0") and "if(lt(t" in e
# R17：多組隨機抖動的平均晃動量（R9 基準 seed=1 std 0.0069）
stds = []
for seed in range(1, 11):
    r = np.random.default_rng(seed); smj = smart.smooth_path(list(0.7 + r.uniform(-0.04, 0.04, 40)))
    stds.append(np.std(smj)); assert np.abs(np.diff(smj)).max() < 0.004
print("wobble std mean %.4f max %.4f" % (np.mean(stds), np.max(stds)))
assert np.mean(stds) < 0.0045
# 速度漸變：1 → 0.75 → 0.5 → 0.75 → 1，各段首尾相接
pc = smart.ramp_pieces(2.0, 6.0, (3.5, 4.5, 0.5))
assert [p[2] for p in pc] == [1.0, 0.75, 0.5, 0.75, 1.0] and pc[0][0] == 2.0 and pc[-1][1] == 6.0
assert all(abs(pc[i][1] - pc[i + 1][0]) < 1e-9 for i in range(len(pc) - 1))
assert abs(sum((b - a) / f for a, b, f in pc) - 4.0 - smart.ramp_extra(0.5, 1.0)) < 1e-6
assert smart.ramp_pieces(0, 4, None) == [(0, 4, 1.0)]
print("REFRAME OK")
