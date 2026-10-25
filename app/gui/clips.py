"""R69：只輸出片段的介面元件（SPEC：review/clips_design/SPEC.md）。
策略列（7 種開關＋策略設定）、匯出設定面板、底部匯出列、匯出完成對話框、在 Finder／檔案總管中顯示。"""
import os, sys, subprocess, datetime
from PySide6.QtCore import Qt, Signal, QRect, QSize, QPoint, QUrl, QEvent
from PySide6.QtGui import QDesktopServices, QFontMetrics
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QGridLayout, QLayout,
                               QComboBox, QCheckBox, QDoubleSpinBox, QSpinBox, QDialog, QProgressBar, QLineEdit,
                               QFileDialog, QSizePolicy, QButtonGroup, QListWidget, QListWidgetItem)
from app import core
from app.core import zh_reason
from .style import prop, PF

# chip 色（SPEC §2.4：字色、底色；對比 ≥ 4.5:1）
STRAT_STYLE = {"start": ("#9CC3FF", "#1C2A40"), "people": ("#FF9CC8", "#3A1F2E"), "action": ("#FFB56B", "#3A2A14"),
               "whole": ("#C9B6FF", "#2A2340"), "uniform": ("#B0B0B0", "#2C2C2C"), "loud": ("#7FE0A8", "#183326"),
               "scene": ("#7FD8E0", "#163236"), "manual": ("#EEEEEE", "#3A3A3A")}
CHIP_MAX = 2


def chip_keys(clip, enabled):
    """卡片要顯示的策略：手動片段只顯示「手動」；AI 片段只顯示目前有開的策略（不照抄 mockup 的 bug）。"""
    import json
    if clip.get("source") == "manual":
        return ["manual"]
    try:
        ks = [core.strat_key(k) for k in json.loads(clip.get("strategy") or "[]")]
    except ValueError:
        ks = []
    out = []
    for k in ks:
        if k in core.STRAT_NAMES and (enabled is None or k in enabled) and k not in out:
            out.append(k)
    return out


def chip_html(keys, max_n=CHIP_MAX):
    sp = []
    for k in keys[:max_n]:
        fg, bg = STRAT_STYLE.get(k, ("#EEE", "#333"))
        sp.append(f'<span style="background:{bg};color:{fg}">&nbsp;{core.STRAT_NAMES[k]}&nbsp;</span>')
    if len(keys) > max_n:
        sp.append(f'<span style="color:#B0B0B0">+{len(keys) - max_n}</span>')
    return "&nbsp;".join(sp)


def reveal(path, platform=None, run=None, open_url=None):
    """在 Finder／檔案總管中顯示（SPEC 驗收 #5）。回傳實際執行的命令（測試用）。"""
    platform = platform or sys.platform
    run = run or subprocess.Popen
    if platform == "darwin":
        cmd = ["open", "-R", path]; run(cmd); return cmd
    if platform.startswith("win"):
        cmd = ["explorer", "/select," + os.path.normpath(path)]; run(cmd); return cmd
    d = path if os.path.isdir(path) else os.path.dirname(path)
    (open_url or QDesktopServices.openUrl)(QUrl.fromLocalFile(d)); return ["openUrl", d]


def reveal_label(platform=None):
    platform = platform or sys.platform
    return "在 Finder 中顯示" if platform == "darwin" else ("在檔案總管中顯示" if platform.startswith("win") else "開啟資料夾")


class FlowLayout(QLayout):
    """會換行的水平排列（策略 pill 在窄螢幕排成兩列）。"""
    def __init__(self, parent=None, sp=8):
        super().__init__(parent); self.items = []; self.sp = sp
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, it): self.items.append(it)
    def count(self): return len(self.items)
    def itemAt(self, i): return self.items[i] if 0 <= i < len(self.items) else None
    def takeAt(self, i): return self.items.pop(i) if 0 <= i < len(self.items) else None
    def expandingDirections(self): return Qt.Orientations(0)
    def hasHeightForWidth(self): return True
    def heightForWidth(self, w): return self._do(QRect(0, 0, w, 0), True)
    def setGeometry(self, r): super().setGeometry(r); self._do(r, False)
    def sizeHint(self): return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self.items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, r, test):
        x, y, lh = r.x(), r.y(), 0
        for it in self.items:
            if it.widget() and not it.widget().isVisibleTo(it.widget().parentWidget()):
                continue
            hs = it.sizeHint()
            if x + hs.width() > r.right() and lh > 0:
                x = r.x(); y += lh + self.sp; lh = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hs))
            x += hs.width() + self.sp; lh = max(lh, hs.height())
        return y + lh - r.y()


