"""卡片牆、迷你預覽、時間軸、提示。"""
import os
from PySide6.QtCore import Qt, QUrl, Signal, QTimer, QSize
from PySide6.QtGui import QPixmap, QImage, QKeySequence
from PySide6.QtWidgets import (QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QWidget, QGridLayout,
                               QListWidget, QListWidgetItem, QAbstractItemView, QSizePolicy)
from .style import prop, key

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink
except Exception:  # noqa: BLE001
    QMediaPlayer = None


STRAT_COLORS = {"start": "#2f3d55", "middle": "#3b3550", "people": "#1f4a3a", "action": "#5a3020", "whole": "#4a4020"}


def fmt(t):
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


_THUMBS = {}


def _thumb_pix(path, w, h):
    """R71：縮圖快取（路徑＋mtime＋尺寸）。重建卡片牆（切策略、重算候選）時不必每張重新解碼與縮放。"""
    try:
        k = (path, os.path.getmtime(path), w, h)
    except OSError:
        k = (path, 0, w, h)
    pm = _THUMBS.get(k)
    if pm is None:
        if len(_THUMBS) > 3000:
            _THUMBS.clear()
        pm = _THUMBS[k] = QPixmap(path).scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return pm


class FrameView(QLabel):
    """用 QVideoSink 把影格畫進 QLabel（離螢幕截圖也看得到畫面）；靜音、無限循環。"""

    def __init__(self, w=192, h=108, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, h)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background:#000;border-radius:4px")
        self.player = None
        self._src = None
        self._thumb = None

    def set_thumb(self, path):
        self._thumb = path
        if path and os.path.exists(path):
            self.setPixmap(_thumb_pix(path, self.width(), self.height()))

    def set_size(self, w, h):
        if (w, h) != (self.width(), self.height()):
            self.setFixedSize(w, h)
            if self._thumb and not self.player:
                self.set_thumb(self._thumb)

    def play(self):
        """R63：延遲建立播放器——卡片捲進畫面才開解碼器。"""
        if self.player is None and self._src:
            self.set_source(self._src, autoplay=True, lazy=False)
        elif self.player and self.player.playbackState() != QMediaPlayer.PlayingState:
            self.player.play()

    def pause(self):
        if self.player and self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()

    def set_source(self, path, autoplay=True, loop=True, muted=True, lazy=True):
        self._src = path
        if not (QMediaPlayer and path and os.path.exists(path)):
            return
        if lazy and self.player is None:
            return                      # 由主視窗依可見範圍呼叫 play()
        if self.player is None:
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.audio.setMuted(muted)
            self.player.setAudioOutput(self.audio)
            self.sink = QVideoSink(self)
            self.player.setVideoSink(self.sink)
            self.sink.videoFrameChanged.connect(self._frame)
        if loop:
            self.player.setLoops(QMediaPlayer.Infinite)
        self.player.setSource(QUrl.fromLocalFile(path))
        if autoplay:
            self.player.play()

    def _frame(self, fr):
        img = fr.toImage()
        if not img.isNull():
            self.setPixmap(QPixmap.fromImage(img).scaled(self.size(), Qt.KeepAspectRatio, Qt.FastTransformation))

    def stop(self):
        if self.player:
            self.player.stop()


