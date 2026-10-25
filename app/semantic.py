"""本機語意搜尋（不連網、不用金鑰）。
有安裝 open_clip（pip install open_clip_torch）時用 CLIP ViT-B-32 比對縮圖與文字；
模型第一次使用時下載一次（約 350 MB），之後離線可用；向量存進素材庫，不重算。
沒安裝時退回「色彩/亮度關鍵字」搜尋（海邊、夕陽、夜景、雪、森林…），結果標示為基本搜尋。"""
import os, json
import numpy as np

ZH = {  # 常用中文 → CLIP 英文提示（ViT-B-32 只懂英文）
    "海邊": "a photo of a beach and the sea", "海": "the sea", "沙灘": "a sandy beach", "夕陽": "a sunset",
    "日出": "a sunrise", "夜景": "a city at night", "晚上": "a night scene", "雪": "snow", "滑雪": "people skiing",
    "山": "mountains", "森林": "a forest", "樹": "trees", "花": "flowers", "城市": "a city street",
    "街": "a street", "車": "a car", "機車": "a motorcycle", "腳踏車": "a bicycle", "騎車": "riding a bike",
    "小孩": "a child", "小孩笑": "a smiling child", "笑": "a smiling person", "笑臉": "a smiling face",
    "人": "people", "朋友": "a group of friends", "家人": "a family", "自拍": "a selfie", "狗": "a dog",
    "貓": "a cat", "食物": "food on a table", "吃": "people eating", "美食": "delicious food",
    "游泳": "people swimming", "衝浪": "surfing", "潛水": "underwater scuba diving", "水": "water",
    "天空": "the sky", "雲": "clouds", "飛機": "an airplane", "跳": "a person jumping", "跑": "a person running",
    "演唱會": "a concert crowd", "生日": "a birthday party with cake", "蛋糕": "a cake", "婚禮": "a wedding",
    "公園": "a park", "湖": "a lake", "河": "a river", "瀑布": "a waterfall", "船": "a boat",
}
COLOR_RULES = {  # 基本搜尋：關鍵字 → (縮圖特徵函式)
    "海": "blue", "海邊": "blue", "沙灘": "blue", "天空": "blue", "水": "blue", "湖": "blue", "游泳": "blue",
    "夕陽": "orange", "日出": "orange", "夜": "dark", "夜景": "dark", "晚上": "dark", "雪": "white",
    "滑雪": "white", "森林": "green", "樹": "green", "山": "green", "公園": "green", "草": "green",
}


def has_clip():
    try:
        import open_clip, torch  # noqa: F401
        return True
    except Exception:
        return False


_model = None


def _load():
    global _model
    if _model is None:
        import open_clip, torch
        torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))
        m, _, pre = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
        m.eval(); _model = (m, pre, open_clip.get_tokenizer("ViT-B-32"), torch)
    return _model


def prompt(q):
    q = q.strip()
    if q in ZH:
        return ZH[q]
    parts = [ZH[k] for k in sorted(ZH, key=len, reverse=True) if k in q]
    return ", ".join(dict.fromkeys(parts)) if parts else q


def embed_images(paths, batch=16):
    """回傳 (n, 512) float32，已正規化。"""
    from PIL import Image
    m, pre, _, torch = _load()
    out = []
    with torch.no_grad():
        for i in range(0, len(paths), batch):
            x = torch.stack([pre(Image.open(p).convert("RGB")) for p in paths[i:i + batch]])
            e = m.encode_image(x); out.append((e / e.norm(dim=-1, keepdim=True)).numpy())
    return np.concatenate(out).astype(np.float32) if out else np.zeros((0, 512), np.float32)


def embed_text(q):
    m, _, tok, torch = _load()
    with torch.no_grad():
        e = m.encode_text(tok([prompt(q)]))
        return (e / e.norm(dim=-1, keepdim=True)).numpy()[0].astype(np.float32)


