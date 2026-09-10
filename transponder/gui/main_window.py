"""主窗口: 双侧面板/转发控制/分侧数据预览(含分侧落地记录)/事件日志/主题切换."""

from __future__ import annotations

import os
import queue
import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QComboBox, QFileDialog, QGroupBox, QTextEdit, QMessageBox,
    QSplitter, QFrame, QRadioButton, QSizePolicy,
)

from ..core import Bridge, LogSession, SourceLog, FileRecvSource, FileSendSource
from .forms import SOURCE_TYPES
from .source_panel import SourcePanel
from .theme import SwitchToggle, apply_theme, toast, ASSET_DIR

PREVIEW_LIMIT = 400  # 每侧预览最多保留行数
EVENT_TS = "%H:%M:%S"  # 事件日志时间戳 (毫秒另行拼接, 统一宽度)


class PreviewPane(QGroupBox):
    """单侧数据预览: 显示开关(转发中即时生效)/HEX/TXT/暂停/清空 + 分侧落地记录配置."""

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
        self.clear_btn = QPushButton("清空")
        self.pause_btn.setFixedWidth(64)
        self.clear_btn.setFixedWidth(64)
        head.addWidget(self.show_sw)
        head.addSpacing(8)
        head.addWidget(QLabel("视图:"))
        head.addWidget(self.hex_rb)
        head.addWidget(self.txt_rb)
        head.addWidget(self.pause_btn)
        head.addWidget(self.clear_btn)
        head.addStretch(1)
        lay.addLayout(head)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setAcceptRichText(False)  # 纯文本显示, 原样呈现 (避免 <>& 被当富文本)
        self.view.setFont(QFont("Consolas, Courier New", 9))
        lay.addWidget(self.view, 1)
        # 分侧落地记录配置 (basedir 共用, 放在主窗口控制条)
        rec = QHBoxLayout()
        self.rec_sw = SwitchToggle("记录")
        self.rec_fmt = QComboBox(); self.rec_fmt.addItems(["BIN", "TXT"])
        self.rec_fmt.setFixedWidth(64)
        self.rec_ts = QSpinBox(); self.rec_ts.setRange(0, 600000)
        self.rec_ts.setSpecialValueText("无时间戳")
        self.rec_ts.setValue(0)
        self.rec_ts.setSuffix(" ms")
        self.rec_ts.setFixedWidth(96)
        self.rec_ts.setEnabled(False)
        self.rec_fmt.currentTextChanged.connect(
            lambda t: self.rec_ts.setEnabled(t == "TXT"))
        rec.addWidget(self.rec_sw)
        rec.addWidget(QLabel("格式:"))
        rec.addWidget(self.rec_fmt)
        rec.addWidget(QLabel("时间戳:"))
        rec.addWidget(self.rec_ts)
        rec.addStretch(1)
        lay.addLayout(rec)
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
            # HEX 严格按原始字节显示 (0x0A 显示为 "0A", 不产生真实换行)
            text = " ".join(f"{b:02X}" for b in data[:256])
            if len(data) > 256:
                text += f"  …(共{len(data)}字节)"
        else:
            # TXT 模式才"翻译" (控制字符等按文本呈现)
            text = data[:256].decode("utf-8", errors="replace").rstrip("\n")
        self.view.moveCursor(QTextCursor.End)
        self.view.insertPlainText(text + "\n")
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())
        doc = self.view.document()
        if doc.blockCount() > PREVIEW_LIMIT:
            cur = QTextCursor(doc)
            cur.movePosition(QTextCursor.Start)
            cur.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor,
                             doc.blockCount() - PREVIEW_LIMIT)
            cur.removeSelectedText()

    def record_widgets(self) -> list:
        """落地记录配置控件 (转发开始后锁定)."""
        return [self.rec_sw, self.rec_fmt, self.rec_ts]

    def set_record_editable(self, on: bool):
        for w in self.record_widgets():
            w.setEnabled(on)
        self.rec_ts.setEnabled(on and self.rec_fmt.currentText() == "TXT")


