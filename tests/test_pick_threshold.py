"""REVIEW_r10 B5：明顯較差的片段不會進一鍵成片；鎖定的仍保留。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import smart
mk = lambda i, f, s, sc: dict(id=i, file_id=f, start=s, end=s + 4, score=sc, sig=None, ftime=f)
clips = [mk(1, 1, 0, .53), mk(2, 1, 5, .45), mk(3, 2, 0, .38), mk(4, 3, 0, .19), mk(5, 3, 5, .15)]
ids = smart.auto_pick(clips, 60)
print("picked", ids); assert 4 not in ids and 5 not in ids and {1, 2, 3} <= set(ids)
ids = smart.auto_pick(clips, 60, locked=[4]); assert 4 in ids and 5 not in ids
print("PICK THRESHOLD OK")