class ClipCard(QFrame):
    toggled = Signal(int, bool)
    trim = Signal(int)
    activated = Signal(object)          # 取得焦點（roving tabindex）
    nav = Signal(object, str)           # 方向鍵移動
    locked = Signal(int, bool)          # L 鍵／鎖頭按鈕：換一批時保留

    def __init__(self, clip, vname, autoplay=True, enabled=None):
        super().__init__()
        from .clips import chip_keys, chip_html
        from app.core import STRAT_NAMES as _SN
        self.setObjectName("card")
        self.cid = clip["id"]
        self.on = bool(clip["checked"])
        self.ai = False
        self.lock = bool(clip.get("locked"))
        self.setFocusPolicy(Qt.StrongFocus)
        lay = QVBoxLayout(self); lay.setContentsMargins(6, 6, 6, 6); lay.setSpacing(4)
        self.view = FrameView()
        self.view.set_thumb(clip.get("thumb"))
        lay.addWidget(self.view)
        dur = clip["end"] - clip["start"]
        # R69：長度疊在預覽右下角
        self.dur = QLabel(f"{dur:.1f} 秒", self.view); self.dur.setObjectName("dur")
        self.dur.setStyleSheet("background:rgba(0,0,0,0.75);color:#FFFFFF;font-size:12px;border-radius:4px;padding:1px 5px")
        self.dur.adjustSize()
        self.chk = QLabel(self.view); self.chk.setFixedSize(26, 26); self.chk.setAlignment(Qt.AlignCenter); self.chk.move(6, 6)
        row = QHBoxLayout()
        self.lab = QLabel(f"{fmt(clip['start'])} – {fmt(clip['end'])}")
        prop(self.lab, small=True)
        self.badge = QLabel("AI 相符"); self.badge.setStyleSheet("color:#CFE3FF;background:#1f3350;border-radius:4px;padding:0 4px;font-size:12px")
        self.badge.hide()
        self.low = QLabel("")          # R69：SPEC 移除「較平淡」徽章（保留屬性相容舊程式）
        self.low.hide(); self.is_low = False
        row.addWidget(self.lab, 1); row.addWidget(self.badge)
        lay.addLayout(row)
        # 策略 chip：只顯示目前有開的策略，最多 2 個＋「+N」
        self.strategies = chip_keys(clip, enabled)
        self.stratl = QLabel(chip_html(self.strategies))
        self.stratl.setTextFormat(Qt.RichText)
        self.stratl.setObjectName("strategy")
        self.stratl.setStyleSheet("font-size:12px")
        self.stratl.setAccessibleName("策略 " + "、".join(_SN[k] for k in self.strategies))
        self.stratl.setToolTip("、".join(_SN[k] for k in self.strategies))
        self.stratl.setVisible(bool(self.strategies)); lay.addWidget(self.stratl)
        self.also = prop(QLabel(""), sec=True, small=True); self.also.hide(); lay.addWidget(self.also)
        import json as _j
        self.tags = _j.loads(clip.get("tags") or "[]")
        self.tagl = QLabel("  ".join("#" + t for t in self.tags)); self.tagl.setObjectName("tags")
        self.tagl.setStyleSheet("color:#E0E0E0;font-size:12px")
        self.tagl.setVisible(bool(self.tags)); lay.addWidget(self.tagl)
        br = QHBoxLayout(); br.setSpacing(6)
        self.btrim = QPushButton("微調"); self.btrim.setFocusPolicy(Qt.NoFocus)   # 用 Enter 開啟，不佔 Tab
        self.btrim.clicked.connect(lambda: self.trim.emit(self.cid))
        self.block = QPushButton(); self.block.setFocusPolicy(Qt.NoFocus)
        self.block.clicked.connect(self.toggle_lock)
        br.addWidget(self.btrim); br.addWidget(self.block); br.addStretch(1)
        lay.addLayout(br)
        self.name = f"{vname} {fmt(clip['start'])} 到 {fmt(clip['end'])}，{dur:.1f} 秒" + \
            (("，標籤 " + "、".join(self.tags)) if self.tags else "") + \
            (("，策略 " + "、".join(_SN[k] for k in self.strategies)) if self.strategies else "")
        self.setToolTip("空白鍵勾選，Enter 微調，L 鎖定（重算候選時保留），Home 到影片名稱")
        self._paint()
        if clip.get("proxy"):
            self.view.set_source(clip["proxy"], autoplay=autoplay)

    def set_also(self, names):
        self.also.setText("也在：" + "、".join(names) if names else ""); self.also.setVisible(bool(names))

    def _paint(self):
        self.chk.setText("✓" if self.on else "")
        self.chk.setStyleSheet("border-radius:6px;font-weight:700;font-size:16px;" +
                               ("background:#FFC400;color:#111" if self.on else "border:2px solid #FFFFFF;background:rgba(0,0,0,0.55)"))
        prop(self, on=self.on)
        self.block.setText("已鎖定" if self.lock else "鎖定")
        self.block.setStyleSheet("color:#FFC400;border-color:#FFC400" if self.lock else "")
        self.block.setToolTip("已鎖定：改策略重算時保留（L）" if self.lock else "鎖定：改策略重算時保留（L）")
        self.block.setAccessibleName("解除鎖定" if self.lock else "鎖定")
        self.setAccessibleName(("已勾選 " if self.on else "未勾選 ") + ("已鎖定 " if self.lock else "") + self.name)

    def set_width(self, w):
        """R63：卡片寬度跟著欄寬（預覽 16:9）。"""
        self.setFixedWidth(w)
        vw = w - 12; vh = int(vw * 9 / 16); self.view.set_size(vw, vh)
        self.dur.adjustSize(); self.dur.move(vw - self.dur.width() - 6, vh - self.dur.height() - 6)

    def set_tags(self, tags_json):
        import json as _j
        self.tags = _j.loads(tags_json or "[]")
        self.tagl.setText("  ".join("#" + t for t in self.tags)); self.tagl.setVisible(bool(self.tags))
        base = self.name.split("，標籤 ")[0].split("，策略 ")[0]
        from app.core import STRAT_NAMES as _SN
        self.name = base + (("，標籤 " + "、".join(self.tags)) if self.tags else "") + \
            (("，策略 " + "、".join(_SN[k] for k in self.strategies)) if self.strategies else "")
        self._paint()

    def set_low(self, on):
        self.is_low = bool(on)

    def toggle_lock(self):
        self.lock = not self.lock
        if self.lock:
            self.on = True
        self._paint(); self.locked.emit(self.cid, self.lock)

    def set_on(self, on):
        self.on = on; self._paint()

    def set_ai(self, on):
        self.ai = on; self.badge.setVisible(on)

    def mousePressEvent(self, e):
        self.setFocus()
        self.set_on(not self.on); self.toggled.emit(self.cid, self.on)

    def mouseDoubleClickEvent(self, e):
        self.trim.emit(self.cid)

    def focusInEvent(self, e):
        self.activated.emit(self); super().focusInEvent(e)

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Space:
            self.set_on(not self.on); self.toggled.emit(self.cid, self.on); return
        if k == Qt.Key_L and not e.modifiers():
            self.toggle_lock(); return
        if k in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)):
            self.trim.emit(self.cid); return
        names = {Qt.Key_Left: "left", Qt.Key_Right: "right", Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Home: "home"}
        if k in names:
            self.nav.emit(self, names[k]); return
        super().keyPressEvent(e)


