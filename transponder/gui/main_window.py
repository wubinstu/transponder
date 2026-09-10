"""主窗口: 双侧面板/转发控制/分侧数据预览/落地记录配置/事件日志."""

from __future__ import annotations

import queue
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QComboBox, QFileDialog, QGroupBox, QTextEdit, QMessageBox,
    QSplitter, QFrame, QRadioButton, QSizePolicy,
)

from ..core import Bridge, LogSession, FileRecvSource, FileSendSource, UdpUnicastSource
from .forms import SOURCE_TYPES, _pair
from .source_panel import SourcePanel
from .theme import SwitchToggle

PREVIEW_LIMIT = 400  # 每侧预览最多保留行数


class PreviewPane(QGroupBox):
    """单侧数据预览: 显示开关(转发中即时生效)/HEX/TXT/暂停/清空."""

    def __init__(self, title: str):
        super().__init__(title)
        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        head = QHBoxLayout()
        self.show_sw = SwitchToggle("显示")
        self.show_sw.setChecked(True)
        self.hex_rb = QRadioButton("HEX")
        self.txt_rb = QRadioButton("TXT")
        self.hex_rb.setChecked(True)
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setFixedWidth(56)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.setFixedWidth(56)
        head.addWidget(self.show_sw)
        head.addStretch(1)
        head.addWidget(QLabel("视图:"))
        head.addWidget(self.hex_rb)
        head.addWidget(self.txt_rb)
        head.addWidget(self.pause_btn)
        head.addWidget(self.clear_btn)
        lay.addLayout(head)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("Consolas, Courier New", 9))
        lay.addWidget(self.view)
        self.paused = False
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.clear_btn.clicked.connect(self.view.clear)

    def _toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.setText("继续" if self.paused else "暂停")

    def append(self, data: bytes):
        if not self.show_sw.isChecked() or self.paused:
            return
        if self.hex_rb.isChecked():
            text = " ".join(f"{b:02X}" for b in data[:256])
            if len(data) > 256:
                text += f"  …(共{len(data)}字节)"
        else:
            text = data[:256].decode("utf-8", errors="replace")
        self.view.append(text)
        doc = self.view.document()
        if doc.blockCount() > PREVIEW_LIMIT:
            cur = QTextCursor(doc)
            cur.movePosition(QTextCursor.Start)
            cur.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor,
                             doc.blockCount() - PREVIEW_LIMIT)
            cur.removeSelectedText()


