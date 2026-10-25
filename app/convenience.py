"""R31–R36：讓一鍵成片更省事的純邏輯（不依賴 Qt，方便測試）。
- 偵測插入的記憶卡/相機（DCIM、Insta360 結構）
- 依拍攝日/旅程自動分組（時間間隔；有 GPS 時加上距離）
- 一句話需求（離線 zh-TW 規則；有金鑰時可選雲端 LLM）
- 剪完後的調整指令（短一點/長一點/多一點人/換首歌/這段不要/更熱血）
- 偏好與「我的範本」的序列化
"""
import json, math, os, re, string, sys, time
from datetime import datetime

# ---------------- R31：記憶卡/相機偵測 ----------------
SKIP_VOLUMES = {"Macintosh HD", "Macintosh HD - Data", "Recovery", "Preboot", "VM", "Update", "com.apple.TimeMachine.localsnapshots"}


def candidate_roots(platform=None):
    """可能是記憶卡/相機的掛載點。IE_VOLUME_ROOTS（os.pathsep 分隔）可覆寫，供測試用。"""
    env = os.environ.get("IE_VOLUME_ROOTS")
    if env is not None:
        return [p for p in env.split(os.pathsep) if p]
    platform = platform or sys.platform
    out = []
    if platform == "darwin":
        try:
            for n in sorted(os.listdir("/Volumes")):
                p = os.path.join("/Volumes", n)
                if n not in SKIP_VOLUMES and not n.startswith(".") and os.path.isdir(p) and os.path.realpath(p) != "/":
                    out.append(p)
        except OSError:
            pass
    elif platform.startswith("win"):
        try:
            import ctypes
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            for i, L in enumerate(string.ascii_uppercase):
                if mask >> i & 1 and L not in "AB":
                    root = f"{L}:\\"
                    t = ctypes.windll.kernel32.GetDriveTypeW(root)
                    if t in (2, 3) and L != "C":     # 2=可移除（SD 讀卡機、相機 USB）；3=固定（部分 USB 讀卡機回報 3）
                        out.append(root)
        except Exception:
            pass
    else:
        user = os.environ.get("USER", "")
        for base in (f"/media/{user}", f"/run/media/{user}", "/media"):
            if os.path.isdir(base):
                out += [os.path.join(base, n) for n in sorted(os.listdir(base)) if os.path.isdir(os.path.join(base, n))]
    return out


def detect_camera(root):
    """有 DCIM 就視為相機/記憶卡；回傳 dict 或 None。Insta360：DCIM/Camera01 或有 .insv/.insp/.lrv。"""
    dcim = None
    try:
        for n in os.listdir(root):
            if n.upper() == "DCIM" and os.path.isdir(os.path.join(root, n)):
                dcim = os.path.join(root, n)
    except OSError:
        return None
    if not dcim:
        return None
    kind, n_media = "camera", 0
    for dp, dns, fns in os.walk(dcim):
        dns[:] = [d for d in dns if not d.startswith(".")]
        if os.path.basename(dp).lower().startswith("camera0"):
            kind = "insta360"
        for f in fns:
            lf = f.lower()
            if f.startswith("._"):
                continue
            if lf.endswith((".insv", ".insp", ".lrv")):
                kind = "insta360"
            if lf.endswith((".mp4", ".mov", ".insv", ".m4v")):
                n_media += 1
    label = os.path.basename(os.path.normpath(root)) or root
    if "insta360" in label.lower():
        kind = "insta360"
    return {"root": root, "dcim": dcim, "kind": kind, "label": label, "count": n_media}


def device_title(info):
    return ("Insta360 記憶卡" if info["kind"] == "insta360" else "相機記憶卡") + f"「{info['label']}」"