class GroupHeader(QWidget):
    def __init__(self, title, ext, status):
        super().__init__()
        h = QHBoxLayout(self); h.setContentsMargins(0, 8, 0, 4)
        self.tog = prop(QPushButton(f"▾ {title}"), tog=True)
        self.tog.setAccessibleName(f"{title}，{ext}")
        self.tog.setMinimumWidth(self.tog.fontMetrics().horizontalAdvance(self.tog.text()) + 24)
        self.ext = QLabel(ext); self.ext.setStyleSheet("font-size:12px;color:#DDD;background:transparent;border:1px solid #767676;border-radius:4px;padding:0 4px")
        self.st = prop(QLabel(status), sec=True, small=True)
        self.again = QPushButton("重新推薦")
        self.manual = QPushButton("＋ 手動新增片段")
        self.selall = QPushButton("本支全選"); self.selall.setAccessibleName(f"{title} 全選")
        self.again.hide()      # R69：改策略會自動重算；「重新推薦」留在程式裡但不顯示
        self.ext.setVisible(bool(ext))
        h.addWidget(self.tog); h.addWidget(self.ext); h.addWidget(self.st); h.addStretch(1)
        h.addWidget(self.again); h.addWidget(self.selall); h.addWidget(self.manual)
        self.buttons = [self.tog, self.selall, self.manual]
        self.manual.setAccessibleName("手動新增片段"); self.manual.setToolTip("手動新增片段")

    def compact(self, on):
        """窄的卡片牆：按鈕改短字（可及名稱與提示仍是完整文字），避免被裁切。"""
        self.manual.setText("＋ 手動" if on else "＋ 手動新增片段")
        self.st.setVisible(not on)


