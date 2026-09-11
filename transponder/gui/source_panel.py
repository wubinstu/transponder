"""单侧数据源面板: 类型选择/参数表单/打开关闭(绿红状态)/对端列表/文件进度.

状态消息不占面板行 (意见4-4), 通过 on_event 钩子投递到主窗口事件日志;
转发开始后 Bridge 会接管数据源的 on_state 回调, 同样汇入事件日志.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QComboBox, QStackedWidget, QPushButton,
    QLabel, QListWidget, QProgressBar, QAbstractItemView, QWidget,
)

from ..core import DataSource, FileSendSource
from .forms import SOURCE_TYPES
from .theme import toast
from .util import fmt_bytes


def _repolish(w: QWidget) -> None:
    """objectName 变化后强制重算 QSS (Qt 不会自动刷新)."""
    w.style().unpolish(w)
    w.style().polish(w)


class PanelSignals(QObject):
    """数据源工作线程回调 -> UI 线程信号的桥接."""

    peers_changed = Signal()
    progress = Signal(int, int)


class SourcePanel(QGroupBox):
    """一侧数据源面板 (M 或 W)."""

    def __init__(self, title: str):
        super().__init__(title)
        self.source: Optional[DataSource] = None
        # 主窗口注入: 打开成功/状态消息回调 (线程安全, 会被工作线程调用)
        self.on_event: Optional[Callable[[str], None]] = None
        self.on_source_opened: Optional[Callable[[DataSource], None]] = None
        self.sig = PanelSignals()
        self.sig.peers_changed.connect(self._refresh_peers)
        self.sig.progress.connect(self._set_progress)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        top = QHBoxLayout()
        self.type_combo = QComboBox()
        for name, _ in SOURCE_TYPES:
            self.type_combo.addItem(name)
        self.open_btn = QPushButton("打开")
        self.open_btn.setObjectName("btn_open")
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

        # 对端列表紧跟表单下方 (向上对齐, 不挤压下方进度/统计)
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
        peer_box = QVBoxLayout()
        peer_box.addWidget(self.peer_list)
        peer_box.addLayout(pb)
        lay.addLayout(peer_box)
        self._hide_peers()

        # 文件发送进度条 (仅文件读源打开后显示)
        self.progress = QProgressBar()
        self.progress.hide()
        lay.addWidget(self.progress)

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
        # 面板关心的回调: 状态投事件日志, 对端/进度走信号
        src.set_callbacks(
            on_state=self._emit_event,
            on_error=self._emit_event,
            on_peers=lambda: self.sig.peers_changed.emit(),
            on_progress=lambda d, t: self.sig.progress.emit(d, t),
        )
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
        # 打开成功钩子 (自动端口回显等) + 打开事件
        hook = getattr(self.current_form(), "on_opened", None)
        if hook:
            try:
                hook(src)
            except Exception:
                pass
        self._update_dynamic_widgets()
        if self.on_source_opened:
            self.on_source_opened(src)

    def _emit_event(self, msg: str) -> None:
        if self.on_event:
            self.on_event(msg)

    def close_source(self):
        if self.source:
            self.source.close()
            self.source = None
        self.open_btn.setText("打开")
        self.open_btn.setObjectName("btn_open")
        _repolish(self.open_btn)
        self.type_combo.setEnabled(True)
        self._apply_form_lock(False)
        # 各表单恢复"关闭后"状态 (如自动端口回显值复位, 避免重开误绑固定端口)
        for i in range(self.stack.count()):
            form = self.stack.widget(i)
            sync = getattr(form, "sync_states_after_close", None) \
                or getattr(form, "sync_states", None)
            if sync:
                sync()
        self._hide_peers()
        self.peer_list.clear()
        self.progress.hide()

    def set_editable(self, on: bool):
        """转发开始后禁用打开/类型切换, 停止后恢复 (文件限速滑块始终可调)."""
        self.open_btn.setEnabled(on)
        self.type_combo.setEnabled(on and self.source is None)
        if self.source is not None:
            self._apply_form_lock(True)
        else:
            self._apply_form_lock(not on)

    # ---- 表单锁定 -------------------------------------------------------
    def _apply_form_lock(self, locked: bool) -> None:
        """锁定/解锁参数表单. 逐控件设置而非禁用父容器(否则会阻断子控件);
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
        # 锁定后重新应用表单内部联动 (radio/开关互灰等)
        if locked:
            refresh = getattr(self.current_form(), "refresh_widget_states", None)
            if refresh:
                refresh()
        else:
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
            self.progress.setFormat(f"发送进度 %p%  (共 {fmt_bytes(total)})")
            self.progress.show()
        else:
            self.progress.hide()
        if src is not None and src.supports_peers:
            self._show_peers()
            self._refresh_peers()  # 打开时立即刷新, 不残留上一次内容
        else:
            self._hide_peers()

    def _show_peers(self):
        self.peer_list.show()
        self.peer_btn_primary.show()
        self.peer_btn_all.show()

    def _hide_peers(self):
        self.peer_list.hide()
        self.peer_btn_primary.hide()
        self.peer_btn_all.hide()

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
            self.peer_list.addItem(f"{mark}#{p.seq}  {p.addr}    收 {fmt_bytes(p.rx_bytes)}")
        if 0 <= current < self.peer_list.count() and self.peer_list.count() > 1:
            self.peer_list.setCurrentRow(current)

    def _set_primary(self):
        if not self.source:
            return
        peers = self.source.peers()
        row = self.peer_list.currentRow()
        if not peers or not (0 <= row < len(peers)):
            toast(self.window(), "请先在列表中选择一个对端", "info")
            return
        try:
            self.source.set_primary_peer(peers[row].addr)
        except ValueError as e:
            toast(self.window(), str(e), "error")

    def _clear_primary(self):
        if self.source and self.source.supports_peers:
            self.source.set_primary_peer(None)
