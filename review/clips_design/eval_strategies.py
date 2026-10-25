"""R67：每個策略單獨（預設 len/n）在真實標註上的 best-of-shown IoU / hit50（IoU≥0.5），train 與 held-out。
用 /workspace/real_labeled/work/r49 的特徵快取（feat/*.pkl）、split（seed 49，依連拍群組）與 ground_truth。
用法：.venv/bin/python review/clips_design/eval_strategies.py [out.json] [--tune-scene]"""
import sys, os, json, glob, pickle
R49 = "/workspace/real_labeled/work/r49"
sys.path.insert(0, R49); sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
from app import core
import metrics as M

FE = {os.path.basename(p)[:-4]: pickle.load(open(p, "rb")) for p in sorted(glob.glob(R49 + "/feat/*.pkl"))}
S = M.split(sorted(os.path.basename(p) for p in glob.glob(M.R + "source/*.lrv")))


def gt(f, D):
    g = M.G.get(f)
    if not g or (g["trimmed"] and g.get("start") is None):
        return None
    return (0.0, D) if not g["trimmed"] else (g["start"], g["end"])


def iou(a, b):
    i = max(0, min(a[1], b[1]) - max(a[0], b[0])); u = max(a[1], b[1]) - min(a[0], b[0]); return i / u if u > 0 else 0


def run(cfg_fn):
    res = {"train": [], "val": []}; ncards = {"train": [], "val": []}
    for f, d in FE.items():
        F = d["F"]; F.score = core.score_features(F); D = d["dur"]; g = gt(f, D)
        if g is None or f not in S:
            continue
        c = core.strategy_candidates(F, f, D, cfg=cfg_fn())
        best = max([iou((s.start, s.end), g) for s in c], default=0.0)
        res[S[f]].append(best); ncards[S[f]].append(len(c))
    return {p: dict(iou=float(np.mean(v)), hit50=float(np.mean([x >= 0.5 for x in v])), n=len(v),
                    cards=float(np.mean(ncards[p]))) for p, v in res.items()}


def only(k):
    return lambda: {s: dict(on=(s == k)) for s in core.STRAT_PER}


if __name__ == "__main__":
    if "--tune-scene" in sys.argv:          # 只看 train
        for thr in (0.03, 0.05, 0.06, 0.08, 0.1):
            for kk in (2.0, 4.0, 6.0):
                core.STRAT_CFG["scene_thr"], core.STRAT_CFG["scene_k"] = thr, kk
                for off in (0.0, 0.5, 1.0):
                    core.STRAT_CFG["scene_off"] = off
                    r = run(only("scene"))["train"]; print(f"thr {thr} k {kk} off {off}: train IoU {r['iou']:.3f} hit50 {r['hit50']:.3f} cards {r['cards']:.2f}")
        sys.exit()
    out = {}
    for k in core.STRAT_ORDER:
        out[k] = run(only(k))
    out["均勻取樣（SPEC 原預設 n=3, 5 秒）"] = run(lambda: {s: dict(on=(s == "uniform"), n=3, len=5.0) for s in core.STRAT_PER})
    out["預設組合（R66 出廠：start+people+action+whole+uniform n=1）"] = run(lambda: None)
    out["SPEC 原預設（均勻取樣關閉）"] = run(lambda: {"uniform": {"on": False}})
    out["全部 7 種開啟"] = run(lambda: {s: dict(on=True) for s in core.STRAT_PER})
    print(f"{'策略':<28}{'train IoU':>10}{'hit50':>8}{'held-out IoU':>14}{'hit50':>8}{'段/支':>7}  n(train/val)")
    for k, r in out.items():
        print(f"{core.STRAT_NAMES.get(k, k):<28}{r['train']['iou']:>10.3f}{r['train']['hit50']:>8.3f}{r['val']['iou']:>14.3f}"
              f"{r['val']['hit50']:>8.3f}{r['val']['cards']:>7.2f}  {r['train']['n']}/{r['val']['n']}")
    if len(sys.argv) > 1 and sys.argv[1].endswith(".json"):
        json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
