"""對話框：微調、刪除（垃圾桶／預覽檔／永久）、磁碟空間、輸出進度、完成、錯誤、設定、同意。"""
import os, shutil, subprocess, sys
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QRadioButton,
                               QDoubleSpinBox, QProgressBar, QTabWidget, QWidget, QFormLayout, QLineEdit,
                               QComboBox, QSpinBox, QFileDialog, QMessageBox, QSlider, QButtonGroup)
from .style import prop, PF, key
from .widgets import FrameView, fmt
from . import ai

FILEMGR = "Finder" if PF == "mac" else "檔案總管"
TRASH = "垃圾桶" if PF == "mac" else "資源回收筒"


def human(b):
    for u in ("B", "KB", "MB", "GB"):
        if b < 1024 or u == "GB":
            return f"{b:.0f} {u}" if u == "B" else f"{b:.1f} {u}"
        b /= 1024


def reveal(path):
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    elif os.name == "nt":
        subprocess.Popen(["explorer", "/select,", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def open_file(path):
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path])


def buttons(dlg, *specs):
    """specs: (文字, 角色, 回呼)；Windows 主要鈕在左、Mac 在右。"""
    h = QHBoxLayout(); h.addStretch(1)
    out = []
    for text, role, cb in specs:
        b = QPushButton(text)
        if role == "primary":
            prop(b, primary=True); b.setDefault(True)
        if role == "danger":
            prop(b, danger=True)
        b.clicked.connect(cb); out.append(b)
    order = out if PF == "mac" else list(reversed(out))
    for b in order:
        h.addWidget(b)
    return h, out


class Base(QDialog):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.setWindowTitle(title); self.setModal(True); self.setMinimumWidth(420)
        self.v = QVBoxLayout(self); self.v.setContentsMargins(20, 18, 20, 16); self.v.setSpacing(10)
        h = prop(QLabel(title), h=True); self.v.addWidget(h)

    def text(self, t, **kw):
        l = QLabel(t); l.setWordWrap(True); prop(l, **kw); self.v.addWidget(l); return l