class StrategyPill(QPushButton):
    def __init__(self, k):
        super().__init__(); self.k = k; self.n = 0
        self.setCheckable(True); self.setToolTip(core.STRAT_TIPS.get(k, ""))
        self.toggled.connect(lambda _: self._paint())

    def set_count(self, n):
        self.n = n; self._paint()

    def _paint(self):
        on = self.isChecked(); fg, bg = STRAT_STYLE[self.k]
        self.setText(f"{'☑' if on else '☐'} {core.STRAT_NAMES[self.k]}" + (f"  {self.n}" if on else ""))
        self.setStyleSheet(f"QPushButton{{border-radius:14px;padding:4px 12px;"
                           + (f"background:{bg};color:{fg};border:1px solid {fg};font-weight:700}}" if on
                              else "background:#1d1d1d;color:#B0B0B0;border:1px solid #5A5A5A}")
                           + "QPushButton:focus{border:2px solid #FFFFFF}"
                           # R71：鎖定（匯出中）時看得出停用：灰底灰字、虛線框
                           + "QPushButton:disabled{background:#222;color:#6E6E6E;border:1px dashed #4A4A4A}")
        self.setAccessibleName(f"{core.STRAT_NAMES[self.k]}，{'開' if on else '關'}" + (f"，{self.n} 段" if on else ""))
        # R70：文字（含段數）變了要重新量寬度，否則 FlowLayout 沿用舊寬度把「1」截成「1:」
        f = self.font(); f.setBold(on); fm = QFontMetrics(f)
        self.setMinimumWidth(fm.horizontalAdvance(self.text()) + 34); self.updateGeometry()
        if self.parentWidget() and self.parentWidget().layout():
            self.parentWidget().layout().invalidate()


class StrategyPanel(QFrame):
    """「策略設定 ▾」展開的面板：每種策略的開關、長度、每支最多幾段。"""
    applied = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent); self.setObjectName("banner")
        v = QVBoxLayout(self); g = QGridLayout(); v.addLayout(g)
        for c, t in enumerate(("策略", "開", "每段長度", "每支最多")):
            g.addWidget(prop(QLabel(t), sec=True, small=True), 0, c)
        self.rows = {}
        for r, k in enumerate(core.STRAT_ORDER, 1):
            on = QCheckBox(); on.setAccessibleName(f"{core.STRAT_NAMES[k]} 開關")
            ln = QDoubleSpinBox(); n = QSpinBox()
            (lo, hi), (nlo, nhi) = core.STRAT_RANGE[k]; ln.setRange(lo, hi); ln.setSingleStep(0.5)
            ln.setSuffix(" 秒"); n.setRange(nlo, nhi); n.setSuffix(" 段"); n.setEnabled(nhi > nlo)
            if k == "whole":
                ln.setPrefix("≤ "); ln.setToolTip("影片短於這個秒數時，整支當一段")
            ln.setAccessibleName(f"{core.STRAT_NAMES[k]} {'整支門檻' if k == 'whole' else '每段長度'}")
            n.setAccessibleName(f"{core.STRAT_NAMES[k]} 每支最多段數")
            g.addWidget(QLabel(core.STRAT_NAMES[k]), r, 0); g.addWidget(on, r, 1); g.addWidget(ln, r, 2); g.addWidget(n, r, 3)
            self.rows[k] = (on, ln, n)
        self.note = prop(QLabel(f"每支影片合計最多 {core.STRAT_TOTAL_MAX} 段；重疊的片段會合併成一張卡、顯示多個策略。"
                                "改動只重算候選、不重新分析；已勾選、鎖定、微調過的片段會保留。"), sec=True, small=True)
        self.note.setWordWrap(True); v.addWidget(self.note)
        h = QHBoxLayout(); v.addLayout(h)
        self.reset_b = QPushButton("還原預設"); self.apply_b = prop(QPushButton("套用到全部影片"), accent2=True)
        h.addWidget(self.reset_b); h.addStretch(1); h.addWidget(self.apply_b)
        self.reset_b.clicked.connect(lambda: self.set_cfg(core.strategy_config(None)))
        self.apply_b.clicked.connect(lambda: self.applied.emit(self.cfg()))

    def set_cfg(self, cfg):
        for k, (on, ln, n) in self.rows.items():
            c = cfg[k]; on.setChecked(c["on"])
            ln.setValue(c["len"]); n.setValue(c["n"])

    def cfg(self):
        out = {}
        for k, (on, ln, n) in self.rows.items():
            out[k] = {"on": on.isChecked(), "len": ln.value(), "n": n.value()}
        return core.strategy_config(out)


