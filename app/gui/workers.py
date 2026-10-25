"""背景工作：分析、重新推薦、手動新增、雲端 AI、輸出都在 QThreadPool 執行，介面不會卡住。
SQLite 連線不能跨執行緒，所以每個工作在自己的執行緒內開一個 Library。"""
import os
from PySide6.QtCore import QObject, QRunnable, Signal


class Sig(QObject):
    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)
    cancelled = Signal()


class Job(QRunnable):
    def __init__(self, fn, *a, **kw):
        super().__init__()
        self.fn, self.a, self.kw = fn, a, kw
        self.sig = Sig()
        self.cancelled = False
        self.finished = False
        self.setAutoDelete(False)

    def run(self):
        from app import core
        core.set_cancel(lambda: self.cancelled)      # 讓 ffmpeg 可在執行中被中止
        try:
            r = self.fn(self, *self.a, **self.kw)
            self.finished = True
            self.sig.cancelled.emit() if self.cancelled else self.sig.done.emit(r)
        except core.Cancelled:
            self.finished = True
            self.sig.cancelled.emit()
        except Exception as e:  # noqa: BLE001 — 轉成介面上的錯誤訊息
            self.finished = True
            self.sig.failed.emit(f"{type(e).__name__}: {e}")
        finally:
            core.set_cancel(None)


def analyze_job(job, root, fids, settings, force=False):
    """分析指定影片；停止分析會在 ffmpeg 執行中立即中止，目前這支的舊結果保留。"""
    from app.library import Library
    lib = Library(root)
    try:
        done = []
        for i, fid in enumerate(fids):
            if job.cancelled:
                break
            job.sig.progress.emit(i / max(1, len(fids)), f"{i + 1}/{len(fids)} 支")
            lib.analyze(fid, count=settings.get("count", 2), seg_len=settings.get("seg_len", 6.5),
                        default_checked=2, force=force)
            done.append(fid)
        return done
    finally:
        lib.close()


def manual_job(job, root, fid, start, end):
    from app.library import Library
    lib = Library(root)
    try:
        return lib.add_manual_clip(fid, start, end)
    finally:
        lib.close()


def trim_job(job, root, cid, start, end):
    from app.library import Library
    lib = Library(root)
    try:
        lib.trim(cid, start, end)
        return cid
    finally:
        lib.close()


def ai_job(job, base, key, model, query, thumbs):
    from . import ai
    try:
        return ("ok", ai.match(base, key, model, query, thumbs))
    except ai.AIError as e:
        return ("err", e.kind)


def search_job(job, root, q):
    from app.library import Library
    lib = Library(root)
    try:
        return lib.semantic_search(q)
    finally:
        lib.close()


def export_job(job, segs, out, opts, prep=None):
    from app import core, smart
    if prep:
        info = None
        if prep.get("music"):
            job.sig.progress.emit(0.0, "分析音樂節拍…")
            from app.library import Library
            lib = Library(prep["root"])
            try:
                info = lib.music_beats(prep["music"])
            finally:
                lib.close()
        segs, opts.music_start = smart.prepare(segs, info, prep.get("pacing", "平穩"), prep.get("slowmo", 0.0),
                                               prep.get("crossfade", 0.0))
        if opts.effect and info and info.get("beats"):
            # 拍點換算到輸出時間軸；放大/閃白用強拍，避免每拍都閃太吵
            src = info.get("downbeats") or info["beats"]
            opts.effect_times = [round(b - opts.music_start, 3) for b in src if b >= opts.music_start]
    import tempfile
    if opts.title and (not core.has_filter("drawtext") or opts.title_style != "經典" or opts.title_anim != "淡入"):
        W, H = core.out_size(opts.aspect, opts.resolution)
        opts.title_png = smart.render_title_png(opts.title, opts.subtitle, W, H,
                                                os.path.join(tempfile.gettempdir(), f"ie_title_{os.getpid()}.png"),
                                                style=opts.title_style) or ""
    sts = []
    for i, st in enumerate((prep or {}).get("stickers", [])):
        png = smart.render_sticker_png(st[0], os.path.join(tempfile.gettempdir(), f"ie_st_{os.getpid()}_{i}.png"))
        if png:
            sts.append((png, *st[1:]))
    opts.stickers = sts
    core.export(segs, out, opts, progress=lambda f, m=None: job.sig.progress.emit(f, m or ""),
                cancel=lambda: job.cancelled)
    return out


def tag_job(job, root):
    """R15：背景用本機 CLIP 貼場景標籤；沒裝 CLIP 時回傳 None（不打擾使用者）。"""
    from app.library import Library
    lib = Library(root)
    try:
        return lib.tag_clips()
    finally:
        lib.close()


def brief_job(job, base, key, model, text):
    """R33：有雲端金鑰時用 LLM 解析一句話需求；失敗自動退回離線規則。"""
    from app import convenience as CV
    from . import ai
    return CV.llm_brief(text, lambda p: ai.chat(base, key, model, p))


def export_clips_job(job, items, folder, opts):
    """R65：已選片段各自輸出（背景執行、可取消）；items: [(Segment, strategies)]。"""
    from app import core
    return core.export_clips(items, folder, opts, progress=lambda f, m: job.sig.progress.emit(f, m),
                             cancel=lambda: job.cancelled)


def recompute_job(job, root, fids=None):
    """R69：策略設定改了 → 用特徵快取重算候選（不重新解碼）。"""
    from app.library import Library
    lib = Library(root)
    try:
        return lib.recompute_strategies(fids, progress=lambda i, n: job.sig.progress.emit(i / max(1, n), f"{i + 1}/{n} 支"))
    finally:
        lib.close()