class DeviceWatcher:
    """每次 poll() 只回報「新插入」的卡（同一張卡在拔出前只提示一次）。"""
    def __init__(self, roots_fn=candidate_roots):
        self.roots_fn = roots_fn
        self.seen = set()

    def poll(self):
        found = []
        cur = set()
        for r in self.roots_fn():
            info = detect_camera(r)
            if not info:
                continue
            cur.add(r)
            if r not in self.seen:
                found.append(info)
        self.seen = cur            # 拔出後再插入會再提示
        return found


def new_media(paths, known):
    """paths 中不在 known（已在素材庫的路徑，含伴隨檔）的影片。"""
    known = set(known)
    return [p for p in paths if p not in known]


# ---------------- R32：依拍攝日/旅程分組 ----------------
def parse_iso6709(s):
    """'+25.0330+121.5654+010.000/' → (lat, lon)。"""
    m = re.match(r"\s*([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)", s or "")
    if not m:
        return None
    lat, lon = float(m[1]), float(m[2])
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def parse_meta(ffmpeg_stderr):
    """從 `ffmpeg -i` 輸出取 creation_time（UTC→本地 epoch）與 GPS（location / com.apple.quicktime.location.ISO6709）。"""
    t = None
    m = re.search(r"creation_time\s*:\s*(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?(Z)?", ffmpeg_stderr)
    if m:
        try:
            from datetime import timezone
            dt = datetime.strptime(m[1], "%Y-%m-%dT%H:%M:%S")
            t = dt.replace(tzinfo=timezone.utc).timestamp()
            if t < 946684800:          # 2000 年以前多半是相機沒設時間 → 不採用
                t = None
        except ValueError:
            t = None
    g = re.search(r"location(?:\.ISO6709)?(?:-\w+)?\s*:\s*([+-][\d.]+[+-][\d.]+)", ffmpeg_stderr)
    return t, parse_iso6709(g[1]) if g else None


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(h)))


def group_trips(items, gap_hours=8.0, far_km=80.0):
    """items: [{'id', 't': epoch, 'gps': (lat,lon)|None}]。
    依時間排序；與前一支相隔 > gap_hours，或（兩支都有 GPS 且）距離 > far_km 就開新的一組。
    連續幾天、每天間隔小於 gap_hours 的晚上→早上不算，所以用「同一天或隔夜 ≤ 36 小時且距離近」合併成旅程。"""
    its = sorted([i for i in items if i.get("t")], key=lambda i: i["t"])
    groups = []
    for it in its:
        g = groups[-1] if groups else None
        if g:
            last = g["items"][-1]
            dt = (it["t"] - last["t"]) / 3600
            gp = [x["gps"] for x in g["items"] if x.get("gps")]
            far = bool(it.get("gps") and gp and km(gp[-1], it["gps"]) > far_km)
            near = bool(it.get("gps") and gp and not far)
            # 有 GPS 而且還在附近：隔夜（≤36 小時）也算同一趟旅程
            same = not far and (dt <= gap_hours or (near and dt <= 36))
            if same:
                g["items"].append(it); continue
        groups.append({"items": [it]})
    for g in groups:
        ts = [x["t"] for x in g["items"]]
        g["start"], g["end"] = min(ts), max(ts)
        g["ids"] = [x["id"] for x in g["items"]]
        g["gps"] = next((x["gps"] for x in g["items"] if x.get("gps")), None)
        g["name"] = trip_name(g)
    return groups


def trip_name(g):
    a, b = datetime.fromtimestamp(g["start"]), datetime.fromtimestamp(g["end"])
    days = (b.date() - a.date()).days + 1
    n = len(g["ids"])
    if days == 1:
        return f"{a:%Y/%m/%d}（{n} 支）"
    return f"{a:%Y/%m/%d}–{b:%m/%d}・{days} 天（{n} 支）"


# ---------------- R33：一句話需求 ----------------
CN_NUM = {"一": 1, "兩": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "半": 0.5}
TAG_WORDS = [("海", ("海邊", "海灘", "沙灘", "海", "浪", "潛水", "衝浪")), ("山", ("山", "爬山", "登山", "健行")),
             ("雪", ("雪", "滑雪", "雪板")), ("夜景", ("夜景", "晚上", "夜市", "夜")),
             ("人物", ("小孩", "孩子", "寶寶", "家人", "朋友", "人", "自拍")), ("寵物", ("狗", "貓", "寵物", "毛孩"))]