class StrategyBar(QWidget):
    """剪片策略列：7 個 pill（點一下開關）＋「策略設定 ▾」。"""
    changed = Signal(dict)
    tip_closed = Signal()

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self); v.setContentsMargins(12, 8, 12, 0); v.setSpacing(6)
        row = QHBoxLayout(); v.addLayout(row)
        lab = prop(QLabel("剪片策略"), sec=True, small=True); row.addWidget(lab, 0, Qt.AlignTop)
        box = QWidget(); self.flow = FlowLayout(box); row.addWidget(box, 1)
        box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.pills = {}
        for k in core.STRAT_ORDER:
            p = StrategyPill(k); p.toggled.connect(lambda on, k=k: self._toggled(k, on))
            self.flow.addWidget(p); self.pills[k] = p
        self.more = QPushButton("策略設定 ▾"); self.more.setCheckable(True)
        self.more.setAccessibleName("策略設定"); row.addWidget(self.more, 0, Qt.AlignTop)
        self.panel = StrategyPanel(); self.panel.hide(); v.addWidget(self.panel)
        self.more.toggled.connect(self._more)
        self.panel.applied.connect(self._applied)
        # R70：均勻取樣第一次使用的一行說明（關掉後記住）
        hr = QHBoxLayout(); hr.setContentsMargins(0, 0, 0, 0); self.tip = QWidget(); self.tip.setLayout(hr)
        self.tip_l = prop(QLabel("💡 「均勻取樣」每支影片只補 1 段當保底，預設不勾選、排在最後；"
                                 "其他策略沒抓到東西時才用得到。"), sec=True, small=True)
        self.tip_l.setWordWrap(False); self.tip_x = prop(QPushButton("知道了"), link=True)
        self.tip_x.setAccessibleName("關閉均勻取樣說明")
        hr.addWidget(self.tip_l, 1); hr.addWidget(self.tip_x); self.tip.hide(); v.addWidget(self.tip)
        self.tip_x.clicked.connect(lambda: (self.tip.hide(), self.tip_closed.emit()))
        self._cfg = core.strategy_config(None); self._quiet = False

    def _more(self, on):
        self.panel.setVisible(on); self.more.setText("策略設定 ▴" if on else "策略設定 ▾")
        if on:
            self.panel.set_cfg(self._cfg)

    def set_cfg(self, cfg):
        self._cfg = core.strategy_config(cfg); self._quiet = True
        for k, p in self.pills.items():
            p.setChecked(self._cfg[k]["on"])
        self._quiet = False
        if self.panel.isVisible():
            self.panel.set_cfg(self._cfg)

    def cfg(self):
        return self._cfg

    def set_counts(self, counts):
        for k, p in self.pills.items():
            p.set_count(counts.get(k, 0))

    def _toggled(self, k, on):
        if self._quiet:
            return
        c = {kk: dict(v) for kk, v in self._cfg.items()}; c[k]["on"] = on
        self._cfg = core.strategy_config(c)
        if self.panel.isVisible():
            self.panel.rows[k][0].setChecked(on)
        self.changed.emit(self._cfg)

    def _applied(self, cfg):
        self.set_cfg(cfg); self.changed.emit(self._cfg)
        self.more.setChecked(False)