class TrimDialog(Base):
    def __init__(self, parent, clip, duration, title="微調片段"):
        super().__init__(parent, title)
        self.clip = clip
        self.view = FrameView(480, 270); self.v.addWidget(self.view, 0, Qt.AlignCenter)
        if clip.get("proxy"):
            self.view.set_source(clip["proxy"], muted=False)
        f = QFormLayout()
        self.s = QDoubleSpinBox(); self.e = QDoubleSpinBox()
        for w in (self.s, self.e):
            w.setRange(0, max(0.1, duration)); w.setDecimals(1); w.setSingleStep(0.1); w.setSuffix(" 秒")
        self.s.setValue(clip["start"]); self.e.setValue(clip["end"])
        f.addRow("開始（I）", self.s); f.addRow("結束（O）", self.e); self.v.addLayout(f)
        # R26：手動速度曲線
        from app import smart
        from .widgets import SpeedCurve
        self.preset = QComboBox()
        for name in smart.SPEED_PRESETS:
            self.preset.addItem(name, name)
        self.preset.addItem("自訂", "自訂")
        self.curve = SpeedCurve()
        sp = clip.get("speed")
        if sp:
            import json
            self.curve.set_curve(json.loads(sp) if isinstance(sp, str) else sp)
            m = [k for k, v in smart.SPEED_PRESETS.items() if v == self.curve.vals]
            self.preset.setCurrentIndex(self.preset.findData(m[0] if m else "自訂"))
        self.preset.currentIndexChanged.connect(self._preset)
        self.curve.changed.connect(self._curve_info)
        f2 = QFormLayout(); f2.addRow("速度曲線", self.preset); self.v.addLayout(f2); self.v.addWidget(self.curve)
        self.curve_info = self.text("", sec=True, small=True); self._curve_info()
        self.s.valueChanged.connect(self._curve_info); self.e.valueChanged.connect(self._curve_info)
        # R40：魚眼水平校正（每段）。自動＝用相機重力感測（Insta360）；勾掉自動就用手動角度
        self.roll_auto = QCheckBox("自動"); self.roll = QDoubleSpinBox(); self.roll.setRange(-45, 45)
        self.roll.setSingleStep(1); self.roll.setSuffix("°"); self.roll.setAccessibleName("水平校正角度")
        r0 = clip.get("roll"); self.roll_auto.setChecked(r0 is None); self.roll.setValue(r0 or 0.0)
        self.roll.setEnabled(r0 is not None); self.roll_auto.toggled.connect(lambda on: self.roll.setEnabled(not on))
        hr = QHBoxLayout(); hr.addWidget(self.roll_auto); hr.addWidget(self.roll); hr.addStretch()
        f3 = QFormLayout(); f3.addRow("水平校正（魚眼）", hr); self.v.addLayout(f3)
        self.err = self.text("", err=True); self.err.hide()
        self.text("I／O 設定開始與結束；←→ 移動 0.1 秒", sec=True, small=True)
        h, (self.reset, self.cancel, self.ok) = buttons(
            self, ("還原 AI 建議", "", self._reset), ("取消", "", self.reject), ("完成", "primary", self._ok))
        self.reset.setEnabled(clip.get("ai_start") is not None)
        self.v.addLayout(h)
        self.result_range = None

    @property
    def result_roll(self):
        return None if self.roll_auto.isChecked() else float(self.roll.value())

    def keyPressEvent(self, e):
        pos = self.view.player.position() / 1000 + self.clip["start"] if self.view.player else None
        if e.key() == Qt.Key_I and pos is not None:
            self.s.setValue(pos); return
        if e.key() == Qt.Key_O and pos is not None:
            self.e.setValue(pos); return
        super().keyPressEvent(e)

    def _preset(self):
        from app import smart
        k = self.preset.currentData()
        if k != "自訂":
            self._applying = True; self.curve.set_curve(smart.SPEED_PRESETS[k]); self._applying = False

    def _curve_info(self):
        from app import smart
        c = self.curve.curve(); L = max(0.0, self.e.value() - self.s.value())
        out = smart.curve_length(self.s.value(), self.e.value(), c) if c else L
        self.curve_info.setText(f"原始 {L:.1f} 秒 → 輸出約 {out:.1f} 秒")
        if c and not getattr(self, "_applying", False):
            m = [k for k, v in smart.SPEED_PRESETS.items() if v == self.curve.vals]
            if not m and self.preset.currentData() != "自訂":
                self.preset.blockSignals(True); self.preset.setCurrentIndex(self.preset.findData("自訂")); self.preset.blockSignals(False)

    def _reset(self):
        self.s.setValue(self.clip["ai_start"]); self.e.setValue(self.clip["ai_end"])

    def _ok(self):
        if self.e.value() - self.s.value() < 0.5:
            self.err.setText("片段至少要 0.5 秒"); self.err.show(); return
        self.result_range = (self.s.value(), self.e.value()); self.result_curve = self.curve.curve()
        self.view.stop(); self.accept()

    def reject(self):
        self.view.stop(); super().reject()


class RemoveDialog(Base):
    """Delete 鍵：預設只從清單移除（可復原）。刪除原始檔是另一個按鈕。"""

    def __init__(self, parent, names):
        n = len(names)
        super().__init__(parent, f"要移除 {n} 支影片嗎？" if n > 1 else f"要移除「{names[0]}」嗎？")
        self.text(f"「從清單移除」不會動到檔案，可以用 {key('⌘Z', 'Ctrl+Z')} 復原。")
        self.choice = None
        h, (self.c, self.d, self.r) = buttons(
            self, ("取消", "", self.reject), ("丟到垃圾桶…", "danger", lambda: self._pick("delete")),
            ("從清單移除", "primary", lambda: self._pick("remove")))
        self.v.addLayout(h)

    def _pick(self, c):
        self.choice = c; self.accept()