MOOD_WORDS = [("熱血", ("熱血", "激動", "燃", "刺激", "動感", "嗨")), ("放鬆", ("放鬆", "輕鬆", "chill", "慵懶", "安靜")),
              ("溫馨", ("溫馨", "感人", "溫暖", "回憶", "家庭")), ("輕快", ("輕快", "活潑", "開心", "快樂"))]


def _num(s):
    s = s.strip()
    try:
        return float(s)
    except ValueError:
        pass
    if s in CN_NUM:
        return CN_NUM[s]
    m = re.fullmatch(r"([一二兩三四五六七八九])?十([一二三四五六七八九])?", s)
    if m:
        return (CN_NUM[m[1]] if m[1] else 1) * 10 + (CN_NUM[m[2]] if m[2] else 0)
    return None


def parse_brief(text):
    """離線規則解析。回傳只含有提到的欄位：target(秒)、pace、aspect、tags[list]、smile、mood、slowmo、title、style。"""
    t = (text or "").strip()
    low = t.lower()
    r = {}
    m = re.search(r"「([^」]+)」|\"([^\"]+)\"", t)
    if m:
        r["title"] = m[1] or m[2]
        t = t.replace(m[0], " "); low = t.lower()
    m = re.search(r"([\d.]+|[一二兩三四五六七八九十半]+)\s*(分鐘|分|min|秒|s\b|sec)", low)
    if m and _num(m[1]) is not None:
        v = _num(m[1]); r["target"] = int(round(v * 60 if m[2] in ("分鐘", "分", "min") else v))
    elif "一分半" in t:
        r["target"] = 90
    elif re.search(r"短短|很短|精簡", t):
        r["target"] = 15
    if "一分半" in t:
        r["target"] = 90
    if re.search(r"直式|直的|直立|reels|shorts|抖音|tiktok|限動|9\s*[:：x]\s*16", low):
        r["aspect"] = "9:16"
    elif re.search(r"方形|正方|1\s*[:：x]\s*1", low):
        r["aspect"] = "1:1"
    elif re.search(r"橫式|橫的|youtube|16\s*[:：x]\s*9", low):
        r["aspect"] = "16:9"
    if re.search(r"史詩|壯闊|大氣|電影感", t):
        r["pace"] = "史詩"
    elif re.search(r"快節奏|節奏快|輕快|快一點|俐落|動感|熱血", t):
        r["pace"] = "輕快"
    elif re.search(r"慢節奏|節奏慢|平穩|慢慢|放鬆", t):
        r["pace"] = "平穩"
    tags = []
    for tag, words in TAG_WORDS:
        for w in words:
            i = t.find(w)
            if i < 0:
                continue
            if w == "人" and re.search(r"沒有人|不要人|無人", t):
                continue
            if tag not in tags:
                tags.append(tag)
            break
    if tags:
        r["tags"] = tags
    if re.search(r"笑|開心|歡樂", t):
        r["smile"] = True
    for mood, words in MOOD_WORDS:
        if any(w in low for w in words):
            r["mood"] = mood; break
    if "慢動作" in t:
        r["slowmo"] = True
    if re.search(r"不要音樂|不配樂|無音樂", t):
        r["mood"] = ""
    if "vlog" in low:
        r["style"] = "Vlog"
    elif re.search(r"運動|極限|騎車|單車", t):
        r["style"] = "運動"
    elif re.search(r"旅行|旅遊|出遊", t):
        r["style"] = "旅行"
    return r


BRIEF_KEYS = {"target": int, "pace": ("平穩", "輕快", "史詩"), "aspect": ("16:9", "9:16", "1:1"),
              "mood": ("", "輕快", "放鬆", "熱血", "溫馨"), "style": ("", "Vlog", "運動", "旅行")}