def default_export_dir(today=None):
    home = os.path.expanduser("~")
    base = os.path.join(home, "Movies" if PF == "mac" else "Videos", "精華片段")
    return os.path.join(base, (today or datetime.date.today()).isoformat())


class ExportPanel(QFrame):
    """右欄「匯出設定」（SPEC §2.5）。"""
    changed = Signal()
    FIELDS = [("pattern", [("影片名_策略_序號", "seq"), ("影片名_時間_策略", "time"), ("拍攝日期_序號", "date")]),
              ("fmt", [("MP4（H.264）", "mp4"), ("MP4（HEVC，較小）", "hevc"), ("MOV（ProRes 422，後製用）", "prores")]),
              ("aspect", [("原始比例", "orig"), ("16:9", "16:9"), ("9:16（直式）", "9:16"), ("1:1", "1:1")]),
              ("resolution", [("與原片相同", "orig"), ("1080p", "1080p"), ("720p", "720p")])]
    LABELS = {"pattern": "檔名規則", "fmt": "格式", "aspect": "畫面比例", "resolution": "解析度"}

    def __init__(self):
        super().__init__(); self.setObjectName("panel")
        v = QVBoxLayout(self); v.setContentsMargins(14, 12, 14, 12); v.setSpacing(6)
        v.addWidget(prop(QLabel("匯出設定"), h=True))
        v.addWidget(QLabel("輸出資料夾"))
        fr = QHBoxLayout(); v.addLayout(fr)
        self.folder_e = QLineEdit(default_export_dir()); self.folder_e.setAccessibleName("輸出資料夾")
        self.folder_b = QPushButton("選擇…"); self.folder_b.setAccessibleName("選擇輸出資料夾")
        fr.addWidget(self.folder_e, 1); fr.addWidget(self.folder_b)
        self.folder_b.clicked.connect(self._pick)
        self.combos = {}
        for k, items in self.FIELDS:
            l = QLabel(self.LABELS[k]); c = QComboBox(); l.setBuddy(c); c.setAccessibleName(self.LABELS[k])
            for t, d in items:
                c.addItem(t, d)
            v.addWidget(l); v.addWidget(c); self.combos[k] = c
            c.currentIndexChanged.connect(self._changed)
            if k == "pattern":
                self.sample = QLabel(""); self.sample.setObjectName("sample")
                self.sample.setStyleSheet("font-family:Menlo,Consolas,monospace;font-size:12px;color:#D0D0D0;"
                                          "background:#141414;border:1px dashed #5A5A5A;border-radius:4px;padding:4px 6px")
                self.sample.setAccessibleName("檔名預覽"); self.sample.setWordWrap(True); v.addWidget(self.sample)
        v.addWidget(QLabel("聲音"))
        self.audio = QCheckBox("保留原音"); self.audio.setChecked(True); v.addWidget(self.audio)
        v.addWidget(QLabel("其他"))
        self.subf = QCheckBox("依影片建立子資料夾"); self.subf.setChecked(True); v.addWidget(self.subf)
        self.over = QCheckBox("同名檔案時覆寫（預設：自動加 _2）"); v.addWidget(self.over)
        for w in (self.audio, self.subf, self.over):
            w.toggled.connect(self._changed)
        self.folder_e.textChanged.connect(self._changed)
        note = prop(QLabel("每個片段各自輸出成一個檔案，不加配樂、轉場或字幕。"), sec=True, small=True)
        note.setWordWrap(True); v.addWidget(note); v.addStretch(1)
        self._sample_item = None; self._changed()

    def _pick(self):
        d = QFileDialog.getExistingDirectory(self, "選擇輸出資料夾", self.folder_e.text())
        if d:
            self.folder_e.setText(d)

    def set_sample(self, item):
        self._sample_item = item; self._update_sample()

    def _update_sample(self):
        it = self._sample_item or (core.Segment("VID_20240825_023257_349.mp4", 0, 7, 1), ["start"])
        rel = core.plan_clip_names([it], self.options())[0]
        self.sample.setText(rel.replace(os.sep, "/"))

    def _changed(self, *_):
        self._update_sample(); self.changed.emit()

    def folder(self):
        return os.path.expanduser(self.folder_e.text().strip()) or default_export_dir()

    def options(self):
        g = lambda k: self.combos[k].currentData()
        return core.ClipOptions(pattern=g("pattern"), fmt=g("fmt"), aspect=g("aspect"), resolution=g("resolution"),
                                audio=self.audio.isChecked(), subfolders=self.subf.isChecked(), overwrite=self.over.isChecked())

    def state(self):
        d = {k: c.currentData() for k, c in self.combos.items()}
        d.update(audio=self.audio.isChecked(), subfolders=self.subf.isChecked(), overwrite=self.over.isChecked(),
                 folder=self.folder_e.text())
        return d

    def set_state(self, d):
        for k, c in self.combos.items():
            i = c.findData((d or {}).get(k))
            if i >= 0:
                c.setCurrentIndex(i)
        for k, w in (("audio", self.audio), ("subfolders", self.subf), ("overwrite", self.over)):
            if k in (d or {}):
                w.setChecked(bool(d[k]))
        if (d or {}).get("folder"):
            self.folder_e.setText(d["folder"])


