"""選用的人臉／笑臉偵測（OpenCV Haar，離線、CPU、不需要下載模型）。
沒有安裝 opencv-python-headless 時 has_cv() 為 False，評分自動退回只用畫面/聲音特徵。"""
import numpy as np

_C = {}


def has_cv():
    try:
        import cv2  # noqa
        return hasattr(cv2, "CascadeClassifier") and bool(_cascade("frontalface_default"))
    except Exception:
        return False


def _cascade(name):
    if name not in _C:
        import cv2, os
        p = os.path.join(getattr(getattr(cv2, "data", None), "haarcascades", ""), f"haarcascade_{name}.xml")
        c = cv2.CascadeClassifier(p) if os.path.exists(p) else None
        _C[name] = c if c is not None and not c.empty() else None
    return _C[name]


SMILE_W, SMILE_NB = 80, 25   # R19：在 8 張公有領域肖像×3 種大小上調出（見 tests/test_smile.py）


def smile_score(roi, sc=None):
    """下半臉放大到 80px 寬、等化後再找笑容。分析用 320×180，臉常只有 30px，原本直接找幾乎永遠找不到。"""
    import cv2
    sc = sc or _cascade("smile")
    if sc is None or roi.size == 0 or roi.shape[1] < 8:
        return 0.0
    r = cv2.resize(roi, (SMILE_W, max(8, int(SMILE_W * roi.shape[0] / roi.shape[1]))), interpolation=cv2.INTER_CUBIC)
    r = cv2.equalizeHist(r)
    return 1.0 if len(sc.detectMultiScale(r, 1.1, SMILE_NB, minSize=(SMILE_W // 4, SMILE_W // 10))) else 0.0


def detect(frames):
    """frames: (n, h, w) uint8 灰階。回傳 (face 0..1, smile 0..1, fx 臉中心水平位置或 nan)。"""
    import cv2
    fc, sc = _cascade("frontalface_default"), _cascade("smile")
    n, h, w = frames.shape
    face = np.zeros(n, np.float32); smile = np.zeros(n, np.float32); fx = np.full(n, np.nan, np.float32)
    mins = max(16, h // 12)
    for i in range(n):
        g = np.ascontiguousarray(frames[i])
        faces = fc.detectMultiScale(g, 1.1, 5, minSize=(mins, mins))
        if len(faces) == 0 and g.std() < 40:          # 逆光/低對比才再試等化後的影像
            g = cv2.equalizeHist(g)
            faces = fc.detectMultiScale(g, 1.1, 5, minSize=(mins, mins))
        if len(faces) == 0:
            continue
        areas = [fw * fh for (_, _, fw, fh) in faces]
        x, y, fw, fh = faces[int(np.argmax(areas))]
        face[i] = min(1.0, 0.4 + 8 * sum(areas) / (w * h))      # 有臉就 0.4 起跳，臉越大越高
        fx[i] = (x + fw / 2) / w
        if sc is not None:
            smile[i] = smile_score(g[y + fh // 2: y + fh, x: x + fw], sc)
    return face, smile, fx