def rank(q, embs, top_frac=0.3, min_sim=0.2):
    """embs: dict id → vec。回傳依相似度排序的 [(id, sim)]，只留明顯相關的。"""
    if not embs:
        return []
    t = embed_text(q)
    ids = list(embs); M = np.stack([embs[i] for i in ids])
    sims = M @ t
    order = np.argsort(-sims)
    cut = max(sims.max() - 0.04, min_sim)          # 跟最佳結果差不多的才算
    keep = [(ids[i], float(sims[i])) for i in order if sims[i] >= cut]
    return keep[:max(1, int(len(ids) * top_frac) or 1)]


def _color_score(sig, kind):
    a = np.asarray(sig, np.float32).reshape(-1, 3)
    r, g, b = a[:, 0], a[:, 1], a[:, 2]
    lum = a.mean(1)
    return float({"blue": ((b > r + 0.08) & (b > g - 0.05)).mean(),
                  "orange": ((r > g + 0.1) & (g > b)).mean(),
                  "dark": (lum < 0.18).mean(),
                  "white": (lum > 0.8).mean(),
                  "green": ((g > r + 0.05) & (g > b + 0.02)).mean()}[kind])


def basic_rank(q, sigs, min_frac=0.25):
    """沒有 CLIP 時：依色彩規則搜尋。sigs: dict id → 9x16x3 小圖。回傳 ([(id, score)], 是否懂這個詞)。"""
    kind = next((COLOR_RULES[k] for k in sorted(COLOR_RULES, key=len, reverse=True) if k in q), None)
    if not kind:
        return [], False
    res = [(i, _color_score(s, kind)) for i, s in sigs.items() if s is not None]
    return sorted([r for r in res if r[1] >= min_frac], key=lambda r: -r[1]), True


# R15：自動場景標籤（zero-shot）。負類讓「都不像」的畫面不被硬貼標籤。
TAGS = {
    "海": ["a photo of the sea", "a photo of a beach", "ocean waves"],
    "山": ["a photo of mountains", "a mountain landscape"],
    "雪": ["a photo of snow", "a snowy landscape", "people skiing", "snow-capped mountains",
           "a winter scene covered in snow", "a ski slope"],
    "夜景": ["a photo taken at night", "a city at night with lights"],
    "人物": ["a photo of a person", "a photo of people", "a selfie"],
    "寵物": ["a photo of a dog", "a photo of a cat", "a pet"],
}
OTHER = ["a photo of a room", "a photo of a street", "an abstract pattern", "a photo of food",
         "a test pattern with colour bars", "a blurry photo", "a photo of an object"]
_tag_emb = None


def _tag_text():
    global _tag_emb
    if _tag_emb is None:
        m, _, tok, torch = _load()
        names = [(k, p) for k, ps in TAGS.items() for p in ps] + [(None, p) for p in OTHER]
        with torch.no_grad():
            e = m.encode_text(tok([p for _, p in names])); e = (e / e.norm(dim=-1, keepdim=True)).numpy()
        _tag_emb = ([k for k, _ in names], e.astype(np.float32))
    return _tag_emb


def tagger_version():
    """R29：標籤器版本＝提示詞＋門檻的雜湊。改了 TAGS/OTHER 或 auto_tags 預設值，版本就變，舊標籤會自動重貼。"""
    import hashlib, inspect
    src = json.dumps([TAGS, OTHER], ensure_ascii=False, sort_keys=True) + str(inspect.signature(auto_tags))
    return hashlib.sha1(src.encode("utf-8")).hexdigest()[:12]


def auto_tags(embs, min_p=0.2, max_tags=2, min_p2=0.12):
    """embs: list of 512 維向量 → 每張的標籤 list。softmax(100·cos) 後同一標籤的機率相加。"""
    keys, T = _tag_text()
    out = []
    for e in embs:
        z = 100.0 * (T @ np.asarray(e, np.float32)); p = np.exp(z - z.max()); p /= p.sum()
        agg = {}
        for k, pi in zip(keys, p):
            agg[k] = agg.get(k, 0.0) + float(pi)
        best = sorted(((v, k) for k, v in agg.items() if k), reverse=True)
        # 第一個標籤要 ≥ min_p；第二個標籤門檻較低（例：雪山＝山＋雪）
        keep = [k for i, (v, k) in enumerate(best[:max_tags])
                if v >= (min_p if i == 0 else min_p2) and v >= agg.get(None, 0) * 0.5]
        out.append(keep)
    return out