ALL_TAGS = ("海", "山", "雪", "夜景", "人物", "寵物")


def normalize_brief(d):
    """把（可能來自雲端 LLM 的）dict 清成合法值；不合法的欄位丟掉。"""
    out = {}
    if not isinstance(d, dict):
        return out
    try:
        if d.get("target") is not None:
            v = int(float(d["target"]))
            if 5 <= v <= 600:
                out["target"] = v
    except (TypeError, ValueError):
        pass
    for k in ("pace", "aspect", "mood", "style"):
        if k in d and d[k] in BRIEF_KEYS[k]:
            out[k] = d[k]
    if isinstance(d.get("tags"), list):
        tg = [x for x in d["tags"] if x in ALL_TAGS]
        if tg:
            out["tags"] = tg
    for k in ("smile", "slowmo"):
        if isinstance(d.get(k), bool):
            out[k] = d[k]
    if isinstance(d.get("title"), str) and d["title"].strip():
        out["title"] = d["title"].strip()[:40]
    return out


LLM_PROMPT = ("把使用者的影片需求轉成 JSON，只輸出 JSON。欄位（沒提到就省略）：target(秒,整數), pace(平穩|輕快|史詩), "
              "aspect(16:9|9:16|1:1), tags(陣列，只能用 海 山 雪 夜景 人物 寵物), smile(bool), mood(輕快|放鬆|熱血|溫馨|空字串=不要音樂), "
              "slowmo(bool), title(字串), style(Vlog|運動|旅行)。需求：")


def llm_brief(text, call):
    """call(prompt)->str（例如 OpenAI 相容 chat）。失敗或亂回就退回離線規則；離線結果優先補空缺。"""
    base = parse_brief(text)
    try:
        s = call(LLM_PROMPT + text)
        m = re.search(r"\{.*\}", s or "", re.S)
        cloud = normalize_brief(json.loads(m[0])) if m else {}
    except Exception:
        cloud = {}
    return dict(base, **cloud), bool(cloud)


def describe_brief(b):
    parts = []
    if "target" in b: parts.append(f"{b['target']} 秒")
    if "aspect" in b: parts.append({"16:9": "橫式", "9:16": "直式", "1:1": "方形"}[b["aspect"]])
    if "pace" in b: parts.append(f"節奏{b['pace']}")
    if b.get("tags"): parts.append("優先" + "、".join(b["tags"]))
    if b.get("smile"): parts.append("多笑臉")
    if "mood" in b: parts.append(f"音樂{b['mood']}" if b["mood"] else "不配樂")
    if b.get("slowmo"): parts.append("慢動作")
    if b.get("style"): parts.append(b["style"])
    if b.get("title"): parts.append(f"標題「{b['title']}」")
    return "、".join(parts) or "沒有特別指定（用目前設定）"


# ---------------- R34：剪完後的調整指令 ----------------
REFINES = ["短一點", "長一點", "多一點人", "換首歌", "這段不要", "更熱血", "更溫馨", "放慢一點"]
MOOD_ORDER = ["輕快", "熱血", "溫馨", "放鬆"]


def parse_refine(text):
    t = (text or "").replace(" ", "")
    out = []
    pats = [("shorter", r"短一點|短一些|縮短|太長"), ("longer", r"長一點|長一些|加長|太短"),
            ("people", r"多一點人|多點人|多一些人|人多一點|多拍人|多一點笑"),
            ("music", r"換首歌|換音樂|換一首|換歌"), ("drop", r"這段不要|不要這段|刪掉這段|拿掉這段"),
            ("hype", r"更熱血|熱血一點|嗨一點|更刺激|快一點"), ("warm", r"更溫馨|溫馨一點|感人一點"),
            ("calm", r"放慢一點|慢一點|輕鬆一點|放鬆一點")]
    for k, p in pats:
        if re.search(p, t):
            out.append(k)
    return out


