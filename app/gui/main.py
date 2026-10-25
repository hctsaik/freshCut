"""主視窗：左側影片清單、中間卡片牆（循環靜音迷你預覽）、右側成品設定、底部時間軸。"""
import os, sys, shutil
from PySide6.QtCore import Qt, QTimer, QThreadPool
from PySide6.QtGui import QKeySequence, QShortcut, QAction
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QListWidget, QListWidgetItem, QLineEdit, QScrollArea, QComboBox, QSpinBox, QSlider,
                               QCheckBox, QStackedWidget, QFileDialog, QFrame, QDialog, QToolBar, QSizePolicy,
                               QAbstractItemView, QDoubleSpinBox)
from app import core
from app.library import Library, watch_interval, STATUS_DONE, STATUS_PENDING, STATUS_CHANGED
from .style import QSS, PF, prop, key
from .widgets import ClipCard, GroupHeader, Wall, Timeline, Toast, StickerPad, fmt
from .workers import Job, analyze_job, export_job, manual_job, trim_job, ai_job, tag_job, brief_job
from app import convenience as CV
from . import dialogs as D, ai

VIDEO_FILTER = "影片 (*.mp4 *.mov *.m4v *.insv *.lrv *.avi *.mkv *.MP4 *.MOV *.INSV *.LRV)"
TARGETS = [("15 秒", 15), ("30 秒", 30), ("60 秒", 60), ("不限", 0), ("自訂…", -1)]
ASPECTS = [("橫式 16:9", "16:9"), ("直式 9:16（Reels、Shorts）", "9:16"), ("方形 1:1", "1:1")]
STYLES = [("自訂", ""), ("Vlog", "Vlog"), ("運動", "運動"), ("旅行", "旅行")]
FRAMES = [("跟著主體（直式/方形）", "smart"), ("置中裁切", "center")]
PROJ = [("自動偵測（360／魚眼）", "auto"), ("一般影片", ""), ("360 全景（等距）", "equirect"), ("360 雙魚眼 .insv", "dfisheye"), ("單一圓形魚眼", "fisheye")]


def _uniform_only(c):
    """R70：只有「均勻取樣」選到的片段（保底），卡片排最後、預設不勾。"""
    import json as _j
    try:
        st = _j.loads(c.get("strategy") or "[]")
    except (ValueError, TypeError):
        return False
    return c.get("source") == "ai" and set(st or []) == {"uniform"}


