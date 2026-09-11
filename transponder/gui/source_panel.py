"""单侧数据源面板: 类型/参数/打开关闭/对端列表/文件进度."""
from __future__ import annotations
from typing import Optional
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QHBoxLayout, QComboBox, QStackedWidget, QPushButton, QLabel, QListWidget, QProgressBar, QAbstractItemView, QWidget
from ..core import DataSource, FileSendSource
from .forms import SOURCE_TYPES
from .theme import toast

def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"

def _repolish(w: QWidget) -> None:
    w.style().unpolish(w); w.style().polish(w)

class PanelSignals(QObject):
    state = Signal(str)
    peers_changed = Signal()
    progress = Signal(int, int)

class SourcePanel(QGroupBox):
    def __init__(self, title: str):
        super().__init__(title)
        self.source: Optional[DataSource] = None
        self.on_source_opened = None
        self.sig = PanelSignals()
        self.sig.state.connect(self._set_status)
        self.sig.peers_changed.connect(self._refresh_peers)
        self.sig.progress.connect(self._set_progress)
        lay = QVBoxLayout(self); lay.setSpacing(8)
        top = QHBoxLayout()
        self.type_combo = QComboBox()
        for name, _ in SOURCE_TYPES: self.type_combo.addItem(name)
        self.open_btn = QPushButton("打开"); self.open_btn.setObjectName("btn_open"); self.open_btn.setFixedWidth(72)
        self.open_btn.clicked.connect(self._toggle)
        top.addWidget(self.type_combo, 1); top.addWidget(self.open_btn); lay.addLayout(top)
        self.stack = QStackedWidget()
        for _, cls in SOURCE_TYPES: self.stack.addWidget(cls())
        self.type_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        lay.addWidget(self.stack)
        # 对端列表紧跟表单下方, 向上对齐
        self.peer_list = QListWidget(); self.peer_list.setSelectionMode(QAbstractItemView.SingleSelection); self.peer_list.setMaximumHeight(88)
        self.peer_btn_primary = QPushButton("设为主要对端"); self.peer_btn_all = QPushButton("全部")
        self.peer_btn_primary.setFixedHeight(26); self.peer_btn_all.setFixedHeight(26)
        self.peer_btn_primary.clicked.connect(self._set_primary); self.peer_btn_all.clicked.connect(self._clear_primary)
        pb = QHBoxLayout(); pb.addWidget(self.peer_btn_primary, 1); pb.addWidget(self.peer_btn_all, 1)
        self.peer_box = QVBoxLayout(); self.peer_box.addWidget(self.peer_list); self.peer_box.addLayout(pb); lay.addLayout(self.peer_box); self._hide_peers()
        # 打开状态由按钮表达, 不再额外占用状态行
        self.status = QLabel(); self.status.setObjectName("hint"); self.status.hide(); lay.addWidget(self.status)
        self.progress = QProgressBar(); self.progress.hide(); lay.addWidget(self.progress)

    def current_form(self): return self.stack.currentWidget()

    def _toggle(self):
        if self.source:
            self.close_source(); return
        try:
            src = self.current_form().build(); src.open()
        except Exception as e:
            toast(self.window(), f"打开失败: {e}", "error"); return
        self.source = src
        src.set_callbacks(on_state=lambda msg: self.sig.state.emit(msg), on_peers=lambda: self.sig.peers_changed.emit(), on_progress=lambda d,t: self.sig.progress.emit(d,t))
        self.open_btn.setText("关闭"); self.open_btn.setObjectName("btn_close"); _repolish(self.open_btn); self.type_combo.setEnabled(False)
        self._apply_form_lock(True)
        if isinstance(src, FileSendSource):
            form = self.current_form()
            if hasattr(form, "on_rate_change"): form.on_rate_change = src.set_rate
        hook = getattr(self.current_form(), "on_opened", None)
        if hook:
            try: hook(src)
            except Exception: pass
        self._update_dynamic_widgets()
        if self.on_source_opened:
            self.on_source_opened(src)

    def close_source(self):
        if self.source: self.source.close()
        self.source = None; self.open_btn.setText("打开"); self.open_btn.setObjectName("btn_open"); _repolish(self.open_btn); self.type_combo.setEnabled(True)
        self._apply_form_lock(False)
        for i in range(self.stack.count()):
            sync = getattr(self.stack.widget(i), "sync_states_after_close", None) or getattr(self.stack.widget(i), "sync_states", None)
            if sync: sync()
        self._hide_peers(); self.peer_list.clear(); self.progress.hide()

    def set_editable(self, on: bool):
        self.open_btn.setEnabled(on); self.type_combo.setEnabled(on and self.source is None)
        if self.source is not None: self._apply_form_lock(True)
        else: self._apply_form_lock(not on)

    def _apply_form_lock(self, locked: bool):
        keep = self.current_form().rate_widgets() if locked and isinstance(self.source, FileSendSource) else []
        self.stack.setEnabled(True)
        def exempt(w): return any(w is k or w.isAncestorOf(k) or k.isAncestorOf(w) for k in keep)
        for w in self.stack.findChildren(QWidget):
            if not locked or not exempt(w): w.setEnabled(not locked)
        if locked:
            refresh = getattr(self.current_form(), "refresh_widget_states", None)
            if refresh: refresh()
        else:
            for i in range(self.stack.count()):
                sync = getattr(self.stack.widget(i), "sync_states", None)
                if sync: sync()

    def _update_dynamic_widgets(self):
        src = self.source
        if isinstance(src, FileSendSource):
            total = getattr(src, "_total", 0); self.progress.setRange(0, max(total, 1)); self.progress.setValue(0); self.progress.setFormat(f"发送进度 %p%  (共 {_fmt_bytes(total)})"); self.progress.show()
        else: self.progress.hide()
        if src and src.supports_peers: self._show_peers(); self._refresh_peers()
        else: self._hide_peers()

    def _show_peers(self):
        self.peer_list.show(); self.peer_btn_primary.show(); self.peer_btn_all.show()
    def _hide_peers(self):
        self.peer_list.hide(); self.peer_btn_primary.hide(); self.peer_btn_all.hide()
    def _set_status(self, msg: str): self.status.setText(msg)
    def _set_progress(self, done: int, total: int):
        self.progress.setRange(0, max(total, 1)); self.progress.setValue(done)

    def _refresh_peers(self):
        if not self.source or not self.source.supports_peers: return
        current = self.peer_list.currentRow(); self.peer_list.clear(); peers = self.source.peers()
        if not peers: self.peer_list.addItem("(暂无对端)")
        for p in peers:
            mark = "● " if p.addr == self.source.primary_peer else "  "; self.peer_list.addItem(f"{mark}#{p.seq}  {p.addr}    收 {_fmt_bytes(p.rx_bytes)}")
        if 0 <= current < self.peer_list.count() and self.peer_list.count() > 1: self.peer_list.setCurrentRow(current)
    def _set_primary(self):
        if not self.source: return
        peers = self.source.peers(); row = self.peer_list.currentRow()
        if not peers or row < 0 or row >= len(peers): toast(self.window(), "请先在列表中选择一个对端", "info"); return
        try: self.source.set_primary_peer(peers[row].addr)
        except ValueError as e: toast(self.window(), str(e), "error")
    def _clear_primary(self):
        if self.source and self.source.supports_peers: self.source.set_primary_peer(None)