class MainWindow(QMainWindow):
    """转发线程 -> UI 的数据一律经线程安全队列, 由 UI 定时器泵送 (避免跨线程调用 Qt)."""

    PUMP_INTERVAL = 100  # ms
    PUMP_BATCH = 500     # 每次泵送最多处理条数

    def __init__(self, prefill=None):
        super().__init__()
        prefill = prefill or {}
        self.setWindowTitle("数据转发器")
        self.resize(1120, 780)
        self.bridge: Optional[Bridge] = None
        self.session: Optional[LogSession] = None
        self._uiq: "queue.Queue[tuple]" = queue.Queue()
        self._pump = QTimer(self)
        self._pump.timeout.connect(self._drain_uiq)
        self._pump.start(self.PUMP_INTERVAL)

        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(10)

        # 标题
        title = QLabel("数据转发器  ·  Data Transponder")
        title.setObjectName("title")
        root.addWidget(title)

        # M / W 面板
        splitter = QSplitter(Qt.Horizontal)
        self.panel_m = SourcePanel("数据源 M")
        self.panel_w = SourcePanel("数据源 W")
        splitter.addWidget(self.panel_m)
        splitter.addWidget(self.panel_w)
        root.addWidget(splitter, 3)

        # 转发控制条
        bar = QFrame()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(4, 0, 4, 0)
        self.start_btn = QPushButton("▶  开始转发")
        self.stop_btn = QPushButton("■  停止转发")
        self.start_btn.setObjectName("primary")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        f = QFont(); f.setPointSize(11); f.setBold(True)
        self.start_btn.setFont(f); self.stop_btn.setFont(f)
        self.start_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(self._stop)
        bl.addWidget(self.start_btn)
        bl.addWidget(self.stop_btn)
        bl.addStretch(1)
        root.addWidget(bar)

        # 分侧预览
        prev = QSplitter(Qt.Horizontal)
        self.pane_m = PreviewPane("M 数据预览")
        self.pane_w = PreviewPane("W 数据预览")
        prev.addWidget(self.pane_m)
        prev.addWidget(self.pane_w)
        root.addWidget(prev, 2)

        # 落地记录配置
        log_box = QGroupBox("数据落地记录")
        ll = QHBoxLayout(log_box)
        self.log_m_sw = SwitchToggle("记录 M")
        self.log_w_sw = SwitchToggle("记录 W")
        self.log_dir = QLineEdit()
        self.log_dir.setPlaceholderText("选择存储根目录 basedir, 开启后自动创建时间戳文件夹")
        self.browse_btn = QPushButton("浏览")
        self.browse_btn.setFixedWidth(56)
        self.browse_btn.clicked.connect(self._browse_dir)
        self.log_fmt = QComboBox(); self.log_fmt.addItems(["BIN", "TXT"])
        self.log_ts = QSpinBox(); self.log_ts.setRange(0, 600000)
        self.log_ts.setSpecialValueText("无时间戳")
        self.log_ts.setValue(0)
        self.log_ts.setSuffix(" ms")
        self.log_fmt.currentTextChanged.connect(
            lambda t: self.log_ts.setEnabled(t == "TXT"))
        self.log_ts.setEnabled(False)
        ll.addWidget(self.log_m_sw)
        ll.addWidget(self.log_w_sw)
        ll.addWidget(QLabel("格式:")); ll.addWidget(self.log_fmt)
        ll.addWidget(QLabel("时间戳间隔:")); ll.addWidget(self.log_ts)
        ll.addWidget(self.log_dir, 1)
        ll.addWidget(self.browse_btn)
        root.addWidget(log_box)

        # 事件日志
        ev_box = QGroupBox("事件日志")
        el = QHBoxLayout(ev_box)
        self.event_view = QTextEdit()
        self.event_view.setReadOnly(True)
        self.event_view.setMaximumHeight(110)
        clear = QPushButton("清空")
        clear.setFixedWidth(56)
        clear.clicked.connect(self.event_view.clear)
        el.addWidget(self.event_view)
        el.addWidget(clear, alignment=Qt.AlignTop)
        root.addWidget(ev_box)

        self.stat_timer = QTimer(self)
        self.stat_timer.timeout.connect(self._update_stats)

        if prefill:
            self._apply_prefill(prefill)

    # ---- 参数预填充 (命令行带参启动GUI) --------------------------------
    def _apply_prefill(self, pf: dict):
        for side, spec in (("m", pf.get("m")), ("w", pf.get("w"))):
            if not spec:
                continue
            try:
                from ..core.factory import _split_spec
                stype, kv = _split_spec(spec)
            except Exception as e:
                self._log(f"参数 {side} 解析失败: {e}")
                continue
            panel = self.panel_m if side == "m" else self.panel_w
            stype = {"file-send": "file", "file-recv": "file"}.get(stype, stype)  # 规格名->表单名
            for i, (_, cls) in enumerate(SOURCE_TYPES):
                if cls.TYPE == stype:
                    panel.type_combo.setCurrentIndex(i)
                    panel.stack.currentWidget().fill(kv)
                    self._log(f"已填充数据源 {side.upper()}: {spec}")
                    break
            else:
                self._log(f"无法识别的数据源类型: {stype}")
        if pf.get("log_dir"):
            self.log_dir.setText(pf["log_dir"])
        if pf.get("log_m"):
            self.log_m_sw.setChecked(True)
        if pf.get("log_w"):
            self.log_w_sw.setChecked(True)
        if pf.get("log_fmt"):
            self.log_fmt.setCurrentText(pf["log_fmt"].upper())
        if pf.get("log_ts"):
            self.log_ts.setValue(int(pf["log_ts"]))

    # ---- 转发控制 -------------------------------------------------------
    def _start(self):
        if not (self.panel_m.source and self.panel_w.source):
            QMessageBox.information(self, "提示", "请先打开两个数据源 (M 和 W)")
            return
        m, w = self.panel_m.source, self.panel_w.source
        if isinstance(m, FileRecvSource) and isinstance(w, FileRecvSource):
            QMessageBox.warning(self, "提示", "两个都为文件(写)无数据来源, 无法转发")
            return
        if isinstance(m, FileSendSource) and isinstance(w, FileSendSource):
            r = QMessageBox.question(self, "确认",
                                     "文件→文件 将执行单向复制(覆盖目标文件), 继续?",
                                     QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        session = None
        log_m = log_w = None
        if self.log_m_sw.isChecked() or self.log_w_sw.isChecked():
            basedir = self.log_dir.text().strip()
            if not basedir:
                QMessageBox.warning(self, "提示", "请先填写落地记录的存储根目录")
                return
            fmt = self.log_fmt.currentText().lower()
            ts = self.log_ts.value()
            session = LogSession(basedir)
            if self.log_m_sw.isChecked():
                log_m = session.writer("M", fmt, ts)
            if self.log_w_sw.isChecked():
                log_w = session.writer("W", fmt, ts)
            self._log(f"落地记录: {session.dir}")
        self.session = session
        self.bridge = Bridge(m, w, log_m=log_m, log_w=log_w,
                             on_event=lambda msg: self._uiq.put(("event", msg)),
                             on_preview=lambda d, data: self._uiq.put(("preview", d[0], data)))
        self.bridge.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.panel_m.set_editable(False)
        self.panel_w.set_editable(False)
        self.stat_timer.start(500)

    def _stop(self):
        if self.bridge:
            self.bridge.stop()
        self.stat_timer.stop()
        self._update_stats()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.panel_m.set_editable(True)
        self.panel_w.set_editable(True)

    def closeEvent(self, ev):
        self._stop()
        if self.session:
            self.session.close()
        self.panel_m.close_source()
        self.panel_w.close_source()
        super().closeEvent(ev)

    # ---- 回调/刷新 -------------------------------------------------------
    def _drain_uiq(self):
        """把转发线程投递的事件/预览数据搬到 UI (仅本函数在 UI 线程操作控件)."""
        for _ in range(self.PUMP_BATCH):
            try:
                item = self._uiq.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == "event":
                self.event_view.append(item[1])
            elif kind == "preview":
                (self.pane_m if item[1] == "M" else self.pane_w).append(item[2])

    def _log(self, msg: str):
        """UI 线程内直接记录事件 (如预填充提示)."""
        self.event_view.append(msg)

    def _update_stats(self):
        if not self.bridge:
            return
        tm, rm = self.bridge.stats_m2w.snapshot()
        tw, rw = self.bridge.stats_w2m.snapshot()
        self.panel_m.update_stats(tm, rm)
        self.panel_w.update_stats(tw, rw)

    def _browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择落地记录根目录")
        if path:
            self.log_dir.setText(path)
