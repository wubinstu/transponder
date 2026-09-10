"""单侧数据源面板: 类型选择/参数表单/打开关闭/状态/对端列表/文件进度/流量统计."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QComboBox, QStackedWidget, QPushButton,
    QLabel, QListWidget, QProgressBar, QAbstractItemView, QWidget,
)

from ..core import DataSource, FileSendSource, SerialSource
from .forms import SOURCE_TYPES
from .theme import toast


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def _repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


class PanelSignals(QObject):
    """把数据源工作线程的回调转成 UI 线程信号."""

    state = Signal(str)
    peers_changed = Signal()
    progress = Signal(int, int)


class SourcePanel(QGroupBox):
    """一侧数据源面板 (M 或 W)."""

    def __init__(self, title: str):
        super().__init__(title)
        self.source: Optional[DataSource] = None
        self.sig = PanelSignals()
        self.sig.state.connect(self._set_status)
        self.sig.peers_changed.connect(self._refresh_peers)
        self.sig.progress.connect(self._set_progress)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        top = QHBoxLayout()
        self.type_combo = QComboBox()
        for name, _ in SOURCE_TYPES:
            self.type_combo.addItem(name)
        self.open_btn = QPushButton("打开")
        self.open_btn.setObjectName("btn_open")  # 绿色; 打开后变 btn_close(红)
        self.open_btn.setFixedWidth(72)
        self.open_btn.clicked.connect(self._toggle)
        top.addWidget(self.type_combo, 1)
        top.addWidget(self.open_btn)
        lay.addLayout(top)

        self.stack = QStackedWidget()
        for _, cls in SOURCE_TYPES:
            self.stack.addWidget(cls())
        self.type_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        lay.addWidget(self.stack)

        # 对端列表 (TCP服务端/组播/广播 打开后显示), 紧跟表单下方, 向上对齐
        self.peer_list = QListWidget()
        self.peer_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.peer_list.setMaximumHeight(88)
        self.peer_btn_primary = QPushButton("设为主要对端")
        self.peer_btn_all = QPushButton("全部")
        self.peer_btn_primary.setFixedHeight(26)
        self.peer_btn_all.setFixedHeight(26)
        self.peer_btn_primary.clicked.connect(self._set_primary)
        self.peer_btn_all.clicked.connect(self._clear_primary)
        pb = QHBoxLayout()
        pb.addWidget(self.peer_btn_primary, 1)
        pb.addWidget(self.peer_btn_all, 1)
        self.peer_box = QVBoxLayout()
        self.peer_box.addWidget(self.peer_list)
        self.peer_box.addLayout(pb)
        lay.addLayout(self.peer_box)
        self._hide_peers()

        self.status = QLabel("未打开")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        # 文件发送进度条 (仅文件读源打开后显示)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        lay.addWidget(self.progress)

        # 流量统计 (该源数据产生速率/累计)
        self.stat_lbl = QLabel("速率 --  |  共 --")
        self.stat_lbl.setObjectName("stat")
        lay.addWidget(self.stat_lbl)

    # ---- 打开/关闭 -----------------------------------------------------
    def current_form(self):
        return self.stack.currentWidget()

    def _toggle(self):
        if self.source:
            self.close_source()
            return
        try:
            src = self.current_form().build()
            src.open()
        except Exception as e:
            toast(self.window(), f"打开失败: {e}", "error")
            return
        self.source = src
        # 面板自身关心的回调: 状态/对端/进度 (转发数据回调由 Bridge 注入)
        src.set_callbacks(on_state=lambda msg: self.sig.state.emit(msg),
                          on_peers=lambda: self.sig.peers_changed.emit(),
                          on_progress=lambda d, t: self.sig.progress.emit(d, t))
        self._set_status("已打开")
        self.open_btn.setText("关闭")
        self.open_btn.setObjectName("btn_close")
        _repolish(self.open_btn)
        self.type_combo.setEnabled(False)
        self._apply_form_lock(True)
        # 文件发送源: 限速控件保持可用 (转发中动态调速)
        if isinstance(src, FileSendSource):
            form = self.current_form()
            if hasattr(form, "on_rate_change"):
                form.on_rate_change = src.set_rate
        # 自动端口回显 (表单钩子)
        on_opened = getattr(self.current_form(), "on_opened", None)
        if on_opened:
            try:
                on_opened(src)
            except Exception:
                pass
        self._update_dynamic_widgets()

    def close_source(self):
        if self.source:
            self.source.close()
            self.source = None
        self._set_status("未打开")
        self.open_btn.setText("打开")
        self.open_btn.setObjectName("btn_open")
        _repolish(self.open_btn)
        self.type_combo.setEnabled(True)
        self._apply_form_lock(False)
        # 恢复表单自身的联动状态 (如 TCP客户端 自动分配开关)
        sync = getattr(self.current_form(), "sync_states_after_close", None) \
            or getattr(self.current_form(), "sync_states", None)
        if sync:
            sync()
        self._hide_peers()
        self.peer_list.clear()
        self.progress.hide()
        self.stat_lbl.setText("速率 --  |  共 --")

    def set_editable(self, on: bool):
        """转发开始后禁用打开/类型切换, 停止后恢复 (文件限速滑块按其自身联动规则)."""
        self.open_btn.setEnabled(on)
        self.type_combo.setEnabled(on and self.source is None)
        if self.source is not None:
            self._apply_form_lock(True)  # 保持锁定(含限速豁免)
        else:
            self._apply_form_lock(not on)

    # ---- 表单锁定 -------------------------------------------------------
    def _apply_form_lock(self, locked: bool) -> None:
        """锁定/解锁参数表单. 逐个控件设置而非禁用父容器(否则会阻断子控件);
        豁免限速控件及其祖先/后代容器, 保证整条交互链可用."""
        keep: list[QWidget] = []
        if locked and isinstance(self.source, FileSendSource):
            keep = self.current_form().rate_widgets()
        self.stack.setEnabled(True)

        def exempt(w: QWidget) -> bool:
            return any(w is k or w.isAncestorOf(k) or k.isAncestorOf(w) for k in keep)

        for w in self.stack.findChildren(QWidget):
            if not locked or not exempt(w):
                w.setEnabled(not locked)
        if locked:
            # 重新应用表单内部联动 (不限速时滑块应禁用等)
            refresh = getattr(self.current_form(), "refresh_widget_states", None)
            if refresh:
                refresh()
        else:
            # 解锁时恢复每一个表单自身的联动状态 (切换类型后新表单也要正确)
            for i in range(self.stack.count()):
                sync = getattr(self.stack.widget(i), "sync_states", None)
                if sync:
                    sync()

    # ---- 动态区域 -------------------------------------------------------
    def _update_dynamic_widgets(self):
        src = self.source
        if isinstance(src, FileSendSource):
            total = getattr(src, "_total", 0)
            self.progress.setRange(0, max(total, 1))
            self.progress.setValue(0)
            self.progress.setFormat(f"发送进度 %p%  (共 {_fmt_bytes(total)})")
            self.progress.show()
        else:
            self.progress.hide()
        if src is not None and src.supports_peers:
            self._show_peers()
            self._refresh_peers()  # 打开时立即刷新, 不残留上一次的列表
        else:
            self._hide_peers()

    def _show_peers(self):
        self.peer_list.show()
        self.peer_btn_primary.show()
        self.peer_btn_all.show()

    def _hide_peers(self):
        for w in (self.peer_list, self.peer_btn_primary, self.peer_btn_all):
            w.hide()

    def _set_status(self, msg: str):
        self.status.setText(msg)

    def _set_progress(self, done: int, total: int):
        if self.progress.maximum() != max(total, 1):
            self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)

    # ---- 对端列表 -------------------------------------------------------
    def _refresh_peers(self):
        if not self.source or not self.source.supports_peers:
            return
        current = self.peer_list.currentRow()
        self.peer_list.clear()
        peers = self.source.peers()  # 已按接入序号排序
        if not peers:
            self.peer_list.addItem("(暂无对端)")
        for p in peers:
            mark = "● " if p.addr == self.source.primary_peer else "  "
            self.peer_list.addItem(f"{mark}#{p.seq}  {p.addr}    收 {_fmt_bytes(p.rx_bytes)}")
        if 0 <= current < self.peer_list.count() and self.peer_list.count() > 1:
            self.peer_list.setCurrentRow(current)

    def _set_primary(self):
        src = self.source
        if not src:
            return
        row = self.peer_list.currentRow()
        peers = src.peers()
        if not peers or row < 0 or row >= len(peers):
            toast(self.window(), "请先在列表中选择一个对端", "info")
            return
        try:
            src.set_primary_peer(peers[row].addr)
        except ValueError as e:
            toast(self.window(), str(e), "error")

    def _clear_primary(self):
        if self.source and self.source.supports_peers:
            self.source.set_primary_peer(None)

    # ---- 统计 -----------------------------------------------------------
    def update_stats(self, total: int, rate: float):
        text = f"速率 {_fmt_bytes(rate)}/s  |  共 {_fmt_bytes(total)}"
        # 串口: 额外显示带宽占用百分比 (按 起始位+数据+校验+停止位 推算理论上限)
        if isinstance(self.source, SerialSource):
            bits = 1 + self.source.bytesize + (1 if self.source.parity != "无" else 0) \
                + self.source.stopbits
            limit = self.source.baudrate / bits
            if limit > 0:
                text += f"  |  带宽 {min(rate / limit * 100, 999):.1f}%"
        self.stat_lbl.setText(text)
