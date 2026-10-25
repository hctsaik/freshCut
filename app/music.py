"""內建背景音樂：用程式即時合成（不含任何第三方錄音），輸出 WAV。
產生的音訊來自本程式的演算法，作者聲明以 CC0 釋出，可自由用於任何影片。"""
import os, wave
import numpy as np

SR = 44100
MOODS = {  # 名稱: (BPM, 和弦根音半音序列, 音色亮度, 鼓組強度)
    "輕快": (120, [0, 7, 9, 5], 1.0, 1.0),
    "放鬆": (84, [0, 5, 9, 7], 0.5, 0.35),
    "熱血": (140, [0, 3, 10, 8], 1.3, 1.2),
    "溫馨": (96, [0, 9, 5, 7], 0.7, 0.6),
}


def _note(f, n, bright):
    t = np.arange(n) / SR
    env = np.minimum(1, t / 0.01) * np.exp(-t * 2.5)
    w = np.sin(2 * np.pi * f * t) + 0.3 * bright * np.sin(4 * np.pi * f * t) + 0.12 * bright * np.sin(6 * np.pi * f * t)
    return w * env


def synth(mood="輕快", seconds=60.0, seed=0):
    bpm, prog, bright, drum = MOODS[mood]
    beat = 60.0 / bpm
    nb = int(np.ceil(seconds / beat))
    out = np.zeros(int(seconds * SR) + SR * 2)
    rng = np.random.default_rng(seed)
    base = 220.0 * 2 ** (rng.integers(-2, 3) / 12)
    nbeat = int(beat * SR)
    for b in range(nb):
        i = b * nbeat
        root = base * 2 ** (prog[(b // 4) % len(prog)] / 12)
        if b % 4 == 0:                                   # 和弦（每小節）
            for iv in (0, 4 if mood != "熱血" else 3, 7):
                out[i:i + nbeat * 4] += 0.18 * _note(root * 2 ** (iv / 12), nbeat * 4, bright)[: len(out) - i]
        out[i:i + nbeat] += 0.35 * _note(root / 2, nbeat, 0.3)[: len(out) - i]          # 低音
        k = np.arange(min(nbeat, len(out) - i)) / SR                                    # 大鼓：拍點清楚，方便對拍
        out[i:i + len(k)] += drum * 0.9 * np.sin(2 * np.pi * (50 + 80 * np.exp(-k * 30)) * k) * np.exp(-k * 18)
        if b % 2 == 1:                                   # 小鼓（雜訊）
            m = min(nbeat // 2, len(out) - i)
            out[i:i + m] += drum * 0.25 * rng.standard_normal(m) * np.exp(-np.arange(m) / SR * 25)
        mel = root * 2 ** (rng.choice([0, 2, 4, 7, 9, 12]) / 12) * 2           # 簡單旋律
        h = nbeat // 2
        out[i + h:i + h + h] += 0.12 * bright * _note(mel, h, bright)[: max(0, len(out) - i - h)]
    out = out[: int(seconds * SR)]
    fade = int(SR * 1.5)
    out[-fade:] *= np.linspace(1, 0, fade)
    out /= max(1e-6, np.abs(out).max()) / 0.8
    return out, bpm


def ensure(folder, mood, seconds=90.0):
    """產生（或沿用快取）內建音樂檔，回傳路徑。"""
    os.makedirs(folder, exist_ok=True)
    p = os.path.join(folder, f"builtin_{list(MOODS).index(mood)}_{int(seconds)}.wav")
    if not os.path.exists(p):
        y, _ = synth(mood, seconds)
        pcm = (np.clip(y, -1, 1) * 32767).astype("<i2")
        tmp = p + ".part"
        with wave.open(tmp, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
        os.replace(tmp, p)
    return p


def pick_mood_from_folder(paths, mood):
    """使用者資料夾的歌依檔名關鍵字對應氣氛；找不到就回傳 None。"""
    keys = {"輕快": ("happy", "upbeat", "fun", "輕快", "快樂"), "放鬆": ("chill", "calm", "relax", "lofi", "放鬆"),
            "熱血": ("epic", "rock", "energy", "power", "熱血"), "溫馨": ("warm", "love", "acoustic", "溫馨")}
    for p in paths:
        if any(k in os.path.basename(p).lower() for k in keys.get(mood, ())):
            return p
    return None