class TrashDialog(Base):
    def __init__(self, parent, plan):
        n = plan["count"]
        super().__init__(parent, f"把 {n} 支影片移到{TRASH}？")
        lines = []
        for g in plan["groups"][:6]:
            exts = "、".join(sorted({os.path.splitext(p)[1][1:].upper() for p, _ in g["files"]}))
            lines.append(f"・{g['name']}（{exts}，{human(g['bytes'])}）")
        if n > 6:
            lines.append(f"・…還有 {n - 6} 支")
        self.text("\n".join(lines))
        self.text(f"共 {plan['file_count']} 個檔案、{human(plan['total_bytes'])}。可從{TRASH}還原。", sec=True)
        self.previews_only = QCheckBox("只刪除預覽檔（.lrv／.thm），保留原始檔")
        ok = any(g["previews_only_ok"] for g in plan["groups"])
        self.previews_only.setEnabled(ok)
        if not ok:
            self.previews_only.setToolTip("這些影片沒有另外的預覽檔")
        self.v.addWidget(self.previews_only)
        h, (_, self.go) = buttons(self, ("取消", "", self.reject), (f"移到{TRASH}", "danger", self.accept))
        self.previews_only.toggled.connect(lambda on: self.go.setText("刪除預覽檔" if on else f"移到{TRASH}"))
        self.v.addLayout(h)


class PermDialog(Base):
    """磁碟沒有垃圾桶：略過這些／永久刪除（須先勾確認）。"""

    def __init__(self, parent, plan):
        nt = len(plan["no_trash"])
        super().__init__(parent, f"{nt} 支影片無法移到{TRASH}")
        vols = "、".join(v for v in plan["no_trash_volumes"] if v) or "這個磁碟"
        self.text(f"它們在 {vols} 上，該磁碟沒有{TRASH}。刪除後將無法還原。")
        self.confirm = QCheckBox("我了解無法還原")
        self.v.addWidget(self.confirm)
        self.choice = None
        others = plan["count"] - nt
        specs = [("取消", "", self.reject)]
        if others:
            specs.append((f"略過這些，其餘 {others} 支照常移到{TRASH}", "", lambda: self._pick("skip")))
        specs.append(("永久刪除", "danger", lambda: self._pick("perm")))
        h, bs = buttons(self, *specs)
        self.perm = bs[-1]; self.skip = bs[1] if others else None
        self.perm.setEnabled(False)
        self.confirm.toggled.connect(self.perm.setEnabled)
        self.v.addLayout(h)

    def _pick(self, c):
        self.choice = c; self.accept()


class DiskDialog(Base):
    def __init__(self, parent, need, free, folder):
        super().__init__(parent, "磁碟空間可能不足")
        self.text(f"預估需要約 {human(need)}，「{folder}」所在的磁碟只剩 {human(free)}。")
        self.choice = None
        h, _ = buttons(self, ("取消", "", self.reject), ("換個位置…", "", lambda: self._pick("other")),
                       ("仍要輸出", "primary", lambda: self._pick("go")))
        self.v.addLayout(h)

    def _pick(self, c):
        self.choice = c; self.accept()


def eta_text(f, f0, elapsed):
    """剩餘時間估計：至少跑 3 秒且進度 > 5% 才顯示，避免一開始亂跳。"""
    done = f - f0
    if elapsed < 3 or f < 0.05 or done <= 0.01 or f >= 1:
        return ""
    left = elapsed * (1 - f) / done
    if left < 60:
        return f"　約剩 {max(1, round(left / 5) * 5)} 秒"
    return f"　約剩 {round(left / 60)} 分鐘"


