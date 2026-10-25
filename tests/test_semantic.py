"""本機 CLIP 語意搜尋（需要 open_clip；沒有就 SKIP）。用簡單合成圖驗證中文詞能找到對的畫面，並驗證向量快取。"""
import os, sys, tempfile, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import semantic as S
if not S.has_clip():
    print("SKIP test_semantic：沒有安裝 open_clip"); sys.exit(0)
TD = tempfile.mkdtemp(); os.chdir(TD)
from PIL import Image, ImageDraw
import random
W,H=320,180
a=Image.new("RGB",(W,H),(110,170,230));d=ImageDraw.Draw(a);d.rectangle([0,80,W,125],fill=(20,90,170));d.rectangle([0,125,W,H],fill=(235,215,160));d.ellipse([250,15,290,55],fill=(255,240,150));a.save("beach.jpg")
b=Image.new("RGB",(W,H),(200,215,235));d=ImageDraw.Draw(b);d.polygon([(0,180),(110,40),(220,180)],fill=(120,120,130));d.polygon([(80,77),(110,40),(140,77)],fill=(255,255,255));d.polygon([(140,180),(240,60),(320,180)],fill=(100,100,115));d.rectangle([0,150,W,H],fill=(250,250,252));b.save("snow.jpg")
c=Image.new("RGB",(W,H),(10,10,30));d=ImageDraw.Draw(c)
for x in range(0,W,40):
    h=random.randint(60,150);d.rectangle([x,H-h,x+30,H],fill=(30,30,50))
    for _ in range(12): px=x+random.randint(3,25);py=H-random.randint(5,h-5);d.rectangle([px,py,px+3,py+3],fill=(255,220,120))
c.save("night.jpg")
E = S.embed_images(["beach.jpg", "snow.jpg", "night.jpg"])
embs = dict(zip(["beach", "snow", "night"], E))
for q, want in (("海邊", "beach"), ("雪", "snow"), ("夜景", "night")):
    r = S.rank(q, embs); print(q, r)
    assert r and r[0][0] == want, (q, r)
assert S.prompt("小孩笑") == "a smiling child" and "beach" in S.prompt("海邊玩水")
# 素材庫路徑：向量只算一次並存進 DB
import subprocess
from app import core
from app.library import Library
v = os.path.join(TD, "v.mp4")
subprocess.run([core.find_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=duration=12:size=640x360:rate=30",
                "-pix_fmt", "yuv420p", v], check=True)
lib = Library(os.path.join(TD, "lib")); lib.add_files([v], find_siblings=False); lib.analyze(lib.files()[0]["id"])
ids, mode = lib.semantic_search("海邊"); assert mode == "clip"
n = lib.db.execute("SELECT COUNT(*) FROM clips WHERE emb IS NOT NULL").fetchone()[0]
assert n == len(lib.clip_rows()) > 0, n
lib.close()
print("SEMANTIC OK")

# R15：自動標籤（海/雪/夜景 合成圖；測試圖案不該被貼成「人物」）
T = S.auto_tags(list(E)); print("tags", T)
assert "海" in T[0] and set(T[1]) & {"雪", "山"} and "夜景" in T[2], T  # 合成雪景含山峰，CLIP 判成「山」也算合理
lib = Library(os.path.join(TD, "lib"))
assert lib.tag_clips() > 0 and lib.tag_clips() == 0          # 第二次不重算
cnt = lib.tag_counts(); print("testsrc tags", dict(cnt))
assert cnt.get("人物", 0) == 0 and cnt.get("寵物", 0) == 0
lib.close()
print("TAGS OK")

# R22：較像真實照片的雪景 → 雪；無雪山 → 不能有雪；簡單雪山 → 山＋雪
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import snowgen
SD = tempfile.mkdtemp(); fs = snowgen.make(SD)
TT = dict(zip([os.path.basename(f)[0] + os.path.basename(f)[1] for f in fs], S.auto_tags(S.embed_images(fs))))
assert all("雪" in TT[f"s{i}"] for i in range(4)), TT
assert all("雪" not in TT[f"m{i}"] for i in range(2)), TT
assert "雪" in S.auto_tags([embs["snow"]])[0], "簡單雪山也要有雪"
print("R22 snow tags", TT)
