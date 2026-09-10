"""主题系统: 黑/白双主题 QSS+调色板, 下拉/SpinBox 箭头图标, 滑动开关, 浮动通知(Toast)."""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QPropertyAnimation, QRectF, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel, QWidget

ASSET_DIR = os.path.join(os.path.dirname(__file__), "assets")

# ---- 颜色令牌 -------------------------------------------------------------
DARK = {
    "name": "dark",
    "window": "#171923", "card": "#20232F", "card2": "#2A2E40",
    "border": "#2E3345", "border2": "#3A3F55",
    "text": "#E8EAF0", "text_dim": "#8A90A5",
    "accent": "#4C62F5", "accent_hi": "#6B7BFF",
    "danger": "#E8556D", "success": "#7FD1A8",
    "view_bg": "#14161F",
    "disabled_bg": "#232635", "disabled_fg": "#5C617A",
    "sel_bg": "#4C62F5",
}

LIGHT = {
    "name": "light",
    "window": "#F3F4F8", "card": "#FFFFFF", "card2": "#ECEDF3",
    "border": "#DDE0EA", "border2": "#C6CBD9",
    "text": "#252A3A", "text_dim": "#6B7188",
    "accent": "#3D52E0", "accent_hi": "#5B6CFF",
    "danger": "#D63A55", "success": "#1E9E6A",
    "view_bg": "#FAFBFD",
    "disabled_bg": "#EFF0F4", "disabled_fg": "#A6ABBD",
    "sel_bg": "#3D52E0",
}


def _url(fname: str) -> str:
    # 注意: QSS 的 url() 在 Windows/PySide6 下不识别 file:/// 前缀, 需用正斜杠绝对路径
    return ASSET_DIR.replace("\\", "/") + "/" + fname


QSS_URL_PREFIX = ""  # 兼容占位 (不再使用)


def build_qss(t: dict) -> str:
    return f"""
* {{ font-family: "Segoe UI", "Microsoft YaHei", sans-serif; font-size: 13px;
     color: {t['text']}; }}
QMainWindow, QWidget#root {{ background: {t['window']}; }}
QGroupBox {{
    background: {t['card']}; border: 1px solid {t['border']}; border-radius: 10px;
    margin-top: 14px; padding: 12px 10px 10px 10px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 6px;
    color: {t['accent']}; }}
QLabel {{ background: transparent; }}
QLabel#hint {{ color: {t['text_dim']}; font-size: 12px; font-weight: 400; }}
QLabel#stat {{ color: {t['success']}; font-size: 12px; font-weight: 600; }}
QLabel#title {{ font-size: 18px; font-weight: 700; color: {t['text']}; }}

QComboBox, QSpinBox, QLineEdit, QListWidget, QTextEdit {{
    background: {t['card2']}; border: 1px solid {t['border2']}; border-radius: 6px;
    padding: 4px 8px; selection-background-color: {t['sel_bg']};
}}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border: 1px solid {t['accent']}; }}
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled {{
    color: {t['disabled_fg']}; background: {t['disabled_bg']}; border-color: {t['border']}; }}
QComboBox::drop-down {{ border: none; width: 26px; subcontrol-origin: padding;
    subcontrol-position: top right; }}
QComboBox::down-arrow {{ image: url({_url(f"arrow-down-{t['name']}.png")}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {t['card']}; border: 1px solid {t['border2']}; border-radius: 6px;
    outline: 0; padding: 4px; selection-background-color: {t['sel_bg']};
    selection-color: #FFFFFF; }}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border; border: none; background: transparent; width: 18px; }}
QSpinBox::up-button {{ subcontrol-position: top right; border-bottom: none; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; border-top: none; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {t['border']}; }}
QSpinBox::up-arrow {{ image: url({_url(f"spin-up-{t['name']}.png")}); width: 10px; height: 8px; }}
QSpinBox::down-arrow {{ image: url({_url(f"spin-down-{t['name']}.png")}); width: 10px; height: 8px; }}

QPushButton {{
    background: {t['card2']}; border: 1px solid {t['border2']}; border-radius: 6px;
    padding: 6px 16px; font-weight: 600; color: {t['text']};
}}
QPushButton:hover {{ background: {t['border']}; }}
QPushButton:pressed {{ background: {t['border2']}; }}
QPushButton:disabled {{ color: {t['disabled_fg']}; background: {t['disabled_bg']};
    border-color: {t['border']}; }}
QPushButton#primary {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['accent_hi']}, stop:1 {t['accent']});
    border: none; color: white; padding: 8px 22px; font-size: 14px;
}}
QPushButton#primary:hover {{ background: {t['accent_hi']}; }}
QPushButton#danger {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #F06479, stop:1 {t['danger']});
    border: none; color: white; padding: 8px 22px; font-size: 14px;
}}
QPushButton#danger:disabled {{ background: {t['disabled_bg']};
    color: {t['disabled_fg']}; }}

QTextEdit, QListWidget {{
    background: {t['view_bg']}; font-family: "Consolas", "Courier New", monospace;
    font-size: 12px; border: 1px solid {t['border']}; border-radius: 8px;
}}
QSlider::groove:horizontal {{ height: 6px; border-radius: 3px; background: {t['card2']}; }}
QSlider::sub-page:horizontal {{ border-radius: 3px; background: {t['accent']}; }}
QSlider::handle:horizontal {{
    width: 16px; height: 16px; margin: -5px 0; border-radius: 8px;
    background: {t['text']}; border: 1px solid {t['border2']};
}}
QSlider::handle:horizontal:hover {{ background: white; }}
QSlider::handle:disabled {{ background: {t['disabled_fg']}; }}
QSlider::groove:horizontal:disabled {{ background: {t['disabled_bg']}; }}

QProgressBar {{
    background: {t['card2']}; border: none; border-radius: 5px; height: 10px;
    text-align: center; color: {t['text']}; font-size: 11px;
}}
QProgressBar::chunk {{ border-radius: 5px; background: {t['accent']}; }}

QRadioButton {{ spacing: 6px; }}
QRadioButton::indicator {{
    width: 15px; height: 15px; border-radius: 8px; border: 1px solid {t['border2']};
    background: {t['card2']};
}}
QRadioButton::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}
QListWidget::item {{ padding: 4px 8px; border-radius: 4px; color: {t['text']}; }}
QListWidget::item:selected {{ background: {t['sel_bg']}; color: white; }}
QSplitter::handle {{ background: {t['border']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {t['border2']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t['text_dim']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {t['card']}; color: {t['text']}; border: 1px solid {t['border2']}; }}
"""


