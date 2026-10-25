"""選用的雲端 AI（OpenAI 相容 API）。金鑰存系統鑰匙圈（keyring）；沒有 keyring 時功能停用。
只有使用者在設定中同意並開啟後才會上傳縮圖。"""
import base64, json, urllib.request, urllib.error

SERVICE = "insta-editor"
SERVICES = {"OpenAI 相容 API": "https://api.openai.com/v1"}

try:
    import keyring  # type: ignore
except Exception:  # noqa: BLE001
    keyring = None


def has_keyring():
    return keyring is not None


def get_key():
    if not keyring:
        return ""
    try:
        return keyring.get_password(SERVICE, "api_key") or ""
    except Exception:  # noqa: BLE001
        return ""


def save_key(k):
    if not keyring:
        raise RuntimeError("系統缺少 keyring 套件，無法安全儲存金鑰")
    keyring.set_password(SERVICE, "api_key", k)


def delete_key():
    if keyring:
        try:
            keyring.delete_password(SERVICE, "api_key")
        except Exception:  # noqa: BLE001
            pass


class AIError(Exception):
    def __init__(self, kind, msg):
        super().__init__(msg)
        self.kind = kind   # key / quota / off


def _req(base, key, path, body=None, timeout=20):
    req = urllib.request.Request(base.rstrip("/") + path, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AIError("key", "金鑰無效")
        if e.code == 429:
            raise AIError("quota", "已達額度上限")
        raise AIError("off", f"服務回報錯誤 {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AIError("off", f"無法連線：{e}")


def test_key(base, key):
    if not key or len(key) < 8:
        raise AIError("key", "金鑰無效或未填寫")
    _req(base, key, "/models")
    return True


def match(base, key, model, query, thumbs):
    """thumbs: [(clip_id, jpg_path)]；回傳相符的 clip_id 集合。"""
    content = [{"type": "text", "text": f"以下有 {len(thumbs)} 張影像，依序編號 0..{len(thumbs)-1}。"
                f"哪些符合描述「{query}」？只回 JSON 陣列，例如 [0,3]。"}]
    for _, p in thumbs:
        with open(p, "rb") as f:
            content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()}})
    r = _req(base, key, "/chat/completions", {"model": model, "messages": [{"role": "user", "content": content}]}, timeout=90)
    txt = r["choices"][0]["message"]["content"]
    try:
        idx = json.loads(txt[txt.index("["): txt.rindex("]") + 1])
    except ValueError:
        idx = []
    return {thumbs[i][0] for i in idx if isinstance(i, int) and 0 <= i < len(thumbs)}


def chat(base, key, model, prompt, timeout=30):
    """R33：一句話需求的雲端解析（選用）。回傳文字。"""
    r = _req(base, key, "/chat/completions", {"model": model, "messages": [{"role": "user", "content": prompt}]}, timeout=timeout)
    return r["choices"][0]["message"]["content"]