class MainWindow(QMainWindow):
    """转发线程 -> UI 的数据一律经线程安全队列, 由 UI 定时器泵送."""

    PUMP_INTERVAL = 100  # ms
    PUMP_BATCH = 500     # 每次泵送最多处理条数

    def __init__(self, prefill=None):
        super().__init__()
        prefill = prefill or {}
        self.setWindowTitle("MW数据转发器")
        self.setWindowIcon(QIcon(os.path.join(ASSET_DIR, "app-icon.svg")))
        self.resize(1180, 800)
        self.bridge: Optional[Bridge] = None
        self.session: Optional[LogSession] = None
        self._theme = "dark"
        self._rounded = True
        self._uiq: "queue.Queue[tuple]" = queue.Queue()
        self._pump = QTimer(self)
        self._pump.timeout.connect(self._drain_uiq)
        self._pump.start(self.PUMP_INTERVAL)

        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(10)

        # 标题栏: 标题 + 圆角风格 + 主题切换
        head = QHBoxLayout()
        title = QLabel("MW数据转发器")
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch(1)
        self.style_btn = QPushButton("圆角")
        self.style_btn.setFixedWidth(88)
        self.style_btn.clicked.connect(self._toggle_style)
        head.addWidget(self.style_btn)
        self.theme_btn = QPushButton("🌙 浅色主题")
        self.theme_btn.setFixedWidth(110)
        self.theme_btn.clicked.connect(self._toggle_theme)
        head.addWidget(self.theme_btn)
        root.addLayout(head)

        # M / W 面板
        splitter = QSplitter(Qt.Horizontal)
        self.panel_m = SourcePanel("数据源 M")
        self.panel_w = SourcePanel("数据源 W")
        splitter.addWidget(self.panel_m)
        splitter.addWidget(self.panel_w)
        splitter.setHandleWidth(14)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 3)

        # 转发控制条: 开始/停止 + 共用落地目录
        bar = QFrame()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(4, 0, 4, 0)
        bl.setSpacing(10)
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
        bl.addSpacing(20)
        bl.addWidget(QLabel("记录目录:"))
        self.log_dir = QLineEdit()
        self.log_dir.setPlaceholderText("落地记录根目录 basedir (任一侧开启记录后自动创建时间戳文件夹)")
        bl.addWidget(self.log_dir, 1)
        self.browse_btn = QPushButton("浏览")
        self.browse_btn.setFixedWidth(64)
        self.browse_btn.clicked.connect(self._browse_dir)
        bl.addWidget(self.browse_btn)
        root.addWidget(bar)

        # 分侧预览 (含分侧记录配置)
        prev = QSplitter(Qt.Horizontal)
        self.pane_m = PreviewPane("M 数据预览")
        self.pane_w = PreviewPane("W 数据预览")
        prev.addWidget(self.pane_m)
        prev.addWidget(self.pane_w)
        prev.setHandleWidth(14)
        prev.setChildrenCollapsible(False)
        prev.setStretchFactor(0, 1)
        prev.setStretchFactor(1, 1)
        root.addWidget(prev, 2)

        # 事件日志
        ev_box = QGroupBox("事件日志")
        el = QHBoxLayout(ev_box)
        self.event_view = QTextEdit()
        self.event_view.setReadOnly(True)
        self.event_view.setMaximumHeight(120)
        clear = QPushButton("清空")
        clear.setFixedWidth(64)
        clear.clicked.connect(self.event_view.clear)
        el.addWidget(self.event_view)
        el.addWidget(clear, alignment=Qt.AlignTop)
        root.addWidget(ev_box)

        self.stat_timer = QTimer(self)
        self.stat_timer.timeout.connect(self._update_stats)

        if prefill:
            self._apply_prefill(prefill)

    # ---- 主题/风格 -------------------------------------------------------
    def _toggle_theme(self):
        self._theme = "light" if self._theme == "dark" else "dark"
        apply_theme(self._theme, self._rounded)
        self.theme_btn.setText("🌙 浅色主题" if self._theme == "dark" else "☀ 深色主题")

    def _toggle_style(self):
        self._rounded = not self._rounded
        apply_theme(self._theme, self._rounded)
        self.style_btn.setText("圆角" if self._rounded else "直角")

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
            self.pane_m.rec_sw.setChecked(True)
        if pf.get("log_w"):
            self.pane_w.rec_sw.setChecked(True)
        for pf_key, pane in (("log_fmt_m", self.pane_m), ("log_fmt_w", self.pane_w)):
            if pf.get(pf_key):
                pane.rec_fmt.setCurrentText(pf[pf_key].upper())
        for pf_key, pane in (("log_ts_m", self.pane_m), ("log_ts_w", self.pane_w)):
            if pf.get(pf_key):
                pane.rec_ts.setValue(int(pf[pf_key]))

    # ---- 转发控制 -------------------------------------------------------
    def _start(self):
        if not (self.panel_m.source and self.panel_w.source):
            toast(self, "请先打开两个数据源 (M 和 W)", "error")
            return
        m, w = self.panel_m.source, self.panel_w.source
        if isinstance(m, FileRecvSource) and isinstance(w, FileRecvSource):
            toast(self, "两个都为文件(写)无数据来源, 无法转发", "error")
            return
        if isinstance(m, FileSendSource) and isinstance(w, FileSendSource):
            r = QMessageBox.question(self, "确认",
                                     "文件→文件 将执行单向复制(覆盖目标文件), 继续?",
                                     QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        session = None
        log_m = log_w = None
        want_m = self.pane_m.rec_sw.isChecked()
        want_w = self.pane_w.rec_sw.isChecked()
        if want_m or want_w:
            basedir = self.log_dir.text().strip()
            if not basedir:
                toast(self, "请先填写落地记录的存储根目录", "error")
                return
            session = LogSession(basedir)
            if want_m:
                session_path = session.writer("M", self.pane_m.rec_fmt.currentText().lower(),
                                              self.pane_m.rec_ts.value())
                log_m = session_path
            if want_w:
                log_w = session.writer("W", self.pane_w.rec_fmt.currentText().lower(),
                                       self.pane_w.rec_ts.value())
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
        # 落地记录配置锁定 (停止转发后才能修改)
        self.pane_m.set_record_editable(False)
        self.pane_w.set_record_editable(False)
        self.log_dir.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.stat_timer.start(500)

    def _stop(self):
        if self.bridge:
            self.bridge.stop()
        self.stat_timer.stop()
        # 停止后速率清零显示 (保留累计总量), 避免冻结在最后一帧
        if self.bridge:
            tm, _ = self.bridge.stats_m2w.snapshot()
            tw, _ = self.bridge.stats_w2m.snapshot()
            self.panel_m.update_stats(tm, 0)
            self.panel_w.update_stats(tw, 0)
        # 立刻释放落地记录文件句柄 (不再占用日志文件与时间戳文件夹)
        if self.session:
            self.session.close()
            self.session = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.panel_m.set_editable(True)
        self.panel_w.set_editable(True)
        self.pane_m.set_record_editable(True)
        self.pane_w.set_record_editable(True)
        self.log_dir.setEnabled(True)
        self.browse_btn.setEnabled(True)

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
                self.event_view.append(self._ts() + "  " + item[1])
            elif kind == "preview":
                (self.pane_m if item[1] == "M" else self.pane_w).append(item[2])

    @staticmethod
    def _ts() -> str:
        """统一宽度时间戳 HH:MM:SS.mmm."""
        now = time.time()
        return time.strftime(EVENT_TS, time.localtime(now)) + f".{int(now * 1000) % 1000:03d}"

    def _log(self, msg: str):
        """UI 线程内直接记录事件 (如预填充提示)."""
        self.event_view.append(self._ts() + "  " + msg)

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