class ProgressDialog(Base):
    cancel_req = Signal()

    def __init__(self, parent, title="正在產生成品"):
        super().__init__(parent, title)
        self.bar = QProgressBar(); self.bar.setRange(0, 1000); self.v.addWidget(self.bar)
        self.msg = self.text("準備中…", sec=True)
        self.msg.setAccessibleName("輸出進度")
        h, (self.cbtn,) = buttons(self, ("取消輸出", "", self._ask))
        self.v.addLayout(h)
        self.setMinimumWidth(420)

    def set(self, f, m):
        import time
        self.bar.setValue(int(f * 1000))
        now = time.monotonic()
        if not hasattr(self, "_t0") or f < getattr(self, "_f0", 0):
            self._t0, self._f0 = now, f
        self.msg.setText(f"{int(f * 100)}%　{m}{eta_text(f, self._f0, now - self._t0)}")

    def _ask(self):
        r = QMessageBox.question(self, "要取消輸出嗎？", "已完成的部分會被捨棄。",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r == QMessageBox.Yes:
            self.cbtn.setEnabled(False); self.msg.setText("正在取消…"); self.cancel_req.emit()

    def reject(self):
        self._ask()


class DoneDialog(Base):
    def __init__(self, parent, path):
        super().__init__(parent, "成品完成")
        self.text(os.path.basename(path)); self.text(os.path.dirname(path), sec=True, small=True)
        h, _ = buttons(self, ("關閉", "", self.accept), (f"顯示於 {FILEMGR}", "", lambda: reveal(path)),
                       ("播放", "primary", lambda: (open_file(path), self.accept())))
        self.v.addLayout(h)


class ErrorDialog(Base):
    def __init__(self, parent, title, msg, retry=True, friendly=True):
        super().__init__(parent, title)
        from app import core as _c
        self.raw = msg
        self.summary = self.text(_c.friendly_error(msg) if friendly else msg)
        self.retry = False
        specs = [("關閉", "", self.reject)]
        if friendly:
            from PySide6.QtWidgets import QPlainTextEdit
            self.detail = QPlainTextEdit(msg); self.detail.setReadOnly(True); self.detail.setMaximumHeight(140)
            self.detail.setAccessibleName("錯誤詳細資料"); self.detail.hide(); self.v.addWidget(self.detail)
            specs.insert(0, ("詳細資料", "", lambda: self.detail.setVisible(not self.detail.isVisible())))
        self.relocate = False
        low_disk = any(k in msg.lower() for k in ("no space", "空間不足", "disk full", "errno 28"))
        if low_disk:   # R63：空間不足時主要動作是改存到別處，重試降為次要
            self.summary.setText("磁碟空間不足。請清出空間，或改存到其他磁碟。")
            if retry:
                specs.append(("重試", "", self._r))
            specs.append(("改存到…", "primary", self._relocate))
        elif retry:
            specs.append(("重試", "primary", self._r))
        h, _ = buttons(self, *specs); self.v.addLayout(h)

    def _r(self):
        self.retry = True; self.accept()

    def _relocate(self):
        self.relocate = True; self.retry = True; self.accept()


class ConsentDialog(Base):
    """mode='consent'：首次開啟雲端 AI；mode='info'：之後只看說明。"""

    def __init__(self, parent, mode="consent"):
        super().__init__(parent, "雲端 AI 搜尋會上傳什麼？")
        self.text("・每個片段的 1 張縮圖（約 240 px 寬）與你輸入的搜尋文字\n"
                  "・不上傳影片、聲音或檔名\n・傳送給你在設定中填寫的服務，依該服務的資料政策處理\n"
                  "・不開啟時所有功能都在這台電腦上完成")
        if mode == "consent":
            h, _ = buttons(self, ("不要開啟", "", self.reject), ("同意並開啟", "primary", self.accept))
        else:
            h, _ = buttons(self, ("知道了", "primary", self.accept))
        self.v.addLayout(h)


class SettingsDialog(QDialog):
    """Mac：即時套用（只有「關閉」）。Windows：快照 + 確定／取消／套用；金鑰測試與刪除都要按套用或確定後才生效。"""
    applied = Signal()

    def __init__(self, parent, lib):
        super().__init__(parent)
        self.lib = lib
        self.setWindowTitle("偏好設定" if PF == "mac" else "設定")
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        self.tabs = QTabWidget(); v.addWidget(self.tabs)
        self.snap = self._read()
        self.pend_key = None     # 已測試成功、待套用的金鑰
        self.pend_del = False    # 待套用的刪除
        self._build()
        if PF == "mac":
            h, (self.close_b,) = buttons(self, ("關閉", "primary", self.accept))
        else:
            # Windows 慣例由左至右：確定 取消 套用（buttons() 在 Windows 會反轉順序）
            h, (self.apply_b, self.cancel_b, self.ok_b) = buttons(
                self, ("套用", "", self._apply), ("取消", "", self.reject), ("確定", "primary", self._ok))
            self.apply_b.setEnabled(False)
        v.addLayout(h)
        self._load(self.snap)
        for w in self._watch:
            sig = getattr(w, "toggled", None) or getattr(w, "valueChanged", None) or getattr(w, "currentIndexChanged", None) or w.textChanged
            sig.connect(self._changed)

    def _read(self):
        g = self.lib.get
        return {"out_dir": g("out_dir", os.path.expanduser("~/Movies" if PF == "mac" else "~/Videos")),
                "music_dir": g("music_dir", ""), "count": g("count", 2), "seg_len": g("seg_len", 6.5),
                "hw": g("hw_encode", True), "ai_on": g("ai_on", False), "ai_base": g("ai_base", ai.SERVICES["OpenAI 相容 API"]),
                "ai_model": g("ai_model", "gpt-4o-mini"), "key_ok": g("ai_key_ok", False)}

    def _build(self):
        t1 = QWidget(); f = QFormLayout(t1)
        self.out = QLineEdit(); b = QPushButton("選擇…"); b.clicked.connect(lambda: self._pick(self.out))
        r = QHBoxLayout(); r.addWidget(self.out); r.addWidget(b); f.addRow("成品存放位置", r)
        self.mus = QLineEdit(); b2 = QPushButton("選擇…"); b2.clicked.connect(lambda: self._pick(self.mus))
        r2 = QHBoxLayout(); r2.addWidget(self.mus); r2.addWidget(b2); f.addRow("音樂資料夾", r2)
        self.hw = QCheckBox("用顯示卡加速輸出（較快，畫質略低）"); f.addRow("", self.hw)
        self.tabs.addTab(t1, "一般")
        t2 = QWidget(); f2 = QFormLayout(t2)
        self.cnt = QSpinBox(); self.cnt.setRange(1, 12); f2.addRow("每支影片推薦幾段", self.cnt)
        self.sl = QDoubleSpinBox(); self.sl.setRange(1.5, 15); self.sl.setSuffix(" 秒"); f2.addRow("每段長度", self.sl)
        self.tabs.addTab(t2, "推薦")
        t3 = QWidget(); f3 = QFormLayout(t3)
        self.ai_on = QCheckBox("開啟雲端 AI 搜尋（選用）"); f3.addRow("", self.ai_on)
        info = prop(QPushButton("會上傳什麼？"), link=True); info.clicked.connect(lambda: ConsentDialog(self, "info").exec())
        f3.addRow("", info)
        self.base = QLineEdit(); f3.addRow("服務網址", self.base)
        self.model = QLineEdit(); f3.addRow("模型", self.model)
        self.key = QLineEdit(); self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("已儲存（不顯示）" if ai.get_key() else "貼上 API 金鑰")
        f3.addRow("API 金鑰", self.key)
        r3 = QHBoxLayout(); self.test_b = QPushButton("測試連線"); self.del_b = prop(QPushButton("刪除儲存的金鑰"), danger=True)
        r3.addWidget(self.test_b); r3.addWidget(self.del_b); r3.addStretch(1); f3.addRow("", r3)
        self.kst = QLabel(""); self.kst.setWordWrap(True); self.kst.setAccessibleName("金鑰狀態"); f3.addRow("", self.kst)
        if not ai.has_keyring():
            self.kst.setText("這台電腦缺少 keyring 套件，無法安全儲存金鑰；雲端 AI 停用。")
            for w in (self.key, self.test_b, self.del_b):
                w.setEnabled(False)
        self.test_b.clicked.connect(self._test); self.del_b.clicked.connect(self._del)
        self.ai_on.toggled.connect(self._consent)
        self.tabs.addTab(t3, "雲端 AI")
        t4 = QWidget(); f4 = QVBoxLayout(t4)
        self.csz = QLabel(); f4.addWidget(self.csz)
        self.keep = QCheckBox("保留勾選與微調"); self.keep.setChecked(True); f4.addWidget(self.keep)
        cb = QPushButton("清除快取"); cb.clicked.connect(self._clear); f4.addWidget(cb, 0, Qt.AlignLeft)
        f4.addWidget(prop(QLabel(f"快取位置：{self.lib.cache_dir}"), sec=True, small=True)); f4.addStretch(1)
        self.tabs.addTab(t4, "快取")
        self._csz()
        self._watch = [self.out, self.mus, self.hw, self.cnt, self.sl, self.ai_on, self.base, self.model]

    def _csz(self):
        self.csz.setText(f"預覽與縮圖快取：{human(self.lib.cache_size())}")

    def _clear(self):
        self.lib.clear_cache(self.keep.isChecked()); self._csz()

    def _pick(self, le):
        d = QFileDialog.getExistingDirectory(self, "選擇資料夾", le.text())
        if d:
            le.setText(d)

    def _load(self, s):
        self.out.setText(s["out_dir"]); self.mus.setText(s["music_dir"]); self.hw.setChecked(s["hw"])
        self.cnt.setValue(s["count"]); self.sl.setValue(s["seg_len"])
        self.ai_on.blockSignals(True); self.ai_on.setChecked(s["ai_on"]); self.ai_on.blockSignals(False)
        self.base.setText(s["ai_base"]); self.model.setText(s["ai_model"])

    def _cur(self):
        return {"out_dir": self.out.text(), "music_dir": self.mus.text(), "hw": self.hw.isChecked(),
                "count": self.cnt.value(), "seg_len": self.sl.value(), "ai_on": self.ai_on.isChecked(),
                "ai_base": self.base.text(), "ai_model": self.model.text()}

    def _staging(self):
        return PF != "mac"

    def _changed(self, *_):
        if self._staging():
            self.apply_b.setEnabled(True)
        else:
            self._write()

    def _consent(self, on):
        if on and not self.lib.get("ai_consent", False):
            if ConsentDialog(self).exec() != QDialog.Accepted:
                self.ai_on.blockSignals(True); self.ai_on.setChecked(False); self.ai_on.blockSignals(False); return
            self.lib.set("ai_consent", True)

    def _test(self):
        k = self.key.text().strip() or ai.get_key()
        self.kst.setText("測試中…"); self.kst.repaint()
        try:
            ai.test_key(self.base.text(), k)
        except ai.AIError as e:
            self.kst.setText(f"✕ {e}"); self.kst.setStyleSheet("color:#FF9C9C"); return
        self.kst.setStyleSheet("color:#8FD18F")
        if self._staging():
            self.pend_key, self.pend_del = k, False
            self.kst.setText("✓ 連線成功（按「套用」或「確定」後生效）"); self.apply_b.setEnabled(True)
        else:
            ai.save_key(k); self.lib.set("ai_key_ok", True); self.kst.setText("✓ 連線成功"); self.applied.emit()

    def _del(self):
        if self._staging():
            self.pend_del, self.pend_key = True, None
            self.kst.setText("將在按「套用」或「確定」時刪除儲存的金鑰"); self.kst.setStyleSheet("")
            self.apply_b.setEnabled(True)
        else:
            ai.delete_key(); self.lib.set("ai_key_ok", False); self.kst.setText("已刪除儲存的金鑰"); self.applied.emit()

    def _commit_key(self):
        if self.pend_del:
            ai.delete_key(); self.lib.set("ai_key_ok", False)
        elif self.pend_key:
            ai.save_key(self.pend_key); self.lib.set("ai_key_ok", True)
        self.pend_key, self.pend_del = None, False

    def _write(self):
        c = self._cur(); s = self.lib.set
        s("out_dir", c["out_dir"]); s("music_dir", c["music_dir"]); s("hw_encode", c["hw"])
        s("count", c["count"]); s("seg_len", c["seg_len"]); s("ai_on", c["ai_on"])
        s("ai_base", c["ai_base"]); s("ai_model", c["ai_model"])
        self.applied.emit()

    def _apply(self):
        self._write(); self._commit_key(); self.snap = self._read(); self.apply_b.setEnabled(False)

    def _ok(self):
        self._apply(); self.accept()

    def reject(self):
        if self._staging():
            self.pend_key, self.pend_del = None, False   # 取消：丟棄所有待套用的變更
        super().reject()