def est_mb(seconds, co, src_h=1080):
    """預估檔案大小（MB）：H.264 1080p ≈ 12 Mbps、HEVC 約一半、ProRes 422 ≈ 147 Mbps；依解析度縮放。"""
    h = {"1080p": 1080, "720p": 720}.get(co.resolution, src_h or 1080)
    mbps = {"mp4": 12, "hevc": 6, "prores": 147}.get(co.fmt, 12) * (h / 1080) ** 2
    return seconds * (mbps + (0.19 if co.audio else 0)) / 8


class ExportBar(QFrame):
    """底部匯出列（56px）：摘要／進度＋取消、預覽選取、唯一的黃色主按鈕「匯出已選片段（N）」。"""
    def __init__(self):
        super().__init__(); self.setObjectName("panel"); self.setFixedHeight(56)
        self.setStyleSheet("QFrame#panel{border-top:1px solid #3a3a3a}")
        h = QHBoxLayout(self); h.setContentsMargins(12, 6, 12, 6)
        self.summary = QLabel(""); self.summary.setAccessibleName("已選摘要"); h.addWidget(self.summary)
        self.summary.setTextFormat(Qt.RichText); self.summary.setMinimumWidth(250)   # R70：不可被擠成「約」
        self.summary.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.prog = QProgressBar(); self.prog.setFixedWidth(160); self.prog.setTextVisible(False); self.prog.setRange(0, 1000)
        self.prog_l = QLabel(""); self.prog_l.setAccessibleName("匯出進度")
        # R71：給足「匯出中 120/500 · 剩約 12:34」的寬度，不再截成「剩約 0:0…」
        self._fit_prog()
        self.cancel_b = prop(QPushButton("取消"), danger=True); self.cancel_b.setAccessibleName("取消匯出")
        for w in (self.prog, self.prog_l):
            h.addWidget(w); w.hide()
        self.cancel_b.hide()   # R71：只留主按鈕位置的「取消匯出」；這顆不再顯示（保留給舊程式碼呼叫）
        h.addStretch(1)
        self.reason = prop(QLabel(""), sec=True); h.addWidget(self.reason)
        self.drawer_b = QPushButton("匯出設定 ▸"); self.drawer_b.setCheckable(True)
        self.drawer_b.setAccessibleName("顯示或隱藏匯出設定"); self.drawer_b.hide(); h.addWidget(self.drawer_b)
        self.prev_b = QPushButton("預覽選取"); h.addWidget(self.prev_b)
        self.exp_b = prop(QPushButton("匯出已選片段（0）"), primary=True); h.addWidget(self.exp_b)
        self.exp_b.setMinimumWidth(180)

    PROG_WORST = "匯出中 9999/9999 · 剩約 99:99"

    def _fit_prog(self):
        """R72：用套完樣式表之後的實際字型量寬度（不是預設字型）。"""
        self.prog_l.ensurePolished()
        self.prog_l.setMinimumWidth(self.prog_l.fontMetrics().horizontalAdvance(self.PROG_WORST) + 12)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.StyleChange, QEvent.FontChange, QEvent.PolishRequest) and hasattr(self, "prog_l"):
            self._fit_prog()

    def showEvent(self, e):
        super().showEvent(e); self._fit_prog()

    def busy(self, on):
        self._fit_prog()
        for w in (self.prog, self.prog_l):
            w.setVisible(on)
        self.summary.setVisible(not on); self.cancel_b.setEnabled(True); self.prev_b.setEnabled(not on)
        prop(self.exp_b, primary=not on, danger=on)
        if on:
            self.prog.setValue(0)


