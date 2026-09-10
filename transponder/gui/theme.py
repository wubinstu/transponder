"""现代深色主题: 全局 QSS + 滑动开关控件."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Property, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget

QSS = """
* { font-family: "Segoe UI", "Microsoft YaHei", sans-serif; font-size: 13px; color: #E8EAF0; }
QMainWindow, QWidget#root { background: #171923; }
QGroupBox {
    background: #20232F; border: 1px solid #2E3345; border-radius: 10px;
    margin-top: 14px; padding: 12px 10px 10px 10px; font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; color: #9FB3FF; }
QLabel { background: transparent; }
QLabel#hint { color: #8A90A5; font-size: 12px; font-weight: 400; }
QLabel#stat { color: #7FD1A8; font-size: 12px; font-weight: 600; }
QLabel#title { font-size: 17px; font-weight: 700; color: #FFFFFF; }
QComboBox, QSpinBox, QLineEdit {
    background: #2A2E40; border: 1px solid #3A3F55; border-radius: 6px;
    padding: 5px 8px; selection-background-color: #4C62F5;
}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus { border: 1px solid #4C62F5; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #2A2E40; border: 1px solid #3A3F55; selection-background-color: #4C62F5;
}
QPushButton {
    background: #2E3348; border: 1px solid #3D4360; border-radius: 6px;
    padding: 6px 16px; font-weight: 600;
}
QPushButton:hover { background: #383E58; }
QPushButton:pressed { background: #2A2F45; }
QPushButton:disabled { color: #5C617A; background: #242736; }
QPushButton#primary {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #5B6CFF, stop:1 #4453E8);
    border: none; color: white; padding: 8px 22px; font-size: 14px;
}
QPushButton#primary:hover { background: #6B7BFF; }
QPushButton#primary:disabled { background: #33385A; color: #6A6F8C; }
QPushButton#danger {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #E8556D, stop:1 #C93A55);
    border: none; color: white; padding: 8px 22px; font-size: 14px;
}
QPushButton#danger:hover { background: #F06479; }
QPushButton#danger:disabled { background: #4A2E3C; color: #7A5E6C; }
QTextEdit, QListWidget {
    background: #14161F; border: 1px solid #2E3345; border-radius: 8px;
    font-family: "Consolas", "Courier New", monospace; font-size: 12px;
}
QSlider::groove:horizontal { height: 6px; border-radius: 3px; background: #2A2E40; }
QSlider::sub-page:horizontal { border-radius: 3px; background: #4C62F5; }
QSlider::handle:horizontal {
    width: 16px; height: 16px; margin: -5px 0; border-radius: 8px; background: #E8EAF0;
}
QSlider::handle:horizontal:hover { background: white; }
QSlider::handle:disabled { background: #5C617A; }
QProgressBar {
    background: #2A2E40; border: none; border-radius: 5px; height: 10px; text-align: center;
    color: #E8EAF0; font-size: 11px;
}
QProgressBar::chunk { border-radius: 5px; background: #4C62F5; }
QRadioButton { spacing: 6px; }
QRadioButton::indicator { width: 15px; height: 15px; border-radius: 8px; border: 1px solid #3A3F55; background: #2A2E40; }
QRadioButton::indicator:checked { background: #4C62F5; border-color: #4C62F5; }
QListWidget::item { padding: 4px 8px; border-radius: 4px; }
QListWidget::item:selected { background: #4C62F5; color: white; }
QSplitter::handle { background: #2E3345; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #3A3F55; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #4A5070; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""


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
        return QSize(w, 24)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = 20
        track = QRectF(2, (self.height() - h) / 2, 42, h)
        knob_r = h - 6
        if self._checked:
            grad = QLinearGradient(track.topLeft(), track.bottomLeft())
            grad.setColorAt(0, QColor("#5B6CFF")); grad.setColorAt(1, QColor("#4453E8"))
            p.setBrush(grad)
            knob_x = track.right() - knob_r - 3
        else:
            p.setBrush(QColor("#3A3F55"))
            knob_x = track.left() + 3
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(track, h / 2, h / 2)
        p.setBrush(QColor("#E8EAF0"))
        p.drawEllipse(QPointF(knob_x + knob_r / 2, track.center().y()), knob_r / 2, knob_r / 2)
        if self._text:
            p.setPen(QColor("#E8EAF0"))
            p.drawText(QRectF(track.right() + 8, 0, self.width() - track.right() - 8,
                              self.height()), Qt.AlignVCenter, self._text)
        p.end()
