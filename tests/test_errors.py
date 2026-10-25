"""R21：library.py 的錯誤處理只吞「預期的」錯誤（壞檔），程式錯誤要往上丟。"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import core, library
from app.library import Library

root = tempfile.mkdtemp(); bad = os.path.join(root, "broken.mp4")
open(bad, "wb").write(b"\x00not a video" * 100)
lib = Library(os.path.join(root, "lib")); fid = lib.add_files([bad])[0]
assert lib.analyze(fid) is False
err = lib.db.execute("SELECT error FROM files WHERE id=?", (fid,)).fetchone()[0]
assert err, "壞檔要記錄錯誤"
# 程式錯誤不能被當成「壞檔」吞掉
orig = core.probe
core.probe = lambda *a, **k: (_ for _ in ()).throw(TypeError("bug"))
try:
    lib.analyze(fid, force=True); raise SystemExit("TypeError 被吞掉了")
except TypeError:
    pass
finally:
    core.probe = orig
assert "Exception" not in [e.__name__ for e in library.ANALYZE_ERRORS]
print("ERRORS OK")