def fmt_mmss(s):
    s = max(0, int(round(s))); return f"{s // 60}:{s % 60:02d}"


class ExportDoneDialog(QDialog):
    """匯出完成（SPEC §2.7）。"""
    retry = Signal(list)
    again = Signal()

    @staticmethod
    def _wants(results, want, got):
        n = len(results)
        return (list(want or [None] * n) + [None] * n)[:n], (list(got or [None] * n) + [None] * n)[:n]

    def __init__(self, parent, results, rels, folder, elapsed, cancelled=False, total=None, want=None, got=None):
        super().__init__(parent); self.setWindowTitle("匯出完成"); self.setMinimumWidth(520)
        self.folder = folder
        ok = sorted([(p, r) for (p, e), r in zip(results, rels) if p], key=lambda t: os.path.basename(t[0]).lower())   # R72：依檔名排序
        bad = [(i, r, e) for i, ((p, e), r) in enumerate(zip(results, rels)) if not p]
        self.ok_paths = [p for p, _ in ok]
        v = QVBoxLayout(self)
        if want is None:
            want = [getattr(p, "want", None) for p, _ in results]; got = [getattr(p, "got", None) for p, _ in results]
        self.trunc = sorted([(r, w, g) for (p, e), r, w, g in zip(results, rels, *self._wants(results, want, got)) if p
                             and w and g is not None and g < w - 0.05], key=lambda t: os.path.basename(t[0]).lower())
        head = (f"已取消：已匯出 {len(ok)} / {total} 個片段" if cancelled else
                f"⚠ 已匯出 {len(ok)} 個片段，其中 {len(self.trunc)} 段被截短" if not bad and self.trunc else   # R72
                f"✓ 已匯出 {len(ok)} 個片段" if not bad else
                f"⚠ 匯出失敗：{len(bad)} 個片段沒有成功" if not ok else
                f"⚠ 已匯出 {len(ok)} 個片段，{len(bad)} 個失敗" + (f"、{len(self.trunc)} 段被截短" if self.trunc else ""))   # R73
        if bad and not cancelled:
            self.setWindowTitle("匯出未完成")
        elif self.trunc and not cancelled:
            self.setWindowTitle("匯出完成（有片段被截短）")
        self.title = prop(QLabel(head), h=True); self.title.setStyleSheet("font-size:18px;font-weight:700"); v.addWidget(self.title)
        mb = sum(os.path.getsize(p) for p in self.ok_paths if os.path.exists(p)) / 1e6
        self.meta = prop(QLabel(f"耗時 {fmt_mmss(elapsed)} · 共 {mb:.0f} MB · 存到 {folder}"), sec=True, small=True)
        self.meta.setWordWrap(True); v.addWidget(self.meta)
        names = [os.path.relpath(p, folder).replace(os.sep, "/") for p in self.ok_paths]
        # R70：長檔名不截尾——清單可捲動、中間省略、滑鼠移上去看完整路徑
        self.files = QListWidget(); self.files.setAccessibleName("已匯出的檔案")
        self.files.setTextElideMode(Qt.ElideMiddle); self.files.setUniformItemSizes(True)
        # R71：關掉橫向捲軸，項目寬度＝清單寬度，ElideMiddle 才會生效；主行只放檔名，資料夾放第二行／tooltip
        self.files.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.files.setWordWrap(False)
        self.files.setResizeMode(QListWidget.Adjust)
        self.files.setStyleSheet("QListWidget{font-family:Menlo,Consolas,monospace;font-size:12px;background:#141414;"
                                 "padding:4px;border-radius:4px}")
        tset = {r for r, _, _ in self.trunc}
        for n, p, r in zip(names, self.ok_paths, [r for _, r in ok]):
            base = os.path.basename(n); sub = os.path.dirname(n)
            it = QListWidgetItem(base + ("　（已截短）" if r in tset else ""))
            it.setToolTip(p + (f"\n資料夾：{sub}/" if sub else "")); it.setData(Qt.UserRole, p); self.files.addItem(it)
        if not names:
            it = QListWidgetItem("（沒有檔案）"); it.setFlags(Qt.NoItemFlags); self.files.addItem(it)
        rh = self.files.sizeHintForRow(0) if self.files.count() else 18
        self.files.setFixedHeight(min(6, max(1, self.files.count())) * (rh + 2) + 12)
        self.names = names
        v.addWidget(self.files)
        subs = sorted({os.path.dirname(n) for n in names if os.path.dirname(n)})
        self.dir_l = prop(QLabel("位置：" + folder), sec=True, small=True)
        self.dir_l.setWordWrap(True); self.dir_l.setToolTip(folder); v.addWidget(self.dir_l)
        # R72：提示獨立一行、不自動換行（「路徑」不會被拆成兩行）
        self.hint_l = prop(QLabel(f"依影片分成 {len(subs)} 個子資料夾 · 滑鼠移到檔名可看完整路徑" if subs else
                                  "滑鼠移到檔名可看完整路徑"), sec=True, small=True)
        self.hint_l.setWordWrap(False); v.addWidget(self.hint_l)
        if self.trunc:   # R71：部分超出影片長度的片段會被截短——要說出來，不能默默算成功
            # R72：每個檔名自成一行、不自動換行；太長就中間省略（不會在檔名中間斷行），完整清單在 tooltip
            self.trunc_l = prop(QLabel(""), warn=True); self.trunc_l.setStyleSheet("color:#FFB74D")
            self.trunc_l.setWordWrap(False); self.trunc_l.ensurePolished()
            fm = self.trunc_l.fontMetrics(); lw = 470
            lines = [f"⚠ {len(self.trunc)} 段因超出影片長度被截短："]
            for r, w, g in self.trunc[:3]:
                tail = f"  {w:.1f}→{g:.1f} 秒"
                lines.append("• " + fm.elidedText(os.path.basename(r), Qt.ElideMiddle, lw - fm.horizontalAdvance("• " + tail)) + tail)
            if len(self.trunc) > 3:
                lines.append(f"…另 {len(self.trunc) - 3} 段")
            self.trunc_l.setText("\n".join(lines)); self.trunc_lines = lines
            self.trunc_l.setToolTip("\n".join(f"{r}：{w:.1f}→{g:.1f} 秒" for r, w, g in self.trunc))
            v.addWidget(self.trunc_l)
        self.bad_idx = [i for i, _, _ in bad]
        if bad:
            # R73：檔名自成一行（完整，太長才中間省略），原因放下一行、可以換行——長原因不再把檔名擠成「VID_2…2.mp4」
            self.fail_box = QVBoxLayout(); self.fail_box.setSpacing(2); v.addLayout(self.fail_box)
            self.fail_l = prop(QLabel(f"{len(bad)} 個片段失敗："), err=True); self.fail_box.addWidget(self.fail_l)
            self.fail_l.ensurePolished(); fm = self.fail_l.fontMetrics(); self.fail_name_w = 470
            self.fail_rows = []
            for _, r, e in bad[:3]:
                nl = prop(QLabel("• " + fm.elidedText(os.path.basename(r), Qt.ElideMiddle, self.fail_name_w - fm.horizontalAdvance("• "))),
                          err=True)
                nl.setWordWrap(False); nl.setToolTip(r)
                rl = prop(QLabel("　" + zh_reason(e or "")), sec=True, small=True); rl.setWordWrap(True)
                rl.setContentsMargins(12, 0, 0, 4)
                self.fail_box.addWidget(nl); self.fail_box.addWidget(rl); self.fail_rows.append((nl, rl))
            if len(bad) > 3:
                self.fail_box.addWidget(prop(QLabel(f"…另 {len(bad) - 3} 個（滑鼠移到上方標題看全部）"), sec=True, small=True))
            self.fail_lines = [self.fail_l.text()] + [t for nl, rl in self.fail_rows for t in (nl.text(), rl.text())]
            self.fail_l.setToolTip("\n".join(f"{r}：{zh_reason(e or '')}" for _, r, e in bad))
            fr = QHBoxLayout(); v.addLayout(fr); fr.addStretch(1)
            self.retry_b = prop(QPushButton(f"重試失敗的 {len(bad)} 個"), link=True); fr.addWidget(self.retry_b)
            self.retry_b.clicked.connect(lambda: (self.accept(), self.retry.emit(self.bad_idx)))
        h = QHBoxLayout(); v.addLayout(h); h.addStretch(1)
        self.close_b = QPushButton("關閉"); self.again_b = QPushButton("再匯出一次")
        self.reveal_b = prop(QPushButton(reveal_label()), primary=True)
        for b in (self.close_b, self.again_b, self.reveal_b):
            h.addWidget(b)
        self.close_b.clicked.connect(self.accept)
        self.again_b.clicked.connect(lambda: (self.accept(), self.again.emit()))
        self.reveal_b.clicked.connect(self.do_reveal)
        self.reveal_b.setEnabled(bool(self.ok_paths) or os.path.isdir(folder))
        self.reveal_b.setDefault(True)

    def do_reveal(self):
        self.revealed = reveal(self.ok_paths[0] if self.ok_paths else self.folder)
        self.accept()