def short_name(n):
    """R63：時間軸用短名，VID_20240825_023257_349 → 08/25 02:32（完整檔名放 tooltip）。"""
    import re
    m = re.search(r"20\d\d(\d\d)(\d\d)_(\d\d)(\d\d)\d\d", n or "")
    return f"{m.group(1)}/{m.group(2)} {m.group(3)}:{m.group(4)}" if m else (n if len(n or "") <= 18 else n[:8] + "…" + n[-8:])


class Wall(QWidget):
    """整面卡片牆只佔一個 Tab 停留點：只有作用中的元件可用 Tab 進入（roving）。"""
    COLS = 3

    def __init__(self):
        super().__init__()
        self.lay = QVBoxLayout(self); self.lay.setContentsMargins(12, 8, 12, 12); self.lay.setSpacing(4)
        self.cards, self.headers, self.items = [], [], []
        self.active = None
        self._grids = []

    def set_cols(self, n, force=False):
        """依可用寬度重排欄數（不重建卡片）；被篩選掉的卡片不佔格子（R63）。"""
        n = max(1, n)
        if n == self.COLS and not force:
            return False
        self.COLS = n
        for g, cards in self._grids:
            shown = [c for c in cards if not getattr(c, "filtered", False)]
            sig = (n, tuple(id(c) for c in shown))
            if getattr(g, "_sig", None) == sig:     # R71：500+ 段時篩選沒變的組不重排（省掉整面 remove/add）
                continue
            g._sig = sig
            for c in cards:
                g.removeWidget(c)
            for i in range(g.columnCount()):
                g.setColumnStretch(i, 0)
            for c in cards:
                if c.isHidden() != bool(getattr(c, "filtered", False)):
                    c.setVisible(not getattr(c, "filtered", False))
            for i, c in enumerate(shown):
                g.addWidget(c, i // n, i % n)
            g.setColumnStretch(n, 1)
        return True

    def clear(self):
        for c in self.cards:
            c.view.stop()
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().hide()          # 先藏起來：deleteLater 要等事件迴圈，否則舊卡片會短暫疊在新卡片上
                it.widget().deleteLater()
        self.cards, self.headers, self.items = [], [], []
        self._grids = []

    def add_group(self, header, cards, extra=None):
        self.lay.addWidget(header)
        self.headers.append(header)
        for b in header.buttons:
            b.installEventFilter(self)
            self.items.append(b)
        box = QWidget(); g = QGridLayout(box); self._grids.append((g, cards)); g.setContentsMargins(0, 0, 0, 0); g.setSpacing(8)
        for i, c in enumerate(cards):
            g.addWidget(c, i // self.COLS, i % self.COLS)
            c.group = header; c.grid_idx = i; c.siblings = cards
            c.activated.connect(self._act); c.nav.connect(self._nav)
            self.cards.append(c); self.items.append(c)
        g.setColumnStretch(self.COLS, 1)
        g._sig = (self.COLS, tuple(id(c) for c in cards if not getattr(c, "filtered", False)))
        self.lay.addWidget(box)
        header.tog.clicked.connect(lambda _=False, b=box, h=header: self._fold(b, h))
        if extra:
            self.lay.addWidget(extra)

    def apply_filter(self, keep):
        """R63：500+ 片段時的篩選（keep(card)->bool）；整組都被濾掉時連標題一起藏。"""
        for c in self.cards:
            c.filtered = not keep(c)
        self.set_cols(self.COLS, force=True)
        for (g, cards), h in zip(self._grids, self.headers):
            vis = any(not c.filtered for c in cards) or not cards
            if h.isHidden() == vis:
                h.setVisible(vis)
            if g.parentWidget().isHidden() == vis and not getattr(h, "folded", False):
                g.parentWidget().setVisible(vis)
        return sum(1 for c in self.cards if not c.filtered)

    def _fold(self, box, h):
        box.setVisible(not box.isVisible())
        h.tog.setText(("▾ " if box.isVisible() else "▸ ") + h.tog.text()[2:])

    def finish(self):
        self.lay.addStretch(1)
        if self.active not in self.items:
            self.active = next((c for c in self.cards), self.items[0] if self.items else None)
        self._rove()

    def _rove(self):
        for w in self.items:
            w.setFocusPolicy(Qt.StrongFocus if w is self.active else Qt.ClickFocus)

    def _act(self, w):
        self.active = w; self._rove()

    def eventFilter(self, o, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.FocusIn and o in self.items:
            self._act(o)
        if e.type() == QEvent.KeyPress and o in self.items:
            d = {Qt.Key_Right: 1, Qt.Key_Down: 1, Qt.Key_Left: -1, Qt.Key_Up: -1}.get(e.key())
            if d:
                i = self.items.index(o); n = self.items[max(0, min(len(self.items) - 1, i + d))]
                n.setFocus(); return True
        return False

    def _nav(self, card, d):
        if d == "home":
            card.group.tog.setFocus(); return
        all_ = self.cards; i = all_.index(card)
        step = {"left": -1, "right": 1, "up": -self.COLS, "down": self.COLS}[d]
        n = all_[max(0, min(len(all_) - 1, i + step))]
        n.setFocus()


class Timeline(QListWidget):
    moved = Signal(list)
    removed = Signal(int)
    opened = Signal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName("timeline")
        self.setFlow(QListWidget.LeftToRight)
        self.setWrapping(False)
        self.setFixedHeight(84); self.setTextElideMode(Qt.ElideNone); self.setIconSize(QSize(64, 36))
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setAccessibleName("成品片段順序（" + key("⌘↑↓ 或 ⌥←→", "Ctrl+↑↓ 或 Alt+←→") + " 移動）")
        self.model().rowsMoved.connect(lambda *a: self.moved.emit(self.ids()))
        self.empty = QLabel("勾選上方的片段卡，就會依序加入這裡", self.viewport())
        prop(self.empty, sec=True); self.empty.move(12, 26)

    def ids(self):
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]

    def set_clips(self, clips, names):
        cur = self.currentRow()
        self.blockSignals(True); self.clear()
        for i, c in enumerate(clips, 1):
            full = names.get(c['file_id'], '')
            it = QListWidgetItem(f"{i}. {short_name(full)}  {fmt(c['start'])}・{c['end'] - c['start']:.1f}s")
            it.setToolTip(full)
            it.setData(Qt.UserRole, c["id"])
            # B8：依文字寬度給足空間（選取時邊框變粗也不會被截成「4....」）
            th = c.get("thumb")
            if th and os.path.exists(th):
                from PySide6.QtGui import QIcon
                it.setIcon(QIcon(QPixmap(th).scaled(64, 36, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)))
            it.setSizeHint(QSize(self.fontMetrics().horizontalAdvance(it.text()) + 44 + (72 if th else 0), 54))
            it.setData(Qt.AccessibleTextRole, f"第 {i} 段：{names.get(c['file_id'], '')} {fmt(c['start'])}")
            self.addItem(it)
        self.blockSignals(False)
        self.empty.setVisible(not clips)
        if clips:
            self.setCurrentRow(max(0, min(cur, len(clips) - 1)))

    def keyPressEvent(self, e):
        r = self.currentRow(); m = e.modifiers()
        moveup = (m & Qt.ControlModifier and e.key() == Qt.Key_Up) or (m & Qt.AltModifier and e.key() == Qt.Key_Left)
        movedn = (m & Qt.ControlModifier and e.key() == Qt.Key_Down) or (m & Qt.AltModifier and e.key() == Qt.Key_Right)
        if (moveup or movedn) and r >= 0:
            n = r - 1 if moveup else r + 1
            if 0 <= n < self.count():
                it = self.takeItem(r); self.insertItem(n, it); self.setCurrentRow(n)
                self.moved.emit(self.ids())
            return
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and r >= 0:
            self.removed.emit(self.item(r).data(Qt.UserRole)); return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and r >= 0 and not (m & Qt.ControlModifier):
            self.opened.emit(self.item(r).data(Qt.UserRole)); return
        super().keyPressEvent(e)


class Toast(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        h = QHBoxLayout(self); h.setContentsMargins(14, 8, 8, 8)
        self.lab = QLabel(); self.lab.setAccessibleName("通知")
        self.btn = QPushButton(); self.btn.hide()
        h.addWidget(self.lab); h.addWidget(self.btn)
        self.t = QTimer(self, singleShot=True, timeout=self.hide)
        self.hide()
        self._cb = None
        self.btn.clicked.connect(self._click)

    def _click(self):
        self.hide()
        if self._cb:
            self._cb()

    def show_msg(self, text, action=None, cb=None, ms=4000):
        self.lab.setText(text); self.lab.setWordWrap(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not action)   # R63：沒有按鈕時不擋點擊
        self.lab.setMaximumWidth(400)
        self.lab.setMinimumWidth(min(self.lab.fontMetrics().horizontalAdvance(text) + 4, 400))
        self.btn.setVisible(bool(action)); self.btn.setText(action or ""); self._cb = cb
        z = getattr(self, "zone", None); z = z() if z else None
        if z and z[1] - z[0] >= 220:          # R71：塞進匯出列的空白處，不蓋卡片
            left, right, top, bot = z
            bw = (self.btn.sizeHint().width() + 8) if action else 0
            w = min(560, right - left - 30 - bw)
            self.lab.setMaximumWidth(w); self.lab.setMinimumWidth(min(self.lab.fontMetrics().horizontalAdvance(text) + 4, w))
            self.adjustSize()
            self.move(max(left, right - self.width()), max(8, bot - 4 - self.height() if self.height() > bot - top - 6
                                                          else top + (bot - top - self.height()) // 2))
            self.show(); self.raise_(); self.t.start(ms); return
        self.adjustSize()
        p = self.parent()
        anchor = getattr(self, "anchor", None)      # R63：右下角、時間軸上緣之上（不蓋卡片中央與時間軸）
        y = (anchor() if anchor else p.height() - 210) - self.height() - 12
        x = p.width() - self.width() - 16
        rx = getattr(self, "right_limit", None)     # 有右欄時貼在右欄左側
        if rx:
            x = min(x, rx() - self.width() - 16)
        self.move(max(8, x), max(8, y))
        self.show(); self.raise_(); self.t.start(ms)


class StickerPad(QWidget):
    """R24：拖曳決定貼圖位置的小畫面（依輸出比例）。pos＝貼圖中心佔畫面比例 (fx, fy)。
    滑鼠拖曳或方向鍵（每次 2%）都能移動，方便沒有滑鼠的人。"""
    moved = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pos_f = (0.85, 0.15); self.emoji = "⭐"; self.ratio = 16 / 9; self.thumb = None
        self.others = []   # R28：已加入的其他貼圖 [(emoji, (fx, fy))]，半透明顯示、不能拖
        self.active = True
        self.setMinimumSize(160, 90); self.setFocusPolicy(Qt.StrongFocus); self.setCursor(Qt.OpenHandCursor)
        self.setAccessibleName("貼圖位置（拖曳或用方向鍵移動）")

    def set_ratio(self, r):
        self.ratio = r; self.update()

    CORNER_F = {"右上": (0.9, 0.1), "左上": (0.1, 0.1), "右下": (0.9, 0.84), "左下": (0.1, 0.84)}

    def set_thumb(self, path):
        """R28：背景改成實際畫面（時間軸第一個片段的縮圖）。"""
        from PySide6.QtGui import QPixmap
        pm = QPixmap(path) if path else None
        self.thumb = pm if pm is not None and not pm.isNull() else None
        self.update()

    def set_others(self, items):
        self.others = [(e, self.CORNER_F.get(p, p) if isinstance(p, str) else tuple(p)) for e, p in items]
        self.update()

    def set_emoji(self, e):
        self.emoji = e or "⭐"; self.update()

    def area(self):
        from PySide6.QtCore import QRectF
        w, h = self.width(), self.height()
        if w / h > self.ratio:
            aw, ah = h * self.ratio, h
        else:
            aw, ah = w, w / self.ratio
        return QRectF((w - aw) / 2, (h - ah) / 2, aw, ah)

    def set_pos(self, fx, fy):
        self.pos_f = (round(min(1, max(0, fx)), 3), round(min(1, max(0, fy)), 3))
        self.setAccessibleDescription(f"水平 {int(self.pos_f[0] * 100)}%，垂直 {int(self.pos_f[1] * 100)}%")
        self.update(); self.moved.emit(*self.pos_f)

    def _from_mouse(self, p):
        a = self.area()
        self.set_pos((p.x() - a.x()) / a.width(), (p.y() - a.y()) / a.height())

    def mousePressEvent(self, e):
        self._from_mouse(e.position()); self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if e.buttons():
            self._from_mouse(e.position())

    def mouseReleaseEvent(self, e):
        self.setCursor(Qt.OpenHandCursor)

    def keyPressEvent(self, e):
        d = {Qt.Key_Left: (-0.02, 0), Qt.Key_Right: (0.02, 0), Qt.Key_Up: (0, -0.02), Qt.Key_Down: (0, 0.02)}.get(e.key())
        if d:
            self.set_pos(self.pos_f[0] + d[0], self.pos_f[1] + d[1])
        else:
            super().keyPressEvent(e)

    def paintEvent(self, e):
        from PySide6.QtGui import QPainter, QColor, QFont
        p = QPainter(self); a = self.area()
        p.fillRect(a, QColor("#2a3340"))
        if self.thumb is not None:
            # 跟輸出一樣置中裁切填滿，不拉伸
            from PySide6.QtCore import QRect
            tw, th = self.thumb.width(), self.thumb.height()
            if tw / th > self.ratio:
                cw = int(th * self.ratio); src = QRect((tw - cw) // 2, 0, cw, th)
            else:
                ch = int(tw / self.ratio); src = QRect(0, (th - ch) // 2, tw, ch)
            p.drawPixmap(a.toRect(), self.thumb, src)
        p.setPen(QColor("#5aa9ff" if self.hasFocus() else "#667")); p.drawRect(a.adjusted(0, 0, -1, -1))
        s = min(a.width(), a.height()) * 0.16
        f = QFont(); f.setPixelSize(max(8, int(s * 0.8))); p.setFont(f)
        from PySide6.QtCore import QRectF
        p.setOpacity(0.55)
        for em, (ox, oy) in self.others:
            cx, cy = a.x() + a.width() * ox, a.y() + a.height() * oy
            p.drawText(QRectF(cx - s / 2, cy - s / 2, s, s), Qt.AlignCenter, em)
        p.setOpacity(1.0)
        if self.active:
            cx, cy = a.x() + a.width() * self.pos_f[0], a.y() + a.height() * self.pos_f[1]
            p.drawText(QRectF(cx - s / 2, cy - s / 2, s, s), Qt.AlignCenter, self.emoji)
        p.end()


class SpeedCurve(QWidget):
    """R26：手動速度曲線編輯器。5 個控制點，上下拖曳改速度（對數刻度 0.25–4 倍）。
    鍵盤：←→ 選點、↑↓ 調整（每次 ×1.25）、0 重設為原速。"""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        from app import smart
        self.U = smart.CURVE_U; self.vals = [1.0] * 5; self.sel = 2; self._drag = None
        self.setMinimumSize(320, 110); self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("速度曲線（←→ 選點，↑↓ 調整速度）"); self._desc()

    def curve(self):
        return None if all(abs(v - 1) < 1e-6 for v in self.vals) else list(self.vals)

    def set_curve(self, c):
        self.vals = list(c) if c else [1.0] * 5; self._desc(); self.update(); self.changed.emit()

    def _desc(self):
        self.setAccessibleDescription("、".join(f"{int(u * 100)}% {v:g} 倍" for u, v in zip(self.U, self.vals)))

    def _geom(self):
        m = 28; return m, 8, self.width() - m - 10, self.height() - 26

    def _y(self, v):
        import math
        x0, y0, w, h = self._geom(); return y0 + h * (1 - (math.log2(v) + 2) / 4)

    def _v(self, y):
        x0, y0, w, h = self._geom()
        from app import smart
        f = 1 - (y - y0) / h; return smart.clamp_speed(2 ** (f * 4 - 2))

    def _x(self, i):
        x0, y0, w, h = self._geom(); return x0 + w * self.U[i]

    def _set(self, i, v):
        from app import smart
        self.vals[i] = smart.clamp_speed(v); self.sel = i; self._desc(); self.update(); self.changed.emit()

    def mousePressEvent(self, e):
        p = e.position(); i = min(range(5), key=lambda k: abs(self._x(k) - p.x()))
        self._drag = i; self._set(i, self._v(p.y()))

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self._set(self._drag, self._v(e.position().y()))

    def mouseReleaseEvent(self, e):
        self._drag = None

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Left:
            self.sel = max(0, self.sel - 1); self.update()
        elif k == Qt.Key_Right:
            self.sel = min(4, self.sel + 1); self.update()
        elif k == Qt.Key_Up:
            self._set(self.sel, self.vals[self.sel] * 1.25)
        elif k == Qt.Key_Down:
            self._set(self.sel, self.vals[self.sel] / 1.25)
        elif k == Qt.Key_0:
            self._set(self.sel, 1.0)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, e):
        from PySide6.QtGui import QPainter, QColor, QPen
        from PySide6.QtCore import QPointF
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        x0, y0, w, h = self._geom()
        p.fillRect(int(x0), int(y0), int(w), int(h), QColor("#1f2630"))
        p.setPen(QColor("#8a94a3"))
        for v in (0.25, 0.5, 1, 2, 4):
            y = self._y(v); p.setPen(QPen(QColor("#3a4452" if v != 1 else "#6b7686"), 1)); p.drawLine(int(x0), int(y), int(x0 + w), int(y))
            p.setPen(QColor("#8a94a3")); p.drawText(2, int(y + 4), f"{v:g}×")
        from app import smart
        pts = [QPointF(x0 + w * i / 40, self._y(smart.curve_speed(self.vals, i / 40))) for i in range(41)]
        p.setPen(QPen(QColor("#ffc400"), 2))
        for a, b in zip(pts, pts[1:]):
            p.drawLine(a, b)
        for i in range(5):
            c = QPointF(self._x(i), self._y(self.vals[i]))
            p.setBrush(QColor("#ffc400" if i == self.sel else "#1f2630")); p.setPen(QPen(QColor("#ffc400"), 2))
            p.drawEllipse(c, 6 if i == self.sel and self.hasFocus() else 5, 6 if i == self.sel and self.hasFocus() else 5)
        p.setPen(QColor("#c9d1dc")); p.drawText(int(x0), int(y0 + h + 16), "開始")
        p.drawText(int(x0 + w - 24), int(y0 + h + 16), "結束")
        p.end()