class Main(QMainWindow):
    def __init__(self, root=None, autoplay=True):
        super().__init__()
        from .style import apply
        apply(QApplication.instance())
        self.lib = Library(root)
        self.root = self.lib.root
        self.autoplay = autoplay
        self.pool = QThreadPool.globalInstance()
        self.jobs = []
        self.cur_fid = None
        self.cards = {}
        self.ai_hits = set()
        self.setWindowTitle("精華剪輯")
        self.resize(1360, 860)
        # R70：明確的最小尺寸——否則版面把「右欄 320」也算進最小寬度，視窗縮不到 1280 以下、抽屜永遠出不來
        self.setMinimumSize(1000, 640)
        self._build()
        self._shortcuts()
        self.toast = Toast(self.centralWidget())
        # R63：toast 在右下角、時間軸上緣之上、右欄左側（外部審查：不可遮內容）
        cw = self.centralWidget
        self.toast.anchor = lambda: (self.ebar.mapTo(cw(), self.ebar.rect().topLeft()).y()
                                     if self.ebar.isVisible() else cw().height() - 60)
        # R71：toast 放進底部匯出列中間的空白處（摘要／進度右側、按鈕左側），不再蓋到卡片
        def _zone():
            if not (hasattr(self, "ebar") and self.ebar.isVisible()):
                return None
            eb = self.ebar; o = eb.mapTo(cw(), eb.rect().topLeft())
            lw = eb.prog_l if eb.prog_l.isVisible() else eb.summary
            left = o.x() + lw.geometry().right() + 12
            rb = eb.reason if (eb.reason.isVisible() and eb.reason.text()) else eb.prev_b
            right = o.x() + rb.geometry().left() - 12
            return left, right, o.y(), o.y() + eb.height()
        self.toast.zone = _zone
        self.toast.right_limit = lambda: (self.rscroll.mapTo(cw(), self.rscroll.rect().topLeft()).x()
                                          if self.rscroll.isVisible() else cw().width())
        self.watch = QTimer(self, timeout=self._watch_tick); self.watch.start(watch_interval() * 1000)
        self.devwatch = CV.DeviceWatcher()
        self.dev_t = QTimer(self, timeout=self._device_tick); self.dev_t.start(3000)
        self._refine = {}
        self.load_prefs()
        self._tpl_list()
        self.refresh()
        if not self.lib.get("tip_seen"):
            QTimer.singleShot(800, self._first_tip)
        if self.lib.needs_analysis():
            self.analyze()
        elif self.tags_stale():
            QTimer.singleShot(1500, self.start_tagging)   # R29：標籤器升級後，開啟時在背景重貼

    # ---------- 版面 ----------
    def _build(self):
        tb = QToolBar("工具列"); tb.setMovable(False); self.addToolBar(tb); self.top_bar = tb
        self.a_files = QAction("匯入影片…", self, triggered=self.import_files)
        self.a_folder = QAction("匯入資料夾…", self, triggered=self.import_folder)
        self.a_set = QAction("偏好設定…" if PF == "mac" else "設定", self, triggered=self.open_settings)
        self.a_auto = QAction("一鍵成片", self, triggered=lambda: self.one_click())
        self.a_shuffle = QAction("換一批", self, triggered=self.reshuffle)
        self.a_shuffle.setToolTip("保留鎖定（🔒）的片段，其餘重新挑一批不同的畫面")
        self.a_auto.setToolTip("選一個資料夾，自動分析、挑片段、對拍、輸出；之後仍可修改")
        tb.addAction(self.a_auto); tb.addAction(self.a_shuffle); tb.addAction(self.a_files); tb.addAction(self.a_folder)
        sp = QWidget(); sp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred); tb.addWidget(sp)
        self.aiq = QLineEdit(); self.aiq.setPlaceholderText("🔍 找片段，例如「海邊」「小孩笑」"); self.aiq.setFixedWidth(280)
        self.aiq.setAccessibleName("AI 搜尋片段"); self.aiq.returnPressed.connect(self.ai_search)
        self.brief = QLineEdit(); self.brief.setFixedWidth(300); self.brief.setClearButtonEnabled(True)
        self.brief.setPlaceholderText("一句話成片：例如「30秒直式海邊，小孩笑，熱血」")
        self.brief.setAccessibleName("一句話成片"); self.brief.returnPressed.connect(lambda: self.run_brief())
        self.brief.setToolTip("離線解析長度、比例、節奏、主題（海邊/小孩/笑…）、音樂氣氛，按 Enter 直接成片；設定中開啟雲端 AI 時會用雲端理解")
        tb.addWidget(self.brief)
        tb.addWidget(self.aiq); tb.addAction(self.a_set)

        self.stack = QStackedWidget(); self.setCentralWidget(self.stack)
        # 歡迎頁
        wel = QWidget(); wel.setObjectName("root"); wo = QVBoxLayout(wel); wo.addStretch(1)
        drop = QFrame(); drop.setObjectName("dropzone"); drop.setMaximumWidth(720); drop.setMinimumHeight(300)
        wh = QHBoxLayout(); wh.addStretch(1); wh.addWidget(drop, 4); wh.addStretch(1); wo.addLayout(wh); wo.addStretch(2)
        wv = QVBoxLayout(drop); wv.setContentsMargins(32, 28, 32, 28); wv.addStretch(1)
        ic = QLabel("⬇"); ic.setAlignment(Qt.AlignCenter); ic.setStyleSheet("font-size:44px;color:#FFC400"); wv.addWidget(ic)
        t = prop(QLabel("把 Insta360 資料夾或影片拖到這裡"), h=True); t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet("font-size:20px;font-weight:700"); wv.addWidget(t)
        steps = prop(QLabel("① 匯入 → ② AI 幫每支挑 2–4 段候選 → ③ 勾選喜歡的 → ④ 每段各自匯出成一個檔案"), sec=True)
        steps.setAlignment(Qt.AlignCenter); steps.setWordWrap(True); wv.addWidget(steps)
        s = prop(QLabel("會自動挑出精彩片段；檔案不會被修改。Insta360 的 .insv／.lrv 會合併成一支。"), sec=True)
        s.setAlignment(Qt.AlignCenter); wv.addWidget(s)
        r = QHBoxLayout(); r.addStretch(1)
        b0 = prop(QPushButton("一鍵成片（選資料夾）…"), primary=True); b0.clicked.connect(lambda: self.one_click())
        b1 = QPushButton("匯入影片…"); b1.clicked.connect(self.import_files)
        b2 = QPushButton("匯入資料夾…"); b2.clicked.connect(self.import_folder)
        self.welcome_auto, self.welcome_steps = b0, steps
        r.addWidget(b0); r.addWidget(b1); r.addWidget(b2); r.addStretch(1); wv.addSpacing(10); wv.addLayout(r); wv.addStretch(1)
        self.welcome_btn = b1
        self.stack.addWidget(wel)

        body = QWidget(); body.setObjectName("root"); self.stack.addWidget(body)
        V = QVBoxLayout(body); V.setContentsMargins(0, 0, 0, 0); V.setSpacing(0)
        H = QHBoxLayout(); H.setSpacing(0); V.addLayout(H, 1)
        # 左：影片清單
        left = QFrame(); left.setObjectName("panel"); left.setFixedWidth(250); lv = QVBoxLayout(left)
        self.search = QLineEdit(); self.search.setPlaceholderText("搜尋檔名"); self.search.setAccessibleName("搜尋影片")
        self.search.textChanged.connect(self._filter); lv.addWidget(self.search)
        self.vlist = QListWidget(); self.vlist.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.vlist.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.vlist.setTextElideMode(Qt.ElideMiddle)
        self.vlist.setWordWrap(False); self.vlist.setAccessibleName("影片清單"); self.vlist.currentItemChanged.connect(self._pick_video)
        self.vlist.installEventFilter(self); lv.addWidget(self.vlist, 1)
        self.watch_lab = prop(QLabel(""), sec=True, small=True); self.watch_lab.setWordWrap(True); lv.addWidget(self.watch_lab)
        # R32：依拍攝日/旅程分組
        self.trip_l = prop(QLabel("依拍攝日／旅程"), sec=True, small=True); lv.addWidget(self.trip_l)
        self.trip_c = QComboBox(); self.trip_c.setAccessibleName("拍攝日或旅程"); lv.addWidget(self.trip_c)
        self.trip_b = prop(QPushButton("用這組做影片"), accent2=True); self.trip_b.clicked.connect(lambda: self.make_trip())
        self.trip_b.setToolTip("只用這一天／這趟旅程的影片一鍵成片（鎖定的片段仍保留）"); lv.addWidget(self.trip_b)
        self.trips = []; self._trip_key = None
        H.addWidget(left)
        # 中：卡片牆
        mid = QWidget(); mv = QVBoxLayout(mid); mv.setContentsMargins(0, 0, 0, 0)
        self.banner = QFrame(); self.banner.setObjectName("banner"); bl = QHBoxLayout(self.banner)
        self.banner_lab = QLabel(""); self.banner_bar = QLabel(""); bl.addWidget(self.banner_lab, 1)
        self.banner_cancel = QPushButton("停止分析"); self.banner_cancel.clicked.connect(self._stop_analyze); bl.addWidget(self.banner_cancel)
        self.banner.hide(); mv.addWidget(self.banner)
        self.aierr = QFrame(); self.aierr.setObjectName("aierr"); al = QHBoxLayout(self.aierr)
        self.aierr_lab = QLabel(""); self.aierr_btn = QPushButton("前往設定"); self.aierr_btn.clicked.connect(self.open_settings)
        al.addWidget(self.aierr_lab, 1); al.addWidget(self.aierr_btn); self.aierr.hide(); mv.addWidget(self.aierr)
        # R31：插入記憶卡/相機
        self.devbar = QFrame(); self.devbar.setObjectName("banner"); dl = QHBoxLayout(self.devbar)
        self.dev_lab = QLabel(""); self.dev_lab.setWordWrap(True); dl.addWidget(self.dev_lab, 1)
        self.dev_import = prop(QPushButton("匯入並分析"), primary=True); self.dev_import.clicked.connect(lambda: self.import_device())
        self.dev_auto = QPushButton("匯入並一鍵成片"); self.dev_auto.clicked.connect(lambda: self.import_device(auto=True))
        self.dev_skip = QPushButton("這次略過"); self.dev_skip.clicked.connect(lambda: (self.devbar.hide(), setattr(self, "_dev", None)))
        for b in (self.dev_import, self.dev_auto, self.dev_skip):
            dl.addWidget(b)
        self.devbar.hide(); mv.addWidget(self.devbar); self._dev = None
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFocusPolicy(Qt.NoFocus); self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        # R63：篩選列（重度使用者 500+ 段）：共 N 段・已選 M，可只看已勾選／未勾選／較平淡／AI 命中
        fb = QHBoxLayout(); fb.setContentsMargins(12, 6, 12, 0)
        self.count_l = prop(QLabel(""), sec=True, small=True)
        self.filt = QComboBox(); self.filt.setAccessibleName("篩選片段")
        for t, k in (("全部片段", ""), ("只看已勾選", "on"), ("只看未勾選", "off"), ("只看較平淡", "low"), ("只看 AI 找到的", "ai")):
            self.filt.addItem(t, k)
        self.filt.currentIndexChanged.connect(lambda _: self._apply_filter())
        self.fold_b = QPushButton("全部收合"); self.fold_b.clicked.connect(self._fold_all)
        fb.addWidget(self.count_l, 1); fb.addWidget(self.filt); fb.addWidget(self.fold_b)
        self.filter_bar = QWidget(); self.filter_bar.setLayout(fb); mv.addWidget(self.filter_bar)
        self.wall = Wall(); self.scroll.setWidget(self.wall); mv.addWidget(self.scroll, 1)
        # R63：只播放看得到的預覽（500+ 片段時不會同時開 500 個解碼器）
        self._play_t = QTimer(self, singleShot=True, interval=120, timeout=self._update_playback)
        self.scroll.verticalScrollBar().valueChanged.connect(lambda *_: self._play_t.start())
        H.addWidget(mid, 1)
        # 右：成品設定
        right = QFrame(); right.setObjectName("panel"); rv = QVBoxLayout(right)
        rscroll = QScrollArea(); rscroll.setWidgetResizable(True); rscroll.setFixedWidth(300); rscroll.setFocusPolicy(Qt.NoFocus)
        rscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); rscroll.setWidget(right)
        rv.addWidget(prop(QLabel("成品設定"), h=True))

        def row(lbl, w):
            l = QLabel(lbl); l.setBuddy(w); rv.addWidget(l); rv.addWidget(w); return w
        # R35：我的範本
        self.tpl_c = row("我的範本", QComboBox()); self.tpl_c.setAccessibleName("我的範本")
        tb2 = QHBoxLayout(); rv.addLayout(tb2)
        self.tpl_save = QPushButton("存成範本…"); self.tpl_del = QPushButton("刪除範本")
        tb2.addWidget(self.tpl_save); tb2.addWidget(self.tpl_del)
        self.tpl_save.clicked.connect(lambda: self.save_template()); self.tpl_del.clicked.connect(lambda: self.delete_template())
        self.tpl_c.activated.connect(lambda i: self.apply_template(self.tpl_c.itemData(i)))
        # R34：剪完後調整
        rv.addWidget(prop(QLabel("用一句話微調成品"), sec=True, small=True))
        rv.addWidget(prop(QLabel("已鎖定的片段不會被換掉"), sec=True, small=True))
        self.refine_e = QLineEdit(); self.refine_e.setPlaceholderText("例如：短一點、換首歌")
        self.refine_e.setAccessibleName("調整指令"); self.refine_e.returnPressed.connect(lambda: self.refine(self.refine_e.text()))
        rv.addWidget(self.refine_e)
        from PySide6.QtWidgets import QGridLayout
        rg = QGridLayout(); rg.setSpacing(4); rv.addLayout(rg); self.refine_btns = {}
        for i, t in enumerate(CV.REFINES[:6]):
            b = QPushButton(t); b.clicked.connect(lambda _=False, t=t: self.refine(t)); rg.addWidget(b, i // 3, i % 3)
            self.refine_btns[t] = b
        self.share = row("分享到", QComboBox()); self.share.addItem("不指定", "")
        for k in core.SHARE_PRESETS:
            self.share.addItem(k, k)
        self.share.setToolTip("一次設定比例、解析度、建議長度與音量標準化（-14 LUFS）")
        self.theme = row("主題標籤", QComboBox()); self.theme.addItem("不指定", "")
        for t in ("海", "山", "雪", "夜景", "人物", "寵物"):
            self.theme.addItem(t, t)
        self.theme.setToolTip("一鍵成片／換一批時優先挑有這個標籤的片段（需安裝本機 CLIP，見 requirements-clip.txt）")
        self.target = row("成品長度", QComboBox())
        for t, v in TARGETS:
            self.target.addItem(t, v)
        self.target.setCurrentIndex(1)
        self.cust = QSpinBox(); self.cust.setRange(5, 600); self.cust.setValue(45); self.cust.setSuffix(" 秒")
        self.cust.setAccessibleName("自訂長度（秒）"); rv.addWidget(self.cust); self.cust.hide()
        self.cust_err = prop(QLabel(""), err=True); self.cust_err.setWordWrap(True); rv.addWidget(self.cust_err); self.cust_err.hide()
        self.aspect = row("畫面比例", QComboBox())
        for t, v in ASPECTS:
            self.aspect.addItem(t, v)
        fr = QHBoxLayout(); rv.addWidget(prop(QLabel("同時輸出其他比例"), sec=True, small=True)); rv.addLayout(fr)
        self.fmt_c = {}
        for a, t in (("16:9", "16:9"), ("9:16", "9:16"), ("1:1", "1:1")):
            c = QCheckBox(t); c.setToolTip(f"按「產生成品」時也輸出 {t} 版（檔名加 _{CV.FORMAT_SUFFIX[a]}）"); fr.addWidget(c); self.fmt_c[a] = c
        self.res = row("解析度", QComboBox()); self.res.addItem("1080p", "1080p"); self.res.addItem("4K（較慢）", "4K")
        self.look_c = row("濾鏡", QComboBox())
        from app import core as _c
        for k in _c.LOOKS:
            self.look_c.addItem(k or "原色", k)
        self.lut_b = QPushButton("匯入 LUT（.cube）…"); self.lut_b.setToolTip("匯入相機或調色軟體的 3D LUT，會加入濾鏡清單")
        self.lut_b.clicked.connect(lambda: self.import_lut()); rv.addWidget(self.lut_b)
        self.auto_col = QCheckBox("自動調色（偏暗、灰濛時修正）"); self.auto_col.setChecked(True); rv.addWidget(self.auto_col)
        self.look_prev = QLabel("選片段後顯示濾鏡預覽"); self.look_prev.setAlignment(Qt.AlignCenter)
        self.look_prev.setMinimumHeight(120); self.look_prev.setAccessibleName("濾鏡預覽")
        self.look_prev.setStyleSheet("border:1px solid #444;border-radius:6px;color:#aaa"); rv.addWidget(self.look_prev)
        self._prev_t = QTimer(self); self._prev_t.setSingleShot(True); self._prev_t.setInterval(250)
        self._prev_t.timeout.connect(self.update_look_preview)
        self.look_c.currentIndexChanged.connect(self._prev_t.start); self.auto_col.toggled.connect(self._prev_t.start)
        self.keep_audio = QCheckBox("保留原始聲音"); self.keep_audio.setChecked(True); rv.addWidget(self.keep_audio)
        self.fade = QCheckBox("結尾淡出"); self.fade.setChecked(True); rv.addWidget(self.fade)
        # R63：進階設定（AI 剪輯／文字／特效／貼圖）預設收合，右欄從 ~45 個控制項降到 ~20 個；有非預設值時自動展開
        self.adv_b = QPushButton("進階設定 ▸（AI 剪輯、文字、特效、貼圖）"); self.adv_b.setCheckable(True)
        self.adv_b.setAccessibleName("顯示或隱藏進階設定"); rv.addSpacing(6); rv.addWidget(self.adv_b)
        self.adv = QWidget(); rv.addWidget(self.adv); _rv_basic = rv
        rv = QVBoxLayout(self.adv); rv.setContentsMargins(0, 0, 0, 0)
        self.adv.hide(); self.adv_b.toggled.connect(self._toggle_adv)
        rv.addSpacing(8); rv.addWidget(prop(QLabel("AI 剪輯（離線）"), h=True))
        self.style_c = row("風格範本", QComboBox())
        for t, v in STYLES:
            self.style_c.addItem(t, v)
        self.slowmo = QCheckBox("精彩瞬間慢動作"); rv.addWidget(self.slowmo)
        self.frame_c = row("構圖", QComboBox())
        for t, v in FRAMES:
            self.frame_c.addItem(t, v)
        self.proj = row("360 素材", QComboBox())
        for t, v in PROJ:
            self.proj.addItem(t, v)
        self.title_e = row("片頭標題（可留空）", QLineEdit()); self.title_e.setPlaceholderText("例如：墾丁三日")
        self.date_c = QCheckBox("片頭加上拍攝日期"); rv.addWidget(self.date_c)
        self.tstyle = row("文字效果", QComboBox())
        for t in core.TITLE_STYLES:
            self.tstyle.addItem(t, t)
        self.tanim = row("文字動畫", QComboBox())
        for t in core.TITLE_ANIMS:
            self.tanim.addItem(t, t)
        self.fx = row("特效模板", QComboBox())
        for t in core.EFFECTS:
            self.fx.addItem({"": "無", "節拍放大": "節拍放大（跟著強拍）", "閃白": "閃白", "故障": "故障（輕微）"}[t], t)
        self.fx.setToolTip("在剪接點觸發")
        # R29：特效預覽條（觸發前／觸發／0.05 秒後／0.15 秒後）
        self.fx_preview = QLabel(); self.fx_preview.setAccessibleName("特效預覽"); self.fx_preview.hide()
        self.fx_preview.setScaledContents(True); self.fx_preview.setFixedHeight(54)
        from PySide6 import QtWidgets as _QW
        self.fx_preview.setSizePolicy(_QW.QSizePolicy.Ignored, _QW.QSizePolicy.Fixed); self.fx_preview.setMinimumWidth(1)   # 不要被 774px 的原圖撐寬
        rv.addWidget(self.fx_preview)
        self.fx.currentIndexChanged.connect(self._fx_preview)
        self.sticker = row("貼圖（全片顯示）", QComboBox()); self.sticker.addItem("無", "")
        from app import smart as _sm
        for e in _sm.STICKERS:
            self.sticker.addItem(e, e)
        self.sticker_pos = row("貼圖位置", QComboBox())
        for t in core.STICKER_POS:
            self.sticker_pos.addItem(t, t)
        self.sticker_pos.addItem("自訂（拖曳）", "custom")
        self.sticker_pad = StickerPad(); rv.addWidget(self.sticker_pad); self.sticker_pad.hide()
        self.sticker_anim = row("貼圖動畫", QComboBox())
        for t in core.STICKER_ANIMS:
            self.sticker_anim.addItem(t, t)
        self.sticker_pos.setEnabled(False); self.sticker_anim.setEnabled(False)
        # R28：多張貼圖。「加入」把目前這張存進清單；輸出＝清單＋目前選的這張。
        self.sticker_list = QListWidget(); self.sticker_list.setMaximumHeight(72)
        self.sticker_list.setAccessibleName("已加入的貼圖"); rv.addWidget(self.sticker_list)
        sb = QHBoxLayout(); rv.addLayout(sb)
        self.sticker_add = QPushButton("＋ 加入這張貼圖"); self.sticker_del = QPushButton("移除選取")
        sb.addWidget(self.sticker_add); sb.addWidget(self.sticker_del)
        self.sticker_add.clicked.connect(self._sticker_add); self.sticker_del.clicked.connect(self._sticker_del)
        self.stickers = []
        self.sticker_pad.moved.connect(self._sticker_dragged)
        self.sticker.currentIndexChanged.connect(self._sticker_state)
        self.sticker_pos.currentIndexChanged.connect(self._sticker_state)
        self._sticker_state()
        rv = _rv_basic
        rv.addStretch(1)
        H.addWidget(rscroll); self.rscroll = rscroll; self._drawer_open = False
        self.style_c.currentIndexChanged.connect(lambda: self.apply_style(self.style_c.currentData()))
        self.share.currentIndexChanged.connect(lambda: self.apply_share(self.share.currentData()))
        for w in (self.target, self.cust):
            (w.currentIndexChanged if w is self.target else w.valueChanged).connect(self._target_changed)
        # 下：時間軸
        bot = QFrame(); bot.setObjectName("panel"); bv = QVBoxLayout(bot); bv.setContentsMargins(12, 6, 12, 10)
        hdr = QHBoxLayout(); self.tl_title = prop(QLabel("成品順序"), h=True); hdr.addWidget(self.tl_title)
        self.skip_keys = prop(QLabel(key("⌥⌘T 跳到時間軸", "Ctrl+Alt+T 跳到時間軸") + "　" +
                                     key("⌘↑↓ 移動", "Ctrl+↑↓ 移動") + "　Delete 移除"), sec=True, small=True)
        hdr.addWidget(self.skip_keys); hdr.addStretch(1); bv.addLayout(hdr)
        self.tl = Timeline(); bv.addWidget(self.tl)
        self.tl.moved.connect(self._reorder); self.tl.removed.connect(lambda cid: self.toggle(cid, False))
        self.tl.opened.connect(self.trim)
        f = QHBoxLayout()
        self.summary = QLabel(""); self.summary.setAccessibleName("成品摘要"); f.addWidget(self.summary, 1)
        self.reason = prop(QLabel(""), sec=True); f.addWidget(self.reason)
        self.prev_b = QPushButton("預覽成品"); self.prev_b.clicked.connect(lambda: self.export(preview=True))
        self.exp_b = prop(QPushButton("產生成品"), primary=True); self.exp_b.clicked.connect(lambda: self.export())
        self.drawer_b = QPushButton("成品設定 ▸"); self.drawer_b.setCheckable(True)
        self.drawer_b.setAccessibleName("顯示或隱藏成品設定"); self.drawer_b.toggled.connect(self._toggle_drawer)
        self.drawer_b.hide(); f.addWidget(self.drawer_b)
        f.addWidget(self.prev_b); f.addWidget(self.exp_b); bv.addLayout(f)
        V.addWidget(bot); self.legacy_bot = bot
        self._H, self._V, self._mv = H, V, mv
        self.setAcceptDrops(True)
        self._build_clips()

    NARROW = 1280   # R69：視窗比這窄時，右側「匯出設定」收成抽屜（SPEC §3）

    def _build_clips(self):
        """R69：只輸出片段（SPEC）。舊的成片介面（音樂、轉場、時間軸、一鍵成片）藏起來，函式保留。"""
        from .clips import StrategyBar, ExportPanel, ExportBar
        tb = self.top_bar
        for a in tb.actions():
            if a in (self.a_auto, self.a_shuffle) or tb.widgetForAction(a) is self.brief:
                a.setVisible(False)
        self.aiq.returnPressed.disconnect()
        self.aiq.setPlaceholderText("🔍 找片段（檔名、日期）"); self.aiq.setAccessibleName("找片段（檔名、日期）")
        self.aiq.setClearButtonEnabled(True)
        self.aiq.textChanged.connect(lambda _: self._apply_filter())
        self.welcome_auto.hide(); self.dev_auto.hide()
        self.welcome_steps.setText("① 匯入 → ② 依剪片策略找出候選片段 → ③ 勾選喜歡的 → ④ 每段各自匯出成一個檔案")
        for w in (self.trip_l, self.trip_c, self.trip_b):
            w.hide()
        # 策略列
        self.strat_bar = StrategyBar(); self.strat_bar.set_cfg(self.lib.strategy_cfg())
        self.strat_bar.changed.connect(self._strategy_changed)
        self._mv.insertWidget(self._mv.indexOf(self.filter_bar), self.strat_bar)
        # 第二列：顯示 全部/已勾選/未勾選、依影片/依策略、全部收合、本頁全選、計數
        fb = self.filter_bar.layout()
        while fb.count():
            it = fb.takeAt(0)
            if it.widget():
                it.widget().setParent(None)
        self.filt.clear()
        for t, k in (("全部", ""), ("已勾選", "on"), ("未勾選", "off")):
            self.filt.addItem(t, k)
        self.filt.hide(); self.filt.setParent(self.filter_bar)
        from PySide6.QtWidgets import QButtonGroup
        def seg(names, cb, acc):
            box = QWidget(); h = QHBoxLayout(box); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(0)
            grp = QButtonGroup(box); grp.setExclusive(True); out = []
            for i, t in enumerate(names):
                b = QPushButton(t); b.setCheckable(True); b.setAccessibleName(f"{acc}：{t}")
                b.setStyleSheet("QPushButton{border-radius:0;padding:4px 10px}QPushButton:checked{background:#3d3520;color:#FFE08A;border-color:#FFC400}")
                b.setMinimumWidth(b.fontMetrics().horizontalAdvance(t) + 24)   # R70：窄視窗不可被擠扁
                grp.addButton(b, i); h.addWidget(b); out.append(b)
            out[0].setChecked(True); grp.idClicked.connect(cb); return box, out
        fb.addWidget(prop(QLabel("顯示"), sec=True, small=True))
        box, self.show_btns = seg(["全部", "已勾選", "未勾選"], lambda i: self.filt.setCurrentIndex(i), "顯示")
        fb.addWidget(box); fb.addSpacing(8)
        box, self.group_btns = seg(["依影片", "依策略"], self._set_group, "分組")
        fb.addWidget(box); fb.addSpacing(8)
        self.group_mode = "video"
        fb.addWidget(self.fold_b)
        self.selall_b = QPushButton("本頁全選"); self.selall_b.setToolTip("勾選目前顯示的所有片段（Ctrl+A）")
        self.selall_b.clicked.connect(self.select_visible); fb.addWidget(self.selall_b)
        for b in (self.fold_b, self.selall_b):
            b.setMinimumWidth(b.sizeHint().width())
        fb.addStretch(1); self.count_l.setTextFormat(Qt.RichText); fb.addWidget(self.count_l)
        # 右欄：匯出設定
        self.legacy_rscroll = self.rscroll; self.legacy_rscroll.hide()
        self.exp_panel = ExportPanel(); self.exp_panel.set_state(self.lib.get("clip_export") or {})
        es = QScrollArea(); es.setWidgetResizable(True); es.setFixedWidth(320); es.setFocusPolicy(Qt.NoFocus)
        es.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); es.setWidget(self.exp_panel)
        self._H.addWidget(es); self.rscroll = es
        # R70：窄視窗（< NARROW）右欄收成 48px 圖示條，點一下展開 320px 抽屜
        self.dstrip = QFrame(); self.dstrip.setObjectName("panel"); self.dstrip.setFixedWidth(48)
        self.dstrip.setStyleSheet("QFrame#panel{border-left:1px solid #3a3a3a}")
        dv = QVBoxLayout(self.dstrip); dv.setContentsMargins(4, 8, 4, 8)
        self.strip_b = QPushButton("⚙"); self.strip_b.setCheckable(True); self.strip_b.setFixedSize(40, 40)
        self.strip_b.setToolTip("匯出設定"); self.strip_b.setAccessibleName("顯示或隱藏匯出設定")
        self.strip_b.setStyleSheet("QPushButton{font-size:18px;border-radius:6px}QPushButton:checked{background:#3d3520;color:#FFE08A;border:1px solid #FFC400}")
        dv.addWidget(self.strip_b); dv.addStretch(1); self.dstrip.hide()
        self._H.addWidget(self.dstrip)
        self.exp_panel.changed.connect(self._export_settings_changed)
        # 底部匯出列
        self.legacy_bot.hide()
        self.legacy = {"summary": self.summary, "reason": self.reason, "prev_b": self.prev_b, "exp_b": self.exp_b,
                       "drawer_b": self.drawer_b}
        self.ebar = ExportBar(); self._V.addWidget(self.ebar)
        self.summary, self.reason, self.prev_b, self.exp_b = self.ebar.summary, self.ebar.reason, self.ebar.prev_b, self.ebar.exp_b
        self.drawer_b = self.strip_b; self.drawer_b.toggled.connect(self._toggle_drawer)
        self.exp_b.clicked.connect(lambda: self.cancel_export() if self._exp_job else self.export_clips())
        self.strat_bar.tip_closed.connect(lambda: self.lib.set("uniform_tip_seen", 1))
        if not self.lib.get("uniform_tip_seen") and self.lib.strategy_cfg().get("uniform", {}).get("on"):
            self.strat_bar.tip.show()
        self.prev_b.clicked.connect(self.preview_selected)
        self.ebar.cancel_b.clicked.connect(self.cancel_export)
        self._exp_job = None; self._rc_job = None; self._rc_pending = False

    # ---------- R69：策略 ----------
    def _strategy_changed(self, cfg):
        self.lib.set_strategy_cfg(cfg)
        self._build_wall(); self._summary()          # 關掉的策略立刻不再顯示 chip
        self._recompute()

    def _recompute(self):
        if self._rc_job or getattr(self, "_an_job", None):
            self._rc_pending = True; return
        self._rc_pending = False
        if not any(f["status"] == STATUS_DONE for f in self.lib.files()):
            return
        self.banner.show(); self.banner_cancel.hide(); self.banner_lab.setText("依新的剪片策略重算候選片段…")
        from .workers import recompute_job
        self._rc_job = self.run_job(recompute_job, self.root, None, done=self._recomputed,
                                    failed=lambda m: (self._recomputed(None), self._job_failed(m)),
                                    cancelled=lambda: self._recomputed(None),
                                    progress=lambda f, m: self.banner_lab.setText(f"依新的剪片策略重算候選片段：{m}"))

    def _recomputed(self, _):
        self._rc_job = None
        if self._rc_pending:
            self._recompute(); return
        self.banner.hide(); self.banner_cancel.show(); self.refresh()
        self.toast.show_msg("已依新的剪片策略更新候選（已勾選、鎖定、微調過的片段都保留）", ms=4000)

    def _strategy_counts(self):
        from .clips import chip_keys
        en = self.lib.enabled_strategies(); n = {}
        for c in self.lib.clip_rows():
            for k in chip_keys(c, en):
                n[k] = n.get(k, 0) + 1
        return n

    def _set_group(self, i):
        self.group_mode = ["video", "strategy"][i]; self._build_wall()

    def _set_many(self, cids, on=True):
        for cid in cids:
            self.lib.set_checked(cid, on)
            for c in self._dups.get(cid, []):
                c.set_on(on)
        self._timeline(); self._apply_filter()

    def select_visible(self):
        """本頁全選（Ctrl+A）：勾選目前篩選後看得到的片段。"""
        self._set_many([c.cid for c in self.wall.cards if not getattr(c, "filtered", False) and not c.on])

    def _ctrl_a(self):
        from PySide6.QtWidgets import QLineEdit as _LE, QAbstractSpinBox as _SB
        fw = QApplication.focusWidget()
        if isinstance(fw, _LE):
            fw.selectAll(); return
        if isinstance(fw, _SB):
            fw.selectAll(); return
        self.select_visible()

    # ---------- R69：匯出片段 ----------
    def _export_settings_changed(self):
        self.lib.set("clip_export", self.exp_panel.state()); self._summary()

    def _export_items(self):
        en = self.lib.enabled_strategies()
        out = []
        for seg, st in self.lib.timeline_clip_items():
            ks = [k for k in (core.strat_key(x) for x in st) if k == "manual" or k in en]
            out.append((seg, ks))
        out.sort(key=lambda it: (it[0].path, it[0].start))
        return out

    def export_clips(self, only=None, folder=None, on_done=None):
        from .clips import est_mb
        import time
        if self._exp_job:
            return None
        items = self._export_items() if only is None else only
        if not items:
            return None
        folder = folder or self.exp_panel.folder(); co = self.exp_panel.options()
        try:
            os.makedirs(folder, exist_ok=True)
            free = shutil.disk_usage(folder).free
        except OSError as e:
            D.ErrorDialog(self, "無法寫入輸出資料夾", f"{folder}\n{e}", retry=False).open(); return None
        need = est_mb(sum(s.end - s.start for s, _ in items), co) * 1.1e6
        if free < need:
            D.ErrorDialog(self, "磁碟空間不足", f"約需 {need / 1e6:.0f} MB，{folder} 只剩 {free / 1e6:.0f} MB。"
                          "請換一個輸出資料夾或改成較小的格式。", retry=False).open(); return None
        self._exp_items, self._exp_folder, self._exp_t0 = items, folder, time.time()
        self._exp_rels = core.plan_clip_names(items, co)
        self.ebar.busy(True); self.ebar.prog_l.setText(f"匯出中 0/{len(items)}")
        self._lock_settings(True)
        self._summary()
        from .workers import export_clips_job
        self._exp_job = self.run_job(export_clips_job, items, folder, co, progress=self._exp_progress,
                                     done=lambda r: self._exp_done(r, on_done),
                                     cancelled=lambda: self._exp_end(None, on_done, cancelled=True),
                                     failed=lambda m: (self._exp_end(None, on_done), self._job_failed(m)))
        self._summary()                      # R70：主按鈕變「取消匯出」
        return self._exp_job

    def _exp_progress(self, f, m):
        import time
        n = len(self._exp_items); i = min(n, int(round(f * n)))
        el = time.time() - self._exp_t0
        left = f"剩約 {int(el / f * (1 - f)) // 60}:{int(el / f * (1 - f)) % 60:02d}" if f > 0.02 else "估算中…"
        self.ebar.prog.setValue(int(f * 1000))
        if not getattr(self, "_cancelling", False):
            self.ebar.prog_l.setText(f"匯出中 {i}/{n} · {left}")

    def cancel_export(self):
        if self._exp_job:
            self._exp_job.cancelled = True; self._cancelling = True
            self.ebar.cancel_b.setEnabled(False); self.ebar.prog_l.setText("正在取消…（已完成的檔案會保留）")
            self.exp_b.setEnabled(False); self.exp_b.setText("正在取消…")

    def _lock_settings(self, on):
        """R70：匯出中右欄設定、策略列都不可改（改了也不會影響正在跑的匯出）。"""
        for wdg in (self.exp_panel, self.strat_bar):
            wdg.setEnabled(not on)
            wdg.setToolTip("匯出中無法修改設定" if on else "")

    def _exp_end(self, res, on_done, cancelled=False):
        self._exp_job = None; self._cancelling = False; self.ebar.busy(False); self._lock_settings(False); self._summary()
        if cancelled:
            self.toast.show_msg("已取消匯出：已完成的片段保留，沒有留下未完成的檔案，也沒有動到原有的檔案", ms=6000)
        if on_done:
            on_done(res)

    def _exp_done(self, res, on_done):
        import time
        from .clips import ExportDoneDialog
        items, folder = self._exp_items, self._exp_folder
        dlg = ExportDoneDialog(self, res, self._exp_rels, folder, time.time() - self._exp_t0)
        dlg.retry.connect(lambda idx: self.export_clips(only=[items[i] for i in idx], folder=folder))
        dlg.again.connect(lambda: self.export_clips())
        self.done_dlg = dlg
        self._exp_end(res, on_done)
        dlg.open()

    def preview_selected(self):
        from .clips import PreviewDialog
        from app.library import group_name
        rows = [c for c in self.lib.timeline() if os.path.exists(c["path"])]
        rows.sort(key=lambda c: (c["path"], c["start"]))
        items = [(f"{group_name(c['path'])} {fmt(c['start'])}–{fmt(c['end'])}", c.get("proxy"), c.get("thumb")) for c in rows]
        self.preview_dlg = PreviewDialog(self, items, autoplay=self.autoplay); self.preview_dlg.open()
        return self.preview_dlg

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and getattr(self, "_drawer_open", False) and hasattr(self, "dstrip"):
            self.drawer_b.setChecked(False); self.drawer_b.setFocus(); e.accept(); return    # R70：Esc 收起抽屜
        super().keyPressEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e); self._layout_drawer()
        QTimer.singleShot(0, self._reflow)

    CARD_MIN, CARD_MAX = 290, 420

    def _reflow(self):
        """卡片牆欄數跟著可用寬度走，預覽跟著放大（寬螢幕不留大片空白）；標題列太窄時按鈕改短字。"""
        vw = self.scroll.viewport().width() - 24
        cols = max(1, min(6, (vw + 8) // (self.CARD_MIN + 8)))
        self.wall.set_cols(cols)
        cw = max(self.CARD_MIN, min(self.CARD_MAX, (vw + 8) // cols - 8))
        for c in self.wall.cards:
            c.set_width(cw)
        for g, _ in self.wall._grids:       # R64：立即套用新欄寬，避免短暫的重疊/空白畫面
            g.invalidate(); g.activate()
        self.wall.layout().activate()
        self._play_t.start()
        for h in self.wall.headers:
            h.compact(vw < 560)
        self._fix_tab_order()

    MAX_PLAYING = 24

    def _apply_filter(self):
        k = self.filt.currentData() or ""
        q = self.aiq.text().strip().lower() if hasattr(self, "strat_bar") else ""
        qd = q.replace("-", "").replace("/", "")
        base = {"": lambda c: True, "on": lambda c: c.on, "off": lambda c: not c.on,
                "low": lambda c: c.is_low, "ai": lambda c: c.ai}.get(k, lambda c: True)
        pred = (lambda c: base(c) and (q in c.name.lower() or (qd and qd in c.name.lower()))) if q else base
        n = self.wall.apply_filter(pred)
        self._update_count()
        self.filter_bar.setVisible(bool(self.wall.cards) or bool(q) or bool(self.lib.files()))
        self._play_t.start()
        return n

    def _uniq_cards(self):
        return list(self.cards.values())

    def _update_count(self):
        u = self._uniq_cards(); on = [c for c in u if c.on]
        secs = sum(c.secs for c in on)
        self.count_l.setText(f"共 <b style='color:#FFC400'>{len(u)}</b> 段，已選 <b style='color:#FFC400'>{len(on)}</b> 段（約 {secs:.0f} 秒）")
        self.count_l.setAccessibleName(f"共 {len(u)} 段，已選 {len(on)} 段，約 {secs:.0f} 秒")

    def _fold_all(self):
        fold = self.fold_b.text() == "全部收合"
        for h in self.wall.headers:
            if (h.tog.text().startswith("▾")) == fold:
                h.tog.click()
        self.fold_b.setText("全部展開" if fold else "全部收合")

    def _relayout_now(self):
        self.wall.adjustSize(); self.wall.updateGeometry(); self._reflow()
        self.scroll.viewport().update()
        QTimer.singleShot(150, self._reflow)

    def _update_playback(self):
        if not self.autoplay:
            return
        vp = self.scroll.viewport(); top = self.scroll.verticalScrollBar().value(); bot = top + vp.height()
        n = 0
        for c in self.wall.cards:
            if not c.isVisible():
                c.view.pause(); continue
            y = c.mapTo(self.wall, c.rect().topLeft()).y()
            vis = y + c.height() > top - 50 and y < bot + 50
            if vis and n < self.MAX_PLAYING:
                c.view.play(); n += 1
            else:
                c.view.pause()

    def _fix_tab_order(self):
        """Tab 順序：上方工具列 → 影片清單 → 策略列 → 篩選列 → 卡片牆 → 匯出設定 → 預覽選取/匯出。"""
        from PySide6.QtWidgets import QWidget as _W
        tab = lambda w: w.isVisibleTo(self) and w.focusPolicy() & Qt.TabFocus
        kids = lambda p: [w for w in p.findChildren(_W) if tab(w)]
        wl = self.wall
        if wl.items and not (wl.active is not None and wl.active.isVisibleTo(self)):
            vis = [c for c in wl.items if c.isVisibleTo(self)]
            if vis:
                wl.active = next((c for c in vis if c in wl.cards), vis[0]); wl._rove()
        chain = kids(self.top_bar) + [self.search, self.vlist] + kids(self.strat_bar) + kids(self.filter_bar)
        chain += kids(self.wall) + kids(self.rscroll.widget()) + [self.drawer_b, self.prev_b, self.exp_b]
        seen = []
        for w in chain:
            if w not in seen and (tab(w) or w in (self.prev_b, self.exp_b)):
                seen.append(w)
        for a, b in zip(seen, seen[1:]):
            QWidget.setTabOrder(a, b)

    def _layout_drawer(self):
        narrow = self.width() < self.NARROW
        if hasattr(self, "dstrip"):
            self.dstrip.setVisible(narrow)
            if not narrow and self._drawer_open:
                self._drawer_open = False; self.drawer_b.blockSignals(True); self.drawer_b.setChecked(False)
                self.drawer_b.blockSignals(False)
            host = self._H.parentWidget()
            overlay = narrow and self._drawer_open
            inside = self._H.indexOf(self.rscroll) >= 0
            if overlay and inside:            # 抽屜浮在卡片牆上，不擠壓中間欄
                self._H.removeWidget(self.rscroll); self.rscroll.setParent(host)
            elif not overlay and not inside:
                self.rscroll.setParent(host); self._H.insertWidget(self._H.indexOf(self.dstrip), self.rscroll)
            if overlay:
                # R71：抽屜只蓋內容區，底邊停在匯出列上緣，不遮主按鈕／「取消匯出」
                top = self._H.geometry().top()
                bot = self.ebar.mapTo(host, self.ebar.rect().topLeft()).y() if self.ebar.isVisible() else host.height()
                right = self.dstrip.mapTo(host, self.dstrip.rect().topLeft()).x() if self.dstrip.isVisible() else host.width() - 48
                self.rscroll.setGeometry(right - 320, top, 320, max(100, bot - top))
                self.rscroll.setStyleSheet("QScrollArea{border-left:1px solid #555;background:#1b1b1b}")
                self.rscroll.show(); self.rscroll.raise_()
            else:
                self.rscroll.setStyleSheet("")
                self.rscroll.setVisible(not narrow)
            self.drawer_b.setText("✕" if (narrow and self._drawer_open) else "⚙")
            self.drawer_b.setToolTip("收起匯出設定" if self._drawer_open else "匯出設定")
            return
        self.drawer_b.setVisible(narrow)
        self.rscroll.setVisible(not narrow or self._drawer_open)
        self.drawer_b.setText("匯出設定 ◂" if (narrow and self._drawer_open) else "匯出設定 ▸")

    def _toggle_drawer(self, on):
        self._drawer_open = on; self._layout_drawer()
        if on:
            self.exp_panel.folder_e.setFocus()

    def _first_tip(self):
        self.lib.set("tip_seen", 1)
        self.toast.show_msg("小提示：上方「剪片策略」決定怎麼挑候選片段；勾選喜歡的，再按右下角「匯出已選片段」，"
                            "每段各存成一個檔案。", action="知道了", ms=15000)

    def _shortcuts(self):
        QShortcut(QKeySequence("Ctrl+Alt+T"), self, activated=lambda: self.tl.setFocus())   # 舊時間軸（隱藏）
        QShortcut(QKeySequence.Undo, self, activated=self.undo)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.import_files)
        QShortcut(QKeySequence("Ctrl+E"), self, activated=lambda: self.export_clips())       # R69：⌘E 匯出已選片段
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=lambda: self.export_clips())
        QShortcut(QKeySequence.SelectAll, self, activated=self._ctrl_a)                       # R69：⌘A 本頁全選
        QShortcut(QKeySequence("Ctrl+,") if PF == "mac" else QKeySequence("Ctrl+Alt+S"), self, activated=self.open_settings)

    def refresh(self, keep=True):
        from app.library import group_name
        files = self.lib.files()
        ld = os.path.join(self.lib.root, "luts")
        for f in sorted(os.listdir(ld)) if os.path.isdir(ld) else []:
            if f.lower().endswith(".cube"):
                self._add_lut_item(os.path.join(ld, f))
        if hasattr(self, "_prev_t"):
            self._prev_t.start()
        self.stack.setCurrentIndex(0 if not files else 1)
        for a in (self.a_shuffle,):
            a.setEnabled(bool(files))
        self.aiq.setEnabled(bool(files))
        _sv = self.scroll.verticalScrollBar().value()
        self.vlist.blockSignals(True); self.vlist.clear()
        sel = None
        for f in files:
            name = group_name(f["path"])
            ext = os.path.splitext(f["path"])[1][1:].upper()
            badge = self.file_badges(f)
            st = f["status"]
            if st == STATUS_DONE:
                cs = self.lib.clips(f["id"]); n_on = sum(1 for c in cs if c["checked"])
                st = f"✓ {len(cs)} 段候選・已選 {n_on}" if cs else "✓ 已分析（沒有合適片段）"
            it = QListWidgetItem(f"{name}  [{ext}]{badge}\n{st}")
            it.setToolTip(f"{f['path']}\n{f['status']}")
            it.setData(Qt.UserRole, f["id"])
            it.setData(Qt.AccessibleTextRole, f"{name}，{ext}，{st}")
            self.vlist.addItem(it)
            if f["id"] == self.cur_fid:
                sel = it
        self.vlist.blockSignals(False)
        if files and sel is None:
            self.cur_fid = None
        self._filter(self.search.text())
        self._build_wall()
        if keep:
            QTimer.singleShot(0, lambda v=_sv: self.scroll.verticalScrollBar().setValue(v))   # R63：重建卡片牆不跳回頂端
        self._timeline()
        ws = self.lib.watched_status()
        self.watch_lab.setText("\n".join(f"監看：{os.path.basename(p) or p}（{s}）" for p, _, s in ws))
        self._ai_state()
        self._trip_list(files)

    def _filter(self, t):
        for i in range(self.vlist.count()):
            it = self.vlist.item(i); it.setHidden(bool(t) and t.lower() not in it.text().lower())

    def _pick_video(self, it, _prev=None):
        if not it:
            return
        fid = it.data(Qt.UserRole)
        hdr = self._headers.get(fid)
        if hdr:
            self.scroll.ensureWidgetVisible(hdr, 0, 0)

    def _build_wall(self):
        from app.library import group_name
        from .clips import chip_keys
        # R71（500+ 段效能）：重建時停掉牆的畫面更新
        # （曾試過先 hide 整面牆：未 show 前建牆會永久藏住、1024 寬標題列也排不回來，已改成只停畫面更新）
        self.wall.setUpdatesEnabled(False)
        try:
            self._build_wall_inner()
        finally:
            self.wall.setUpdatesEnabled(True)
        if hasattr(self, "strat_bar"):
            self.strat_bar.set_cfg(self.lib.strategy_cfg()); self.strat_bar.set_counts(self._strategy_counts())
        self._apply_filter()
        QTimer.singleShot(0, self._reflow)

    def _build_wall_inner(self):
        from app.library import group_name
        from .clips import chip_keys
        self.wall.clear(); self.cards = {}; self._headers = {}; self._dups = {}
        en = self.lib.enabled_strategies()
        files = self.lib.files()

        def mk(c, vname):
            card = ClipCard(c, vname, autoplay=self.autoplay, enabled=en)
            card.secs = c["end"] - c["start"]
            card.toggled.connect(self.toggle); card.trim.connect(self.trim)
            card.locked.connect(self.lock_clip)
            card.set_ai(c["id"] in self.ai_hits)
            self.cards.setdefault(c["id"], card); self._dups.setdefault(c["id"], []).append(card)
            return card

        def sel(cards):
            self._set_many([c.cid for c in cards if not c.on])
        if getattr(self, "group_mode", "video") == "strategy":
            rows = [(f, c) for f in files for c in self.lib.clips(f["id"])]
            keyed = [(f, c, chip_keys(c, en)) for f, c in rows]
            groups = [(k, core.STRAT_NAMES[k]) for k in list(core.STRAT_ORDER) + ["manual"] if k == "manual" or k in en]
            groups.append((None, "其他（策略已關閉）"))
            for k, title in groups:
                mem = [(f, c, ks) for f, c, ks in keyed if (k in ks if k else not ks)]
                if not mem:
                    continue
                h = GroupHeader(title, "", f"{len(mem)} 段"); h.manual.hide(); h.selall.setText("本組全選")
                cards = []
                for f, c, ks in mem:
                    card = mk(c, group_name(f["path"]))
                    card.set_also([core.STRAT_NAMES[x] for x in ks if x != k])
                    cards.append(card)
                h.selall.clicked.connect(lambda _=False, cs=cards: sel(cs))
                self.wall.add_group(h, cards)
        else:
            for f in files:
                ext = os.path.splitext(f["path"])[1][1:].upper()
                clips = self.lib.clips(f["id"])
                # R70：只有「均勻取樣」選到的片段排最後（保底用）
                clips = sorted(clips, key=lambda c: _uniform_only(c) and not c.get("checked"))
                dur = f.get("duration") or 0
                st = f["status"] if f["status"] != STATUS_DONE else f"{fmt(dur).split('.')[0]} · {len(clips)} 段"
                h = GroupHeader(group_name(f["path"]), ext, st)
                h.again.clicked.connect(lambda _=False, fid=f["id"]: self.reanalyze(fid))
                h.manual.clicked.connect(lambda _=False, fid=f["id"]: self.manual_clip(fid))
                h.manual.setEnabled(f["status"] == STATUS_DONE)
                cards = [mk(c, group_name(f["path"])) for c in clips]
                h.selall.clicked.connect(lambda _=False, cs=cards: sel(cs)); h.selall.setEnabled(bool(cards))
                self.wall.add_group(h, cards)
                self._headers[f["id"]] = h
        self.wall.finish()

    def _timeline(self):
        tl = self.lib.timeline()
        names = {}
        from app.library import group_name
        for c in tl:
            names[c["file_id"]] = group_name(c["path"])
        self.tl.set_clips(tl, names)
        th = next((c.get("thumb") for c in tl if c.get("thumb") and os.path.exists(c["thumb"])), None)
        if hasattr(self, "sticker_pad"):
            self.sticker_pad.set_thumb(th)
        self._summary()

    def _target(self):
        v = self.target.currentData()
        return self.cust.value() if v == -1 else v

    def _target_changed(self, *_):
        custom = self.target.currentData() == -1
        self.cust.setVisible(custom)
        if not custom:                     # N1：切回預設長度時清掉舊的自訂錯誤
            self.cust_err.hide(); prop(self.cust, invalid=False)
        self._summary()

    def _segments(self):
        segs = self.lib.timeline_segments()
        tgt = self._target()
        fitted, over = core.fit_to_target(segs, tgt) if tgt else (segs, 0.0)
        return segs, fitted, over

    def _summary(self):
        if not hasattr(self, "ebar"):
            return
        from .clips import est_mb
        if self.target.currentData() == -1:      # 舊的成品長度設定（隱藏）仍維持原本的檢查
            segs = self.lib.timeline_segments(); tgt = self._target()
            bad = segs and tgt > 0 and tgt < 1.5 * max(1, len(segs))
            self.cust_err.setVisible(bool(bad)); prop(self.cust, invalid=bool(bad))
        items = self._export_items()
        n = len(items); secs = sum(s.end - s.start for s, _ in items)
        co = self.exp_panel.options()
        self.summary.setText(f"已選 <b>{n}</b> 段 · 約 {secs:.0f} 秒 · 預估 {est_mb(secs, co):.0f} MB" if n else "尚未選取片段")
        self.summary.setAccessibleName(f"已選 {n} 段，約 {secs:.0f} 秒，預估 {est_mb(secs, co):.0f} MB")
        self.exp_b.setText(f"匯出已選片段（{n}）")
        self.exp_b.setAccessibleName(f"匯出已選片段，{n} 段")
        busy = bool(getattr(self, "_exp_job", None))
        if busy:
            stopping = self._exp_job.cancelled
            self.exp_b.setText("正在取消…" if stopping else "取消匯出")
            self.exp_b.setAccessibleName("取消匯出")
            self.exp_b.setEnabled(not stopping); self.prev_b.setEnabled(False)
        else:
            self.exp_b.setEnabled(n > 0); self.prev_b.setEnabled(n > 0)
        self.reason.setText("" if n else "勾選片段後即可匯出")
        self.exp_panel.set_sample(items[0] if items else None)

    def import_files(self, paths=None):
        if not paths:
            paths, _ = QFileDialog.getOpenFileNames(self, "匯入影片", os.path.expanduser("~"), VIDEO_FILTER)
        if paths:
            self.lib.add_files(paths); self.refresh(); self.analyze()

    def import_folder(self, folder=None, watch=True):
        if not folder:
            folder = QFileDialog.getExistingDirectory(self, "匯入資料夾", os.path.expanduser("~"))
        if folder:
            self.lib.add_folder(folder, recursive=True, watch=watch); self.refresh(); self.analyze()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        ps = [u.toLocalFile() for u in e.mimeData().urls()]
        dirs = [p for p in ps if os.path.isdir(p)]
        allf = [p for p in ps if os.path.isfile(p)]
        files = [p for p in allf if p.lower().endswith(core.VIDEO_EXTS)]
        for d in dirs:
            self.lib.add_folder(d)
        if files:
            self.lib.add_files(files)
        if not dirs and not files:
            self.toast.show_msg("拖進來的不是影片檔（支援 MP4、MOV、INSV、LRV…）", ms=5000); return
        self.refresh(); self.analyze()
        if len(allf) > len(files):
            self.toast.show_msg(f"已略過 {len(allf) - len(files)} 個非影片檔", ms=4000)

    def run_job(self, fn, *a, done=None, failed=None, cancelled=None, progress=None):
        """在背景執行；主執行緒先 commit，工作執行緒開自己的 SQLite 連線。"""
        if getattr(self, "_closed", False):        # R70：視窗關掉後不再開工作（資料庫已關閉）
            return None
        self.lib.db.commit()
        job = Job(fn, *a); self.jobs.append(job)
        if progress:
            job.sig.progress.connect(progress)

        def fin(cb):
            def f(*x):
                if job in self.jobs:
                    self.jobs.remove(job)
                if cb:
                    cb(*x)
            return f
        job.sig.done.connect(fin(done)); job.sig.failed.connect(fin(failed or self._job_failed))
        job.sig.cancelled.connect(fin(cancelled))
        self.pool.start(job)
        return job

    def _job_failed(self, msg):
        D.ErrorDialog(self, "發生錯誤", msg, retry=False).exec()

    def busy(self):
        return any(not j.finished for j in self.jobs)

    def analyze(self, fids=None, force=False):
        fids = list(fids or self.lib.needs_analysis())
        if getattr(self, "_an_job", None):
            self._an_queue = getattr(self, "_an_queue", []) + [(f, force) for f in fids]   # 排隊，不丟掉
            return
        if not fids:
            return
        st = {"count": self.lib.get("count", 2), "seg_len": self.lib.get("seg_len", 6.5)}
        self.banner.show(); self.banner_cancel.setEnabled(True)
        self.banner_lab.setText(f"正在分析 {len(fids)} 支影片…（可以先勾選已完成的片段）")
        for f in fids:
            h = getattr(self, "_headers", {}).get(f)
            if h:
                h.st.setText("分析中…"); h.again.setEnabled(False)
        self._an_job = self.run_job(analyze_job, self.root, fids, st, force,
                                    progress=lambda f, m: self.banner_lab.setText(f"正在分析：{m}"),
                                    done=self._analyzed, failed=self._analyze_failed,
                                    cancelled=self._analyze_cancelled)

    def _stop_analyze(self):
        if getattr(self, "_an_job", None):
            self._an_job.cancelled = True; self._an_queue = []
            self.banner_lab.setText("正在停止…"); self.banner_cancel.setEnabled(False)

    def _next_analysis(self):
        self._an_job = None
        q, self._an_queue = getattr(self, "_an_queue", []), []
        if q:
            force = any(f for _, f in q)
            self.analyze(list(dict.fromkeys(fid for fid, _ in q)), force=force)
            return True
        return False

    def _analyzed(self, _):
        if self._next_analysis():
            self.refresh(); return
        self.banner.hide(); self.refresh()
        if getattr(self, "_rc_pending", False):
            QTimer.singleShot(0, self._recompute)
        self._relayout_now()       # R63：分析完成立刻重排（外部審查必改 #1：不等使用者改視窗大小）
        self.start_tagging()
        cb, self._after_analysis = getattr(self, "_after_analysis", None), None
        if cb:
            cb(); return
        self.toast.show_msg("分析完成：已依剪片策略列出候選，並幫每支影片勾選最精彩的 1 段", ms=4000)

    def _analyze_cancelled(self):
        self._an_job = None; self._an_queue = []; self._after_analysis = None
        self.banner.hide(); self.refresh()
        self.toast.show_msg("已停止分析；未完成的影片會在下次開啟時繼續", ms=5000)

    def _analyze_failed(self, msg):
        # 失敗時也要清掉一鍵成片的後續動作與佇列，否則下次分析完會意外自動輸出（REVIEW_r10 B2）
        self._an_job = None; self._an_queue = []; self._after_analysis = None
        self.banner.hide(); self.refresh()
        D.ErrorDialog(self, "分析失敗", msg, retry=False).exec()

    def reanalyze(self, fid):
        self.analyze([fid], force=True)

    def manual_clip(self, fid, rng=None):
        f = next(x for x in self.lib.files() if x["id"] == fid)
        dur = f["duration"] or 0
        if rng is None:
            clip = {"file_id": fid, "path": f["path"], "start": 0.0, "end": min(4.0, dur), "proxy": None, "ai_start": None}
            dlg = D.TrimDialog(self, clip, dur, title="手動新增片段")
            if dlg.exec() != QDialog.Accepted or not dlg.result_range:
                return
            rng = dlg.result_range
        h = self._headers.get(fid)
        if h:
            h.manual.setEnabled(False); h.st.setText("正在產生片段預覽…")
        return self.run_job(manual_job, self.root, fid, *rng, done=lambda _: self.refresh(),
                            failed=lambda m: (self.refresh(), self._job_failed(m)))

    def _watch_tick(self):
        self.watch.setInterval(watch_interval() * 1000)
        if self.lib.rescan():
            self.refresh(); self.analyze()

    # ---------- 片段操作 ----------
    def toggle(self, cid, on):
        self.lib.set_checked(cid, on)
        for c in getattr(self, "_dups", {}).get(cid, []) or ([self.cards[cid]] if cid in self.cards else []):
            c.set_on(on)
        self._timeline()
        if hasattr(self, "count_l"):
            self._apply_filter() if (self.filt.currentData() or "") in ("on", "off") else self._update_count()

    def _reorder(self, ids):
        self.lib.set_order(ids); self._timeline()

    def trim(self, cid, rng=None):
        c = self.lib.db.execute("SELECT c.*, f.duration, f.path FROM clips c JOIN files f ON f.id=c.file_id WHERE c.id=?",
                                (cid,)).fetchone()
        if rng is None:
            cd = dict(c); cd["roll"] = self.lib.get(f"roll:{cid}")
            dlg = D.TrimDialog(self, cd, c["duration"] or c["end"])
            if dlg.exec() != QDialog.Accepted or not dlg.result_range:
                return
            rng = dlg.result_range
            self.lib.set_speed(cid, dlg.result_curve)
            self.lib.set_roll(cid, dlg.result_roll)
        self.lib.db.execute("UPDATE clips SET start=?, end=? WHERE id=?", (*rng, cid)); self.lib.db.commit()
        self._timeline()
        if cid in self.cards:
            self.cards[cid].lab.setText(f"{fmt(rng[0])}–{fmt(rng[1])}・{rng[1] - rng[0]:.1f} 秒　更新預覽中…")
        return self.run_job(trim_job, self.root, cid, *rng, done=lambda _: self.refresh())

    # ---------- 移除 / 刪除 ----------
    def eventFilter(self, o, e):
        from PySide6.QtCore import QEvent
        if o is self.vlist and e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.remove_selected(); return True
        return super().eventFilter(o, e)

    def remove_selected(self, fids=None, auto=None):
        fids = fids or [it.data(Qt.UserRole) for it in self.vlist.selectedItems()]
        if not fids:
            return
        from app.library import group_name
        names = [group_name(f["path"]) for f in self.lib.files() if f["id"] in fids]
        dlg = D.RemoveDialog(self, names)
        if auto:
            dlg.choice = auto
        elif dlg.exec() != QDialog.Accepted:
            return
        if dlg.choice == "remove":
            self.lib.remove_from_list(fids); self.refresh()
            self.toast.show_msg(f"已從清單移除 {len(fids)} 支", "復原", self.undo)
        else:
            self.delete_files(fids)

    def delete_files(self, fids, auto=None):
        """auto（測試用）：{'trash': bool, 'previews_only': bool, 'perm': 'skip'|'perm'|None}"""
        plan = self.lib.delete_plan(fids)
        dlg = D.TrashDialog(self, plan)
        if auto is not None:
            dlg.previews_only.setChecked(auto.get("previews_only", False))
            if not auto.get("trash", True):
                return
        elif dlg.exec() != QDialog.Accepted:
            return
        po = dlg.previews_only.isChecked()
        allow, skip = False, False
        if plan["no_trash"] and not po:
            p = D.PermDialog(self, plan)
            if auto is not None:
                p.choice = auto.get("perm")
            elif p.exec() != QDialog.Accepted:
                return
            if not p.choice:
                return
            allow, skip = p.choice == "perm", p.choice == "skip"
        ok, fail = self.lib.delete_files(fids, allow_permanent=allow, skip_no_trash=skip, previews_only=po)
        self.refresh()
        real = [x for x in fail if x[1] not in ("skipped",)]
        msg = (f"已刪除 {len(ok)} 支的預覽檔" if po else f"已將 {len(ok)} 支移到{D.TRASH}") if ok else "沒有刪除任何檔案"
        if any(x[1] == "skipped" for x in fail):
            msg += f"，略過 {len({x[0] for x in fail if x[1] == 'skipped'})} 個檔案"
        self.toast.show_msg(msg)
        if real:
            D.ErrorDialog(self, "部分檔案無法刪除", "\n".join(f"{os.path.basename(p)}：{r}" for p, r in real[:8]), retry=False, friendly=False).exec()
        return ok, fail

    def undo(self):
        if self.lib.undo_remove():
            self.refresh(); self.toast.show_msg("已復原", ms=3000)

    # ---------- 輸出 ----------
    def options(self, preview=False):
        return core.ExportOptions(aspect=self.aspect.currentData(), resolution="1080p" if preview else self.res.currentData(),
                                  crossfade=0.0, music="",
                                  keep_original_audio=self.keep_audio.isChecked(), fade_out=1.5 if self.fade.isChecked() else 0,
                                  hw_encode=bool(self.lib.get("hw_encode", True)) and not preview,
                                  reframe=self.frame_c.currentData(), projection=self.proj.currentData(),
                                  look=self.look_c.currentData() or "", loudnorm=bool(self.share.currentData()) and not preview, auto_enhance=self.auto_col.isChecked(),
                                  title=self.title_e.text().strip(), subtitle=self._date_text() if self.date_c.isChecked() else "",
                                  title_style=self.tstyle.currentData(), title_anim=self.tanim.currentData(),
                                  effect=self.fx.currentData() or "")

    def _toggle_adv(self, on):
        self.adv.setVisible(on)
        self.adv_b.setText(("進階設定 ▾" if on else "進階設定 ▸") + "（AI 剪輯、文字、特效、貼圖）")
        if self.adv_b.isChecked() != on:
            self.adv_b.setChecked(on)

    def _fx_preview(self, *_):
        name = self.fx.currentData()
        if not name:
            self.fx_preview.hide(); return
        self._toggle_adv(True)
        import hashlib
        tl = self.lib.timeline()
        img = next((c["thumb"] for c in tl if c.get("thumb") and os.path.exists(c["thumb"])), None)
        key_ = hashlib.sha1(f"{name}|{img}".encode("utf-8")).hexdigest()[:12]
        d = os.path.join(self.lib.root, "cache"); os.makedirs(d, exist_ok=True)
        out = os.path.join(d, f"fxpv_{key_}.png")
        try:
            if not os.path.exists(out):
                core.effect_preview(name, out, img=img)
        except (RuntimeError, OSError) as e:
            self.fx_preview.hide(); self.fx_preview.setToolTip(str(e)); return
        from PySide6.QtGui import QPixmap
        self.fx_preview.setPixmap(QPixmap(out)); self.fx_preview.show()
        self.fx_preview.setToolTip(f"{self.fx.currentText()}：觸發前 → 觸發 → 0.05 秒後 → 0.15 秒後")

    def _cur_sticker(self):
        e = self.sticker.currentData()
        if not e:
            return None
        pos = self.sticker_pad.pos_f if self.sticker_pos.currentData() == "custom" else self.sticker_pos.currentData()
        return (e, pos, self.sticker_anim.currentData())

    def _sticker_add(self):
        st = self._cur_sticker()
        if not st or len(self.stickers) >= core.STICKER_MAX:
            return
        self.stickers.append(st)
        pos = f"{int(st[1][0] * 100)}%, {int(st[1][1] * 100)}%" if isinstance(st[1], tuple) else st[1]
        self.sticker_list.addItem(f"{st[0]}  {pos}  {st[2]}")
        self.sticker.setCurrentIndex(0)

    def _sticker_del(self):
        r = self.sticker_list.currentRow()
        if r >= 0:
            self.stickers.pop(r); self.sticker_list.takeItem(r); self._sticker_state()

    def _sticker_dragged(self, *_):
        if self.sticker.currentData() and self.sticker_pos.currentData() != "custom":
            self.sticker_pos.setCurrentIndex(self.sticker_pos.findData("custom"))

    def _sticker_state(self):
        on = bool(self.sticker.currentData())
        self.sticker_pos.setEnabled(on); self.sticker_anim.setEnabled(on)
        full = len(self.stickers) >= core.STICKER_MAX
        self.sticker_add.setEnabled(on and not full); self.sticker_del.setEnabled(bool(self.stickers))
        self.sticker_add.setText("已達上限" if full else "＋ 加入這張貼圖")
        self.sticker_list.setVisible(bool(self.stickers))
        if on and self.sticker_pos.currentData() != "custom":
            self.sticker_pad.pos_f = StickerPad.CORNER_F.get(self.sticker_pos.currentData(), self.sticker_pad.pos_f)
        self.sticker_pad.active = on
        self.sticker_pad.set_others([(e, p) for e, p, _ in self.stickers])
        self.sticker_pad.setVisible(on or bool(self.stickers))
        if (on or self.stickers) and hasattr(self, "adv_b"):
            self._toggle_adv(True)
        self.sticker_pad.set_emoji(self.sticker.currentData())
        a = self.aspect.currentData() or "16:9"; x, y = a.split(":"); self.sticker_pad.set_ratio(int(x) / int(y))

    def import_lut(self, path=None):
        """複製 .cube 到媒體庫 luts/（避免原檔被移走），並加入濾鏡清單、立即選取。"""
        if path is None:
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(self, "選擇 LUT", "", "3D LUT (*.cube)")
            if not path:
                return None
        try:
            core.parse_cube(path)
        except (ValueError, OSError) as e:
            self.toast.show_msg(f"無法使用這個 LUT：{e}", ms=5000); return None
        import shutil
        d = os.path.join(self.lib.root, "luts"); os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, os.path.basename(path))
        if os.path.abspath(dst) != os.path.abspath(path):
            shutil.copy2(path, dst)
        self._add_lut_item(dst)
        self.look_c.setCurrentIndex(self.look_c.findData("lut:" + dst))
        self.toast.show_msg(f"已加入 LUT：{os.path.splitext(os.path.basename(dst))[0]}", ms=3000)
        return dst

    def _add_lut_item(self, p):
        if self.look_c.findData("lut:" + p) < 0:
            self.look_c.addItem("LUT：" + os.path.splitext(os.path.basename(p))[0], "lut:" + p)

    def update_look_preview(self):
        """在背景抓一格套濾鏡，完成後更新預覽圖（設定變動 250ms 去抖動）。"""
        try:
            segs = self.lib.timeline_segments()
        except Exception:   # R63: 視窗關閉後的延遲計時器
            return
        if not segs:
            self.look_prev.setText("選片段後顯示濾鏡預覽"); return
        s0 = segs[0]; look = self.look_c.currentData() or ""; auto = self.auto_col.isChecked()
        out = os.path.join(self.lib.root, "look_preview.png")

        def done(p):
            from PySide6.QtGui import QPixmap
            if p:
                pm = QPixmap(p)
                self.look_prev.setPixmap(pm.scaledToWidth(min(300, max(120, self.look_prev.width() - 4)), Qt.SmoothTransformation))
                self.look_prev.setToolTip(f"預覽：{self.look_c.currentText()}")
                self._look_prev_ok = True
        self.run_job(lambda job: core.preview_look(s0.path, (s0.start + s0.end) / 2, look, auto, out), done=done,
                     failed=lambda m: self.look_prev.setText("預覽失敗"))

    def apply_share(self, name):
        p = core.SHARE_PRESETS.get(name or "")
        if not p:
            return
        self.aspect.setCurrentIndex(max(0, self.aspect.findData(p["aspect"])))
        self.res.setCurrentIndex(max(0, self.res.findData(p["resolution"])))
        self.target.setCurrentIndex(max(0, self.target.findData(p["target"])))
        self.toast.show_msg(f"已套用「{name}」：{self.aspect.currentText()}、{p['target']} 秒、音量標準化", ms=3000)

    def _date_text(self):
        tl = self.lib.timeline()
        if not tl:
            return ""
        import time as _t
        ts = [os.path.getmtime(c["path"]) for c in tl if os.path.exists(c["path"])]
        if not ts:
            return ""
        a, b = _t.strftime("%Y.%m.%d", _t.localtime(min(ts))), _t.strftime("%Y.%m.%d", _t.localtime(max(ts)))
        return a if a == b else f"{a} – {b[5:] if a[:4] == b[:4] else b}"

    def apply_style(self, name):
        from app import smart
        t = smart.TEMPLATES.get(name)
        if not t:
            return
        self._pacing = t["pacing"]
        self.slowmo.setChecked(t["slowmo"] > 0)
        self.target.setCurrentIndex(max(0, self.target.findData(t["target"])))
        self.date_c.setChecked(t["title"])
        lk = {"運動": "鮮豔", "旅行": "電影"}.get(name, "")
        self.look_c.setCurrentIndex(max(0, self.look_c.findData(lk)))
        self.toast.show_msg(f"已套用「{name}」風格："
                            f"{'有' if t['slowmo'] else '無'}慢動作", ms=3000)

    def _prep(self):
        """交給背景輸出工作的 AI 步驟參數。"""
        return {"root": self.root, "music": "",
                "pacing": getattr(self, "_pacing", "平穩"), "slowmo": 0.5 if self.slowmo.isChecked() else 0.0,
                "crossfade": 0.0,
                "stickers": self.stickers + ([self._cur_sticker()] if self._cur_sticker() else [])}

    def one_click(self, folder=None, out=None, on_done=None, only_fids=None, brief=None):
        """一鍵成片：(選資料夾) → 分析 → 自動挑選＋去重 → 對拍/慢動作 → 輸出。完成後仍可修改。"""
        if folder is None and not self.lib.files():
            folder = QFileDialog.getExistingDirectory(self, "一鍵成片：選擇影片資料夾", os.path.expanduser("~"))
            if not folder:
                return
        if folder:
            self.lib.add_folder(folder, recursive=True, watch=False); self.refresh()

        def go():
            tgt = self._target() or 60
            self._only = only_fids
            b = brief or {}
            ids = self.lib.auto_pick(tgt, prefer_tag=b.get("tags") or self.theme.currentData() or None,
                                     only_fids=only_fids, smile=bool(b.get("smile")))
            self.refresh()
            if not ids:
                self.toast.show_msg("沒有可用的片段", ms=4000); return
            self.toast.show_msg(f"已自動挑選 {len(ids)} 段（去除重複畫面），正在輸出；之後仍可修改再輸出", ms=6000)
            self.export(out=out or self._suggest_out(), auto=out is not None, on_done=on_done)
            self.save_prefs()
        if self.lib.needs_analysis():
            self._after_analysis = go
            self.analyze()
        else:
            go()

    def tags_stale(self):
        """有片段，且（裝了 CLIP 時）資料庫記錄的標籤器版本和目前不同。"""
        from app import semantic
        return bool(self.lib.clip_rows()) and semantic.has_clip() and self.lib.get("tagger_version") != semantic.tagger_version()

    def start_tagging(self):
        from app import semantic
        if getattr(self, "_closed", False) or getattr(self, "_tagging", False) or not semantic.has_clip():
            return
        self._tagging = True

        def ok(n):
            self._tagging = False
            if n:
                self._retag_cards(); self._update_theme_counts()

        def bad(msg):
            self._tagging = False        # 標籤是加分功能，失敗不跳錯誤視窗
        self.run_job(tag_job, self.lib.root, done=ok, failed=bad)

    def _retag_cards(self):
        """R63：標籤完成只更新卡片上的 #標籤，不重建整面牆（不重開所有預覽播放器、不跳捲動位置）。"""
        rows = {r["id"]: r for r in self.lib.clip_rows()}
        if set(rows) != set(self.cards):
            self.refresh(); return
        for cid, card in self.cards.items():
            card.set_tags(rows[cid].get("tags"))

    def _update_theme_counts(self):
        cnt = self.lib.tag_counts()
        for i in range(1, self.theme.count()):
            t = self.theme.itemData(i); self.theme.setItemText(i, f"{t}（{cnt.get(t, 0)} 段）")

    def lock_clip(self, cid, on):
        if on:
            self.lib.set_checked(cid, True)
        self.lib.set_locked(cid, on)
        if cid in self.cards:
            self.cards[cid].set_on(self.cards[cid].on or on)
        self._timeline()

    def reshuffle(self):
        if not self.lib.clip_rows():
            self.toast.show_msg("還沒有片段可以換", ms=3000); return
        before = {r["id"] for r in self.lib.clip_rows() if r["checked"]}
        ids = self.lib.auto_pick(self._target() or 60, reshuffle=True,
                                 prefer_tag=self.theme.currentData() or None)
        self.refresh()
        new = len(set(ids) - before)
        self.toast.show_msg(f"換了 {new} 段新畫面（鎖定的保留）" if new else "沒有其他夠好的片段可以換了", ms=4000)

    def _suggest_out(self):
        d = self.lib.get("out_dir", os.path.expanduser("~/Movies" if PF == "mac" else "~/Videos"))
        os.makedirs(d, exist_ok=True)
        from datetime import datetime
        sp = core.SHARE_PRESETS.get(self.share.currentData() or "")
        tag = f"_{sp['suffix']}" if sp else ""
        p = os.path.join(d, f"精華_{datetime.now():%Y%m%d_%H%M}{tag}.mp4"); i = 2
        while os.path.exists(p):
            p = os.path.join(d, f"精華_{datetime.now():%Y%m%d_%H%M}{tag}_{i}.mp4"); i += 1
        return p

    def formats(self):
        return [a for a, c in self.fmt_c.items() if c.isChecked()]

    def export(self, preview=False, out=None, auto=False, on_done=None, _multi=None):
        """R36：勾了「同時輸出」多種比例時，依序各輸出一支（檔名加 _16x9/_9x16/_1x1），完成後回到原本比例。"""
        fm = self.formats()
        if not preview and _multi is None and len(set(fm) | {self.aspect.currentData()}) > 1 and fm:
            if not self._segments()[1]:
                return
            if not out:
                sug = self._suggest_out()
                out = sug if auto else QFileDialog.getSaveFileName(self, "儲存成品（會再加上比例）", sug, "MP4 (*.mp4)")[0]
                if not out:
                    return
            aspects = list(dict.fromkeys([self.aspect.currentData()] + fm))
            plan = CV.multi_outputs(out, aspects); orig = self.aspect.currentData(); res = []

            def step(i):
                if i >= len(plan):
                    self.aspect.setCurrentIndex(self.aspect.findData(orig))
                    if on_done:
                        on_done(res[0] if res else None) if all(res) else on_done(None, "部分比例輸出失敗")
                    else:
                        self.toast.show_msg("已輸出 " + "、".join(a for a, _ in plan) + f"：{os.path.dirname(plan[0][1])}", ms=8000)
                        if all(res):
                            D.DoneDialog(self, res[0]).exec()
                    self.multi_results = res
                    return
                a, o = plan[i]
                self.aspect.setCurrentIndex(self.aspect.findData(a))

                def fin(path, err=None):
                    res.append(path)
                    if err == "cancelled":
                        self.aspect.setCurrentIndex(self.aspect.findData(orig)); self.multi_results = res
                        if on_done:
                            on_done(None, "cancelled")
                        return
                    step(i + 1)
                self.export(out=o, auto=True, on_done=fin, _multi=True)
            step(0)
            return plan
        segs, fitted, over = self._segments()
        if not fitted:
            return
        if preview:
            out = os.path.join(self.lib.cache_dir, "preview.mp4")
        if not out:
            sug = self._suggest_out()
            out = sug if auto else QFileDialog.getSaveFileName(self, "儲存成品", sug, "MP4 (*.mp4)")[0]
            if not out:
                return
        W, H = core.out_size(self.aspect.currentData(), self.res.currentData())
        need = int(sum(s.length for s in fitted) * (40e6 if W * H > 3e6 else 12e6) / 8 * 1.3 + 50e6)
        free = shutil.disk_usage(os.path.dirname(out) or ".").free
        if free < need and not auto:
            dd = D.DiskDialog(self, need, free, os.path.dirname(out))
            if dd.exec() != QDialog.Accepted or dd.choice != "go":
                if dd.choice == "other":
                    self.export(preview)
                return
        opts = self.options(preview)
        prog = D.ProgressDialog(self, "正在產生預覽" if preview else "正在產生成品")
        self.lib.db.commit()
        job = Job(export_job, fitted, out, opts, self._prep()); self.jobs.append(job)
        prog.cancel_req.connect(lambda: setattr(job, "cancelled", True))
        job.sig.progress.connect(prog.set)

        def cancelled():
            prog.done(0)
            pass                # 半成品只存在 out.part.mp4，由 core.export 清掉；絕不刪使用者原本的檔案（REVIEW_r10 B1）
            self.toast.show_msg("已取消輸出", ms=3000)
            if on_done:
                on_done(None, "cancelled")
        job.sig.cancelled.connect(cancelled)

        def done(path):
            prog.done(0)
            if on_done:
                on_done(path); return
            if preview:
                D.open_file(path)
            else:
                D.DoneDialog(self, path).exec()

        def failed(msg):
            prog.done(0)
            if on_done:
                on_done(None, msg); return
            e = D.ErrorDialog(self, "輸出失敗", msg)
            if e.exec() == QDialog.Accepted and e.retry:
                self.export(preview, None if getattr(e, "relocate", False) else out)
        job.sig.done.connect(done); job.sig.failed.connect(failed)
        self.pool.start(job)
        if auto:
            prog.show()
        else:
            prog.open()
        self._prog = prog
        return job

    def file_badges(self, f):
        """R37：低解析來源（只有 LRV）＋ 360 類型徽章。"""
        b = ""
        if self.lib.low_res(f["id"]):
            b += "  ・低解析來源"
        w_, h_ = f.get("width") or 0, f.get("height") or 0
        if h_ and (abs(w_ / h_ - 2) < 0.03 or abs(w_ / h_ - 1) < 0.03):
            pj = self.lib.projection(f["id"])
            b += {"equirect": "  ・360 全景", "dfisheye": "  ・360 雙魚眼", "fisheye": "  ・魚眼（自動攤平）"}.get(pj, "")
        if self.lib.analysis_source(f["id"]) != f["path"]:
            b += "  ・LRV 加速"
        return b

    # ---------- R31：記憶卡/相機 ----------
    def _device_tick(self):
        try:
            found = self.devwatch.poll()
        except Exception:
            return
        from app.library import scan_folder
        known = self.lib.known_paths()
        for info in found:
            new = CV.new_media(scan_folder(info["dcim"], True), known)
            vids = [p for p in new if p.lower().endswith((".mp4", ".mov", ".insv", ".m4v"))]
            if vids:
                self.show_device(info, len(vids)); break

    def show_device(self, info, n):
        self._dev = info
        self.dev_lab.setText(f"偵測到{CV.device_title(info)}：{n} 支新影片。要匯入並在背景分析嗎？（檔案不會被修改或刪除）")
        self.devbar.show(); self.stack.setCurrentIndex(1)

    def import_device(self, auto=False):
        info = self._dev
        self.devbar.hide(); self._dev = None
        if not info:
            return
        if auto:
            self.lib.add_folder(info["dcim"], recursive=True, watch=True); self.refresh()
            return self.one_click(only_fids=None)
        self.lib.add_folder(info["dcim"], recursive=True, watch=True)
        self.refresh(); self.analyze()
        self.toast.show_msg(f"已匯入{CV.device_title(info)}，正在背景分析；之後插入同一張卡會自動加入新影片", ms=5000)

    # ---------- R32：旅程 ----------
    def _trip_list(self, files=None):
        files = files if files is not None else self.lib.files()
        k = tuple(sorted((f["id"], f.get("mtime") or 0) for f in files))
        if k == self._trip_key:
            return
        self._trip_key = k
        self.trips = self.lib.trips() if files else []
        cur = self.trip_c.currentData()
        self.trip_c.blockSignals(True); self.trip_c.clear()
        for i, g in enumerate(self.trips):
            self.trip_c.addItem(g["name"], i)
        self.trip_c.blockSignals(False)
        self.trip_c.setEnabled(bool(self.trips)); self.trip_b.setEnabled(bool(self.trips))
        if cur is not None and cur < len(self.trips):
            self.trip_c.setCurrentIndex(cur)

    def make_trip(self, idx=None, out=None, on_done=None):
        idx = self.trip_c.currentData() if idx is None else idx
        if idx is None or idx >= len(self.trips):
            return
        g = self.trips[idx]
        if not self.title_e.text().strip():
            from datetime import datetime
            self.title_e.setText(f"{datetime.fromtimestamp(g['start']):%Y/%m/%d}")
        self.toast.show_msg(f"用「{g['name']}」做影片…", ms=3000)
        return self.one_click(only_fids=g["ids"], out=out, on_done=on_done)

    # ---------- R33：一句話成片 ----------
    def run_brief(self, text=None, out=None, on_done=None, go=True):
        text = (self.brief.text() if text is None else text).strip()
        if not text:
            return None
        if getattr(self, "cloud", False) and self.lib.get("ai_base"):
            def done(r):
                b, used = r
                self._brief_go(b, used, out, on_done, go)
            return self.run_job(brief_job, self.lib.get("ai_base"), ai.get_key(), self.lib.get("ai_model", "gpt-4o-mini"),
                                text, done=done, failed=lambda m: self._brief_go(CV.parse_brief(text), False, out, on_done, go))
        b = CV.parse_brief(text)
        self._brief_go(b, False, out, on_done, go)
        return b

    def apply_brief(self, b):
        if b.get("style"):
            self.style_c.setCurrentIndex(max(0, self.style_c.findData(b["style"])))
        if "target" in b:
            i = self.target.findData(b["target"])
            if i >= 0:
                self.target.setCurrentIndex(i)
            else:
                self.target.setCurrentIndex(self.target.findData(-1)); self.cust.setValue(b["target"])
        if "aspect" in b:
            self.aspect.setCurrentIndex(self.aspect.findData(b["aspect"]))
        if "pace" in b:
            self._pacing = b["pace"]
        if b.get("tags"):
            self.theme.setCurrentIndex(max(0, self.theme.findData(b["tags"][0])))
        if "slowmo" in b:
            self.slowmo.setChecked(b["slowmo"])
        if b.get("title"):
            self.title_e.setText(b["title"])

    def _brief_go(self, b, cloud, out, on_done, go):
        self.apply_brief(b); self.last_brief = b
        self.toast.show_msg(("雲端理解" if cloud else "離線理解") + "：" + CV.describe_brief(b), ms=6000)
        if go:
            self.one_click(out=out, on_done=on_done, brief=b)

    # ---------- R34：剪完後調整 ----------
    def refine(self, text):
        cmds = CV.parse_refine(text)
        if not cmds:
            self.toast.show_msg("看不懂這個調整，可以試試：" + "、".join(CV.REFINES[:6]), ms=4000); return []
        if not self.lib.clip_rows():
            self.toast.show_msg("先做一支影片，再來調整", ms=3000); return []
        st = dict(self._refine, target=self._target() or int(sum(c["end"] - c["start"] for c in self.lib.timeline())) or 60,
                  pace=getattr(self, "_pacing", "平穩"), fx=self.fx.currentData() or "",
                  mood=self._refine.get("mood", ""))
        st, msg = CV.refine_state(cmds, st)
        if "drop" in cmds:
            cid = self.tl.currentItem().data(Qt.UserRole) if self.tl.currentItem() else None
            if cid is None:
                msg[-1] = "「這段不要」：請先在下方時間軸點選要拿掉的片段"
            else:
                locked = {r["id"] for r in self.lib.clip_rows() if r.get("locked")}
                if cid in locked:
                    msg[-1] = "這段已鎖定（🔒），先解鎖才能拿掉"
                else:
                    self.lib.exclude([cid])
        self._refine = {k: st[k] for k in ("people", "music_idx", "mood") if k in st}
        if any(c in cmds for c in ("shorter", "longer")):
            i = self.target.findData(st["target"])
            if i >= 0:
                self.target.setCurrentIndex(i)
            else:
                self.target.setCurrentIndex(self.target.findData(-1)); self.cust.setValue(st["target"])
        if any(c in cmds for c in ("hype", "warm", "calm")):
            self._pacing = st["pace"]
            if st.get("fx") is not None:
                self.fx.setCurrentIndex(max(0, self.fx.findData(st["fx"])))
        if any(c in cmds for c in ("shorter", "longer", "people", "drop")):
            b = getattr(self, "last_brief", {}) or {}
            self.lib.auto_pick(self._target() or st["target"], prefer_tag=b.get("tags") or self.theme.currentData() or None,
                               only_fids=getattr(self, "_only", None), people=st.get("people", 0), smile=bool(b.get("smile")))
        self.refresh(); self.refine_e.clear()
        self.toast.show_msg("；".join(msg) + "。按「產生成品」輸出新版本", ms=6000)
        self.last_refine = msg
        return msg

    # ---------- R35：偏好與我的範本 ----------
    def prefs(self):
        return {"target": self.target.currentData(), "cust": self.cust.value(), "aspect": self.aspect.currentData(),
                "res": self.res.currentData(), "look": self.look_c.currentData(),
                "fx": self.fx.currentData(), "slowmo": self.slowmo.isChecked(),
                "frame": self.frame_c.currentData(), "tstyle": self.tstyle.currentData(), "tanim": self.tanim.currentData(),
                "fade": self.fade.isChecked(), "keep_audio": self.keep_audio.isChecked(), "auto_color": self.auto_col.isChecked(),
                "theme": self.theme.currentData(), "formats": self.formats()}

    def set_prefs(self, d):
        combos = {"aspect": self.aspect, "res": self.res, "look": self.look_c, "fx": self.fx, "frame": self.frame_c, "tstyle": self.tstyle, "tanim": self.tanim,
                  "theme": self.theme}
        for k, w in combos.items():
            if k in d:
                i = w.findData(d[k])
                if i >= 0:
                    w.setCurrentIndex(i)
        if "target" in d:
            i = self.target.findData(d["target"])
            if i >= 0:
                self.target.setCurrentIndex(i)
        if "cust" in d:
            self.cust.setValue(int(d["cust"]))
        for k, w in (("slowmo", self.slowmo), ("fade", self.fade), ("keep_audio", self.keep_audio),
                     ("auto_color", self.auto_col)):
            if k in d:
                w.setChecked(bool(d[k]))
        if "formats" in d:
            for a, c in self.fmt_c.items():
                c.setChecked(a in (d["formats"] or []))

    def save_prefs(self):
        import json
        self.lib.set("prefs", json.dumps(self.prefs()))

    def load_prefs(self):
        import json
        try:
            d = json.loads(self.lib.get("prefs", "") or "{}")
        except ValueError:
            d = {}
        if isinstance(d, dict) and d:
            self.set_prefs(dict(CV.clean_prefs(d), **({"cust": d["cust"]} if "cust" in d else {})))

    def templates(self):
        return CV.templates_load(self.lib.get("my_templates", ""))

    def _tpl_list(self):
        self.tpl_c.blockSignals(True); self.tpl_c.clear()
        t = self.templates()
        self.tpl_c.addItem("（選一個套用）" if t else "（還沒有，先調好設定再存）", "")
        for n in t:
            self.tpl_c.addItem(n, n)
        self.tpl_c.blockSignals(False); self.tpl_del.setEnabled(bool(t))

    def save_template(self, name=None):
        import json
        if name is None:
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "存成我的範本", "範本名稱（例如：IG 直式旅遊）")
            if not ok:
                return
        try:
            t = CV.templates_save(self.templates(), name, self.prefs())
        except ValueError as e:
            self.toast.show_msg(str(e), ms=3000); return
        self.lib.set("my_templates", json.dumps(t, ensure_ascii=False)); self._tpl_list()
        self.tpl_c.setCurrentIndex(self.tpl_c.findData(name.strip()[:30]))
        self.toast.show_msg(f"已存成範本「{name.strip()}」", ms=3000)
        return t

    def apply_template(self, name):
        t = self.templates().get(name or "")
        if not t:
            return
        self.set_prefs(t); self.toast.show_msg(f"已套用我的範本「{name}」", ms=3000)

    def delete_template(self, name=None):
        import json
        name = name or self.tpl_c.currentData()
        t = self.templates()
        if name in t:
            del t[name]; self.lib.set("my_templates", json.dumps(t, ensure_ascii=False)); self._tpl_list()

    # ---------- 設定 / AI ----------
    def open_settings(self):
        dlg = D.SettingsDialog(self, self.lib)
        dlg.applied.connect(self._settings_applied)
        dlg.exec()
        self._settings_applied()

    def _settings_applied(self):
        self._ai_state()

    def _ai_state(self):
        self.cloud = bool(self.lib.get("ai_on", False)) and bool(self.lib.get("ai_key_ok", False)) and bool(ai.get_key())
        self.aiq.setEnabled(True)
        self.aiq.setToolTip("雲端 AI 搜尋（設定中已開啟）" if self.cloud else
                            "本機搜尋，不上傳、不需金鑰。安裝 open_clip 後可懂更多詞（見說明）")

    def ai_search(self):
        q = self.aiq.text().strip()
        if not q:
            self.ai_hits = set()
            for c in self.cards.values():
                c.set_ai(False)
            return
        rows = self.lib.db.execute("SELECT id, thumb FROM clips").fetchall()
        thumbs = [(r[0], r[1]) for r in rows if r[0] in self.cards and r[1] and os.path.exists(r[1])]
        self.aiq.setEnabled(False); self.aierr.hide()
        if not getattr(self, "cloud", False):
            return self._local_search(q)
        self.toast.show_msg(f"正在用雲端 AI 搜尋「{q}」…（可以繼續操作）", ms=90000)

        def done(r):
            self.aiq.setEnabled(True); self.toast.hide()
            kind, val = r
            if kind == "err":
                self.aierr_lab.setText({"key": "金鑰無效，雲端 AI 搜尋暫停", "quota": "已達服務額度上限，請稍後再試",
                                        "off": "目前離線，雲端 AI 搜尋暫停；其他功能照常"}[val])
                self.aierr_btn.setVisible(val == "key"); self.aierr.show(); return
            self.ai_hits = val
            for cid, c in self.cards.items():
                c.set_ai(cid in self.ai_hits)
            self.toast.show_msg(f"找到 {len(self.ai_hits)} 段符合「{q}」", ms=4000)
        self._ai_job = self.run_job(ai_job, self.lib.get("ai_base"), ai.get_key(), self.lib.get("ai_model", "gpt-4o-mini"),
                                    q, thumbs, done=done, failed=lambda m: (self.aiq.setEnabled(True), self._job_failed(m)))
        return self._ai_job

    def _local_search(self, q):
        from .workers import search_job
        self.toast.show_msg(f"正在本機搜尋「{q}」…", ms=60000)

        def done(r):
            ids, mode = r
            self.aiq.setEnabled(True); self.toast.hide()
            self.ai_hits = set(ids)
            for cid, c in self.cards.items():
                c.set_ai(cid in self.ai_hits)
            if mode == "unknown":
                self.toast.show_msg(f"基本搜尋看不懂「{q}」。試試：海邊、夕陽、夜景、雪、森林；"
                                    "或安裝本機 AI 模型（open_clip）以搜尋任何描述", ms=7000)
            elif not ids:
                self.toast.show_msg(f"沒有找到符合「{q}」的片段", ms=4000)
            else:
                tag = "" if mode == "clip" else "（基本色彩搜尋）"
                self.toast.show_msg(f"找到 {len(ids)} 段符合「{q}」{tag}", "只勾選這些",
                                    lambda: (self.lib.apply_selection(ids), self.refresh()), ms=8000)
            self._search_mode = mode
        self._ai_job = self.run_job(search_job, self.root, q, done=done,
                                    failed=lambda m: (self.aiq.setEnabled(True), self._job_failed(m)))
        return self._ai_job

    def closeEvent(self, e):
        self._closed = True
        try:
            self.save_prefs()
        except Exception:
            pass
        self.watch.stop(); self.dev_t.stop()          # 關閉後監看計時器不可再碰已關閉的資料庫
        for j in self.jobs:
            j.cancelled = True
        self.pool.waitForDone(5000)
        for c in self.cards.values():
            c.view.stop()
        self.lib.close()
        super().closeEvent(e)


def main(argv=None):
    app = QApplication(argv or sys.argv)
    app.setApplicationName("精華剪輯")
    try:
        core.find_ffmpeg()
    except Exception as e:  # noqa: BLE001
        D.ErrorDialog(None, "找不到 ffmpeg", f"{e}\n請參考 README 安裝 ffmpeg。", retry=False, friendly=False).exec()
        return 1
    w = Main(); w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