class PreviewDialog(QDialog):
    """「預覽選取」：依序看已勾選的片段（← → 切換）。items: [(標題, proxy, thumb)]。"""
    def __init__(self, parent, items, autoplay=True):
        super().__init__(parent); self.setWindowTitle("預覽選取"); self.items = items; self.i = 0
        from .widgets import FrameView
        v = QVBoxLayout(self); self.view = FrameView(640, 360); v.addWidget(self.view)
        self.autoplay = autoplay
        h = QHBoxLayout(); v.addLayout(h)
        self.prev_b = QPushButton("← 上一段"); self.lab = QLabel(""); self.next_b = QPushButton("下一段 →")
        self.close_b = QPushButton("關閉")
        h.addWidget(self.prev_b); h.addWidget(self.lab, 1); h.addWidget(self.next_b); h.addWidget(self.close_b)
        self.prev_b.clicked.connect(lambda: self.go(-1)); self.next_b.clicked.connect(lambda: self.go(1))
        self.close_b.clicked.connect(self.accept)
        self.go(0)

    def go(self, d):
        if not self.items:
            self.lab.setText("沒有已選片段"); return
        self.i = max(0, min(len(self.items) - 1, self.i + d))
        t, proxy, thumb = self.items[self.i]
        self.view.set_thumb(thumb)
        if proxy:
            self.view.set_source(proxy, autoplay=self.autoplay, muted=False, lazy=False)
        self.lab.setText(f"{self.i + 1}/{len(self.items)} · {t}")
        self.prev_b.setEnabled(self.i > 0); self.next_b.setEnabled(self.i < len(self.items) - 1)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Left, Qt.Key_Right):
            self.go(-1 if e.key() == Qt.Key_Left else 1); return
        super().keyPressEvent(e)

    def done(self, r):
        self.view.stop(); super().done(r)