def _palette(t: dict) -> QPalette:
    """整体调色板: 兜住 QSS 覆盖不到的原生部分 (弹层边缘/工具提示等)."""
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(t["window"]))
    pal.setColor(QPalette.WindowText, QColor(t["text"]))
    pal.setColor(QPalette.Base, QColor(t["card2"]))
    pal.setColor(QPalette.AlternateBase, QColor(t["card"]))
    pal.setColor(QPalette.Text, QColor(t["text"]))
    pal.setColor(QPalette.Button, QColor(t["card2"]))
    pal.setColor(QPalette.ButtonText, QColor(t["text"]))
    pal.setColor(QPalette.Highlight, QColor(t["sel_bg"]))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ToolTipBase, QColor(t["card"]))
    pal.setColor(QPalette.ToolTipText, QColor(t["text"]))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(t["disabled_fg"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(t["disabled_fg"]))
    return pal


def apply_theme(theme: str = "dark") -> dict:
    """应用主题到整个应用, 返回主题令牌表."""
    t = DARK if theme == "dark" else LIGHT
    app = QApplication.instance()
    app.setStyleSheet(build_qss(t))
    app.setPalette(_palette(t))
    return t


class SwitchToggle(QWidget):
    """滑动开关 (替换 QCheckBox 的勾选框视觉)."""

    toggled = Signal(bool)

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._checked = False
        self._text = text
        self.setFixedHeight(24)
        self.setCursor(Qt.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, on: bool) -> None:
        if self._checked != on:
            self._checked = on
            self.toggled.emit(on)
        self.update()

    def mousePressEvent(self, ev) -> None:
        self.setChecked(not self._checked)

    def sizeHint(self):
        w = 46 + (self.fontMetrics().horizontalAdvance(self._text) + 8 if self._text else 0)
        from PySide6.QtCore import QSize
        return QSize(w, 24)

    def paintEvent(self, ev) -> None:
        t = {"dark": DARK, "light": LIGHT}.get(
            "light" if QApplication.instance().palette().window().color().value() > 128 else "dark")
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = 20
        track = QRectF(2, (self.height() - h) / 2, 42, h)
        knob_r = h - 6
        if self._checked:
            grad = QLinearGradient(track.topLeft(), track.bottomLeft())
            grad.setColorAt(0, QColor(t["accent_hi"]))
            grad.setColorAt(1, QColor(t["accent"]))
            p.setBrush(grad)
            knob_x = track.right() - knob_r - 3
        else:
            p.setBrush(QColor(t["border2"]))
            knob_x = track.left() + 3
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(track, h / 2, h / 2)
        p.setBrush(QColor("#E8EAF0") if t is DARK else QColor("#FFFFFF"))
        p.drawEllipse(QPointF(knob_x + knob_r / 2, track.center().y()), knob_r / 2, knob_r / 2)
        if self._text:
            p.setPen(QColor(t["text"]))
            p.drawText(QRectF(track.right() + 8, 0, self.width() - track.right() - 8,
                              self.height()), Qt.AlignVCenter, self._text)
        p.end()


class Toast(QLabel):
    """浮动通知: 自动淡出消失, 无需点击."""

    DURATION = 2600  # ms

    _kind_color = {"info": None, "success": "success", "error": "danger"}

    def __init__(self, parent: QWidget, text: str, kind: str = "info"):
        super().__init__(parent)
        t = {"dark": DARK, "light": LIGHT}.get(
            "light" if QApplication.instance().palette().window().color().value() > 128 else "dark")
        color = t.get(self._kind_color.get(kind) or "accent", t["accent"])
        self.setText(text)
        self.setWordWrap(True)
        self.setMaximumWidth(360)
        self.setStyleSheet(f"""
            background: {t['card']}; color: {t['text']};
            border: 1px solid {color}; border-left: 4px solid {color};
            border-radius: 8px; padding: 10px 14px; font-weight: 600;
        """)
        self.adjustSize()
        # 堆叠: 已有通知则往上排
        y = parent.height() - self.height() - 18
        for child in parent.findChildren(Toast):
            if child is not self and child.isVisible():
                y = min(y, child.y() - self.height() - 8)
        self.move(parent.width() - self.width() - 18, y)
        self.show()
        self.raise_()
        eff = QGraphicsOpacityEffect(self)
        eff.setOpacity(0.0)
        self.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(150)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start()
        QTimer.singleShot(self.DURATION, self._fade_out)
        self._eff = eff  # 防止被GC

    def _fade_out(self) -> None:
        anim = QPropertyAnimation(self._eff, b"opacity", self)
        anim.setDuration(400)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(self.deleteLater)
        anim.start()
        self._anim = anim


def toast(parent: QWidget, text: str, kind: str = "info") -> None:
    """在窗口右下角弹出自动消失的浮动通知."""
    if parent is None:
        return
    Toast(parent, text, kind)