def refine_state(cmds, st):
    """st：{'target','pace','mood','fx','people','music_idx'}；回傳 (新 st, 說明清單)。純函式；「這段不要」由呼叫端處理。"""
    st = dict(st); msg = []
    for c in cmds:
        if c == "shorter":
            st["target"] = max(10, int(round(st.get("target", 60) * 0.7))); msg.append(f"縮短到約 {st['target']} 秒")
        elif c == "longer":
            st["target"] = min(600, int(round(st.get("target", 60) * 1.4))); msg.append(f"加長到約 {st['target']} 秒")
        elif c == "people":
            st["people"] = min(3, st.get("people", 0) + 1); msg.append("多挑有人臉/笑臉的片段")
        elif c == "music":
            m = st.get("mood") or "輕快"
            i = (MOOD_ORDER.index(m) + 1) % len(MOOD_ORDER) if m in MOOD_ORDER else 0
            st["mood"] = MOOD_ORDER[i]; st["music_idx"] = st.get("music_idx", 0) + 1; msg.append(f"換成「{st['mood']}」音樂")
        elif c == "hype":
            st.update(pace="輕快", mood="熱血", fx=st.get("fx") or "節拍放大"); msg.append("改成熱血：輕快節奏＋熱血音樂")
        elif c == "warm":
            st.update(pace="平穩", mood="溫馨"); msg.append("改成溫馨：平穩節奏＋溫馨音樂")
        elif c == "calm":
            st.update(pace="史詩" if st.get("pace") == "平穩" else "平穩"); msg.append(f"節奏改成{st['pace']}")
        elif c == "drop":
            msg.append("拿掉選取的片段（並記住不再自動挑）")
    return st, msg


def people_score(row, level):
    """多一點人：依片段裡有人臉的比例與「人物」標籤加分。"""
    if not level:
        return row["score"]
    f = 0.0
    try:
        tr = json.loads(row.get("track") or "{}")
        c = tr.get("c") or []
        f = sum(1 for v in c if v > 0) / max(1, len(c)) if c else 0.0
    except (ValueError, AttributeError, TypeError):
        pass
    tags = json.loads(row.get("tags") or "[]") if row.get("tags") else []
    bonus = 1 + level * (0.6 * f + (0.4 if "人物" in tags else 0))
    return row["score"] * bonus


# ---------------- R35：偏好與我的範本 ----------------
PREF_KEYS = ("target", "cust", "aspect", "res", "trans", "look", "music", "vol", "pace", "style", "fx", "beat", "slowmo",
             "frame", "tstyle", "tanim", "fade", "keep_audio", "auto_color", "share", "theme", "formats")


def clean_prefs(d):
    return {k: d[k] for k in PREF_KEYS if isinstance(d, dict) and k in d}


def templates_load(s):
    try:
        d = json.loads(s or "{}")
        return {str(k): clean_prefs(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except ValueError:
        return {}


def templates_save(tpls, name, prefs):
    t = dict(tpls); name = (name or "").strip()[:30]
    if not name:
        raise ValueError("範本名稱不可空白")
    t[name] = clean_prefs(prefs)
    return t


# ---------------- R36：一次輸出多種比例 ----------------
FORMAT_SUFFIX = {"16:9": "16x9", "9:16": "9x16", "1:1": "1x1"}


def multi_outputs(out, aspects):
    """'/x/精華.mp4', ['16:9','9:16'] → [('16:9','/x/精華_16x9.mp4'), ...]；只有一種時用原檔名。"""
    aspects = [a for a in dict.fromkeys(aspects) if a in FORMAT_SUFFIX]
    if len(aspects) <= 1:
        return [(aspects[0] if aspects else "16:9", out)]
    b, e = os.path.splitext(out)
    return [(a, f"{b}_{FORMAT_SUFFIX[a]}{e or '.mp4'}") for a in aspects]
