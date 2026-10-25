"""深色主題 QSS（數值對應 DESIGN.md／mockup.html 的 CSS 變數）。"""
import os, sys

PF = os.environ.get("INSTA_PF") or ("mac" if sys.platform == "darwin" else "win")
MOD = "⌘" if PF == "mac" else "Ctrl+"


def key(mac, win):
    """依平台回傳快捷鍵的顯示文字。"""
    return mac if PF == "mac" else win


BG, PANEL, CARD, LINE, LINE2 = "#141414", "#1d1d1d", "#222222", "#707070", "#3a3a3a"
TX, TX2, ACC, WARN, ERR, OK = "#EEEEEE", "#B0B0B0", "#FFC400", "#FFA000", "#FF6B6B", "#8FD18F"

QSS = f"""
* {{ color:{TX}; font-size:13px; }}
QMainWindow, QDialog, QWidget#root {{ background:{BG}; }}
QWidget#panel, QFrame#panel {{ background:{PANEL}; }}
QLabel[sec="true"] {{ color:{TX2}; }}
QLabel[small="true"] {{ font-size:12px; }}
QLabel[err="true"] {{ color:#FF9C9C; font-size:12px; }}
QLabel[h="true"] {{ font-size:16px; font-weight:700; }}
QPushButton {{ background:#2c2c2c; border:1px solid #7A7A7A; border-radius:6px; padding:5px 11px; min-height:22px; }}
QPushButton:hover {{ border-color:#A8A8A8; }}
QPushButton:focus {{ outline:none; border:2px solid #FFFFFF; }}
QPushButton:disabled {{ color:#8A8A8A; border:1px solid #767676; background:#242424; }}
QPushButton[primary="true"] {{ background:{ACC}; color:#111111; border:0; font-weight:700; font-size:14px; padding:8px 18px; border-radius:8px; }}
QPushButton[primary="true"]:focus {{ border:2px solid #FFFFFF; }}
QPushButton[primary="true"]:disabled {{ background:#3d3520; color:#B0A070; }}
QPushButton[danger="true"] {{ color:#FFB3B3; border:1px solid {ERR}; background:#2c2c2c; }}
QPushButton[danger="true"]:disabled {{ color:#8A8A8A; border:1px solid #767676; background:#242424; }}
QPushButton[link="true"] {{ background:transparent; border:0; color:#9CC3FF; text-decoration:underline; padding:0 4px; }}
QPushButton[tog="true"] {{ background:transparent; border:0; font-weight:700; font-size:14px; text-align:left; }}
QPushButton[tog="true"]:focus {{ border:2px solid #FFFFFF; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background:#262626; border:1px solid {LINE}; border-radius:6px; padding:4px 6px; min-height:22px; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border:2px solid #FFFFFF; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color:#8A8A8A; background:#202020; border:1px solid #767676; }}
QSpinBox[invalid="true"] {{ border:2px solid {ERR}; }}
QListWidget {{ background:{PANEL}; border:0; outline:none; }}
QListWidget::item {{ padding:6px; border-left:3px solid transparent; }}
QListWidget::item:selected {{ background:#3d3520; border-left:3px solid {ACC}; color:{TX}; }}
QListWidget#timeline {{ background:#1a1a1a; }}
QListWidget#timeline::item {{ background:#2a2a2a; border:1px solid {LINE}; border-radius:6px; margin:4px; padding:6px 10px; }}
QListWidget#timeline::item:selected {{ border:2px solid {ACC}; padding:5px 9px; background:#3d3520; }}
QFrame#card {{ background:{CARD}; border:2px solid {LINE}; border-radius:8px; }}
QFrame#card[on="true"] {{ border:2px solid {ACC}; }}
QFrame#card:focus {{ border:2px solid #FFFFFF; }}
QFrame#card[on="true"]:focus {{ border:3px solid #FFFFFF; }}   /* R69：焦點環一律白色（SPEC §2.4） */
QFrame#card[state="error"] {{ border:2px solid {ERR}; }}
QFrame#banner {{ background:#262626; border:1px solid {LINE}; border-radius:6px; }}
QFrame#dropzone {{ background:#1a1a1a; border:2px dashed #8A8A8A; border-radius:16px; }}
QFrame#toast {{ background:#333333; border:1px solid #7A7A7A; border-radius:8px; }}
QFrame#aierr {{ background:#3a2424; border:1px solid {ERR}; border-radius:6px; }}
QTabWidget::pane {{ border:1px solid {LINE2}; }}
QTabBar::tab {{ background:#262626; padding:6px 12px; border:1px solid {LINE2}; }}
QTabBar::tab:selected {{ background:#3d3520; border-bottom:2px solid {ACC}; }}
QProgressBar {{ background:#262626; border:1px solid {LINE}; border-radius:4px; text-align:center; }}
QProgressBar::chunk {{ background:{ACC}; }}
QCheckBox::indicator, QRadioButton::indicator {{ width:16px; height:16px; background:#1D1D1D; border:2px solid #8A8A8A; border-radius:3px; }}
QRadioButton::indicator {{ border-radius:9px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background:{ACC}; border:2px solid {ACC}; }}
QCheckBox::indicator:focus {{ border:2px solid #FFFFFF; }}
QCheckBox::indicator:disabled {{ background:#202020; border:2px solid #555555; }}
QPushButton[accent2="true"] {{ background:#2C2C2C; color:{ACC}; border:1px solid {ACC}; font-weight:700; padding:7px 14px; border-radius:8px; }}
QPushButton[accent2="true"]:focus {{ border:2px solid #FFFFFF; }}
QPushButton[accent2="true"]:disabled {{ color:#8A8A8A; border:1px solid #767676; background:#242424; }}
QToolTip {{ background:#333; color:#EEE; border:1px solid #7A7A7A; }}
QToolBar {{ background:{PANEL}; border:0; border-bottom:1px solid {LINE2}; spacing:6px; padding:4px; }}
QToolButton {{ color:{TX}; background:#2c2c2c; border:1px solid #7A7A7A; border-radius:6px; padding:4px 10px; }}
QToolButton:focus {{ border:2px solid #FFFFFF; }}
QScrollArea {{ border:0; background:{BG}; }}
"""


def prop(w, **kv):
    """設定 QSS 動態屬性並重新套用樣式。"""
    for k, v in kv.items():
        w.setProperty(k, v)
    w.style().unpolish(w); w.style().polish(w)
    return w


def apply(app):
    """深色調色盤 + QSS；沒有自己 QSS 的元件（例如帶局部樣式的標籤）也不會變成淺色底。"""
    from PySide6.QtGui import QPalette, QColor
    app.setStyle("Fusion")
    p = QPalette()
    for role, c in ((QPalette.Window, BG), (QPalette.WindowText, TX), (QPalette.Base, "#262626"),
                    (QPalette.AlternateBase, PANEL), (QPalette.Text, TX), (QPalette.Button, "#2c2c2c"),
                    (QPalette.ButtonText, TX), (QPalette.Highlight, ACC), (QPalette.HighlightedText, "#111111"),
                    (QPalette.ToolTipBase, "#333333"), (QPalette.ToolTipText, TX), (QPalette.PlaceholderText, "#9A9A9A")):
        p.setColor(role, QColor(c))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#8A8A8A"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#8A8A8A"))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#8A8A8A"))
    app.setPalette(p)
    app.setStyleSheet(QSS)
