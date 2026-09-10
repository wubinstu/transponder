"""各数据源类型的参数配置表单.

每个表单实现:
- build() -> DataSource  依据当前表单内容构造数据源
- fill(kv: dict)         用规格串解析出的参数预填充 (命令行带参启动GUI)
- on_opened(src)         打开成功后的回填钩子 (如自动端口显示实际值)
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QComboBox, QPushButton, QLabel,
    QLineEdit, QSpinBox, QFileDialog, QSlider, QRadioButton, QButtonGroup,
    QSizePolicy,
)

from ..core import (
    DataSource, SerialSource, scan_serial_ports,
    FileSendSource, FileRecvSource,
    TcpClientSource, TcpServerSource, UdpUnicastSource,
    MulticastSource, BroadcastSource,
    scan_local_addresses, scan_broadcast_addresses, addr_in_use,
    is_valid_multicast, udp_bind_ok,
)
from .theme import SwitchToggle, toast


def _row(label: str, *fields: QWidget, stretch_last=True) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    lab = QLabel(label)
    lab.setMinimumWidth(60)
    h.addWidget(lab)
    for i, f in enumerate(fields):
        h.addWidget(f, 1 if (stretch_last and i == len(fields) - 1) else 0)
    return w


def _pair(field: QWidget, button: QWidget) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(field, 1)
    h.addWidget(button)
    return w


def fmt_rate(bps: float) -> str:
    """限速显示: 智能单位, 保留两位小数."""
    for unit, factor in (("B", 1), ("KB", 1024), ("MB", 1024 * 1024)):
        if bps < 1024 * factor:
            return f"{bps / factor:.2f} {unit}/s"
    return f"{bps / 1024**3:.2f} GB/s"


class SerialForm(QWidget):
    TYPE = "serial"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(7)
        self.port = QComboBox()
        btn = QPushButton("刷新")
        btn.setFixedWidth(56)
        btn.clicked.connect(self.refresh_ports)
        lay.addWidget(_row("串口:", _pair(self.port, btn)))
        grid = QGridLayout()
        grid.setContentsMargins(60, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        self.baud = QComboBox(); self.baud.setEditable(True)
        self.baud.addItems(["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"])
        self.baud.setCurrentText("115200")
        self.data_bits = QComboBox(); self.data_bits.addItems(["8", "7", "6", "5"])
        self.parity = QComboBox(); self.parity.addItems(["无", "偶", "奇"])
        self.stop_bits = QComboBox(); self.stop_bits.addItems(["1", "2"])
        self.flow = QComboBox(); self.flow.addItems(["无", "RTS/CTS"])
        for col, (lab, f) in enumerate([
                ("波特率", self.baud), ("数据位", self.data_bits), ("校验", self.parity),
                ("停止位", self.stop_bits), ("流控", self.flow)]):
            grid.addWidget(QLabel(lab), 0, col * 2, Qt.AlignRight)
            grid.addWidget(f, 0, col * 2 + 1)
        lay.addLayout(grid)
        lay.addStretch(1)
        self.refresh_ports()

    def refresh_ports(self):
        self.port.clear()
        for p in scan_serial_ports():
            tag = " (占用)" if p["busy"] else ""
            self.port.addItem(f"{p['port']}{tag}  {p['desc']}", userData=p)

    def build(self) -> SerialSource:
        info = self.port.currentData()
        if not info:
            raise ValueError("请先选择串口")
        if info["busy"]:
            raise ValueError(f"串口 {info['port']} 已被占用")
        return SerialSource(
            port=info["port"], baudrate=int(self.baud.currentText()),
            bytesize=int(self.data_bits.currentText()), parity=self.parity.currentText(),
            stopbits=int(self.stop_bits.currentText()), flowctrl=self.flow.currentText(),
        )

    def fill(self, kv: dict):
        self.refresh_ports()
        for i in range(self.port.count()):
            if self.port.itemData(i) and self.port.itemData(i)["port"] == kv.get("port"):
                self.port.setCurrentIndex(i)
                break
        self.baud.setCurrentText(kv.get("baud", self.baud.currentText()))
        self.data_bits.setCurrentText(kv.get("data", "8"))
        self.parity.setCurrentText({"N": "无", "E": "偶", "O": "奇"}.get(kv.get("parity", "N"), "无"))
        self.stop_bits.setCurrentText(kv.get("stop", "1"))


class FileForm(QWidget):
    TYPE = "file"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(7)
        self.rb_send = QRadioButton("读文件 → 发送")
        self.rb_recv = QRadioButton("接收 → 写入文件")
        self.rb_send.setChecked(True)
        grp = QButtonGroup(self); grp.addButton(self.rb_send); grp.addButton(self.rb_recv)
        h = QHBoxLayout(); h.addWidget(self.rb_send); h.addWidget(self.rb_recv); h.addStretch(1)
        lay.addLayout(h)
        self.path = QLineEdit()
        btn = QPushButton("浏览")
        btn.setFixedWidth(56)
        btn.clicked.connect(self._browse)
        lay.addWidget(_row("文件:", _pair(self.path, btn)))
        # 三滑块叠加限速: B + 1024*KB + 1024*1024*MB 字节/秒
        self.unlimited = SwitchToggle("不限速")
        self.unlimited.setChecked(True)
        lay.addWidget(_row("限速:", self.unlimited))
        self.sl_b = self._slider()
        self.sl_kb = self._slider()
        self.sl_mb = self._slider()
        for slider, unit in [(self.sl_b, "B"), (self.sl_kb, "KB"), (self.sl_mb, "MB")]:
            lbl = QLabel("0")
            lbl.setMinimumWidth(64)
            slider.valueChanged.connect(lambda v, l=lbl, u=unit: l.setText(f"{v} {u}"))
            row = _row("", slider, lbl)
            row.layout().itemAt(0).widget().deleteLater()  # 去掉占位label
            lay.addWidget(row)
        self.rate_total = QLabel("限速未启用 (不限速)")
        self.rate_total.setObjectName("hint")
        lay.addWidget(self.rate_total, alignment=Qt.AlignRight)
        for s in (self.sl_b, self.sl_kb, self.sl_mb):
            s.valueChanged.connect(self._update_total)
        self.unlimited.toggled.connect(lambda on: self._update_total())
        self.append = SwitchToggle("追加写入 (不开启则覆盖)")
        lay.addWidget(self.append)
        self.rb_send.toggled.connect(self._mode_changed)
        self._mode_changed()
        lay.addStretch(1)
        # 限速变化回调 (面板连接到 FileSendSource.set_rate 实现动态限速)
        self.on_rate_change: Optional[callable] = None
        for s in (self.sl_b, self.sl_kb, self.sl_mb):
            s.valueChanged.connect(self._notify_rate)
        self.unlimited.toggled.connect(lambda _: self._notify_rate())

    @staticmethod
    def _slider() -> QSlider:
        s = QSlider(Qt.Horizontal)
        s.setRange(0, 1024)
        s.setMinimumWidth(240)  # 加长滑块, 降低鼠标滑动灵敏度
        s.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return s

    def _notify_rate(self):
        if self.on_rate_change and self.rb_send.isChecked():
            rate = self.rate_value()
            self.on_rate_change(rate or None)

    def _mode_changed(self):
        sending = self.rb_send.isChecked()
        for w in (self.unlimited, self.sl_b, self.sl_kb, self.sl_mb):
            w.setEnabled(sending)
        self.append.setEnabled(not sending)
        self._update_total()

    def _update_total(self):
        if self.rb_recv.isChecked() or self.unlimited.isChecked():
            self.rate_total.setText("限速未启用 (不限速)")
            return
        total = self.rate_value() or 1  # 全0按 1 B/s
        self.rate_total.setText(f"限速 {fmt_rate(total)}")

    def rate_value(self) -> int:
        if self.unlimited.isChecked():
            return 0
        return self.sl_b.value() + 1024 * self.sl_kb.value() + 1024 * 1024 * self.sl_mb.value()

    def rate_widgets(self) -> list[QWidget]:
        """限速相关控件 (打开数据源后仍保持可调)."""
        return [self.unlimited, self.sl_b, self.sl_kb, self.sl_mb]

    def _browse(self):
        if self.rb_send.isChecked():
            path, _ = QFileDialog.getOpenFileName(self, "选择要发送的文件")
        else:
            path, _ = QFileDialog.getSaveFileName(self, "选择要写入的文件")
        if path:
            self.path.setText(path)

    def build(self) -> DataSource:
        path = self.path.text().strip()
        if not path:
            raise ValueError("请先选择文件")
        if self.rb_send.isChecked():
            rate = self.rate_value()
            return FileSendSource(path, rate_bps=rate or None)
        return FileRecvSource(path, append=self.append.isChecked())

    def fill(self, kv: dict):
        if "path" in kv:
            self.path.setText(kv["path"])
        if kv.get("b") or kv.get("kb") or kv.get("mb"):
            self.rb_send.setChecked(True)
            self.unlimited.setChecked(False)
            self.sl_b.setValue(int(kv.get("b", "0")))
            self.sl_kb.setValue(int(kv.get("kb", "0")))
            self.sl_mb.setValue(int(kv.get("mb", "0")))
        if "append" in kv:
            self.rb_recv.setChecked(True)
            self.append.setChecked(kv["append"] == "1")


class TcpClientForm(QWidget):
    TYPE = "tcp-client"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(7)
        self.host = QLineEdit("127.0.0.1")
        self.port = QSpinBox(); self.port.setRange(1, 65535); self.port.setValue(9000)
        lay.addWidget(_row("服务器:", self.host))
        lay.addWidget(_row("端口:", self.port))
        self.local_auto = SwitchToggle("本地 IP:PORT 自动分配")
        self.local_auto.setChecked(True)
        lay.addWidget(self.local_auto)
        self.local_host = QComboBox(); self.local_host.setEditable(True)
        self.local_host.addItems(scan_local_addresses())
        self.local_port = QSpinBox(); self.local_port.setRange(0, 65535)
        self.local_port.setSpecialValueText("自动")
        lay.addWidget(_row("本地地址:", self.local_host))
        lay.addWidget(_row("本地端口:", self.local_port))
        for w in (self.local_host, self.local_port):
            w.setEnabled(False)
        self.local_auto.toggled.connect(lambda on: [
            self.local_host.setEnabled(not on), self.local_port.setEnabled(not on)])
        lay.addStretch(1)

    def build(self) -> TcpClientSource:
        return TcpClientSource(
            self.host.text().strip(), self.port.value(),
            local_host="" if self.local_auto.isChecked() else self.local_host.currentText().strip(),
            local_port=0 if self.local_auto.isChecked() else self.local_port.value(),
        )

    def on_opened(self, src: TcpClientSource) -> None:
        # 自动分配时回显实际本地端口
        if self.local_auto.isChecked() and src.local_port:
            self.local_port.setSpecialValueText("")
            self.local_port.setValue(src.local_port)
            self.local_auto.setEnabled(False)  # 已连接, 不能再切换

    def fill(self, kv: dict):
        if "host" in kv:
            self.host.setText(kv["host"])
        if "port" in kv:
            self.port.setValue(int(kv["port"]))
        if kv.get("local_host") or kv.get("local_port", "0") not in ("", "0"):
            self.local_auto.setChecked(False)
            if kv.get("local_host"):
                self.local_host.setCurrentText(kv["local_host"])
            if kv.get("local_port"):
                self.local_port.setValue(int(kv["local_port"]))


class TcpServerForm(QWidget):
    TYPE = "tcp-server"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(7)
        self.host = QComboBox(); self.host.setEditable(True)
        self.host.addItems(scan_local_addresses())
        self.port = QSpinBox(); self.port.setRange(1, 65535); self.port.setValue(9000)
        self.check = QPushButton("检测占用")
        self.check.setFixedWidth(80)
        self.check.clicked.connect(self._check)
        lay.addWidget(_row("绑定地址:", _pair(self.host, self.check)))
        lay.addWidget(_row("绑定端口:", self.port))
        self.backlog = QSpinBox(); self.backlog.setRange(0, 128)
        self.backlog.setSpecialValueText("默认")
        lay.addWidget(_row("监听队列:", self.backlog))
        hint = QLabel("不选主要对端时: 发送给全部客户端并接收全部; 主要对端断开自动恢复全部模式")
        hint.setObjectName("hint"); hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)

    def _check(self):
        busy = addr_in_use(self.host.currentText().strip(), self.port.value())
        msg = (f"{self.host.currentText()}:{self.port.value()} 已被占用"
               if busy else f"{self.host.currentText()}:{self.port.value()} 可以使用")
        toast(self.window(), msg, "error" if busy else "success")

    def build(self) -> TcpServerSource:
        return TcpServerSource(self.host.currentText().strip(), self.port.value(),
                               backlog=self.backlog.value())

    def fill(self, kv: dict):
        if "host" in kv:
            self.host.setCurrentText(kv["host"])
        if "port" in kv:
            self.port.setValue(int(kv["port"]))
        if "backlog" in kv:
            self.backlog.setValue(int(kv["backlog"]))


class UdpForm(QWidget):
    TYPE = "udp"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(7)
        self.bind_host = QComboBox(); self.bind_host.setEditable(True)
        self.bind_host.addItems(scan_local_addresses())
        self.bind_port = QSpinBox(); self.bind_port.setRange(0, 65535)
        self.bind_port.setSpecialValueText("自动分配")
        self.bind_port.setValue(0)
        self.check = QPushButton("检测占用")
        self.check.setFixedWidth(80)
        self.check.clicked.connect(self._check)
        lay.addWidget(_row("本地地址:", _pair(self.bind_host, self.check)))
        lay.addWidget(_row("本地端口:", self.bind_port))
        self.peer_host = QLineEdit()
        self.peer_host.setPlaceholderText("留空 = 收到第一帧数据后自动锁定对端")
        self.peer_port = QSpinBox(); self.peer_port.setRange(0, 65535)
        self.peer_port.setSpecialValueText("自动")
        lay.addWidget(_row("对端地址:", self.peer_host))
        lay.addWidget(_row("对端端口:", self.peer_port))
        hint = QLabel("指定对端后仅与该对端收发; 不指定则锁定第一个发来数据的地址")
        hint.setObjectName("hint"); hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)

    def _check(self):
        host = self.bind_host.currentText().strip()
        port = self.bind_port.value()
        if port == 0:
            ok = udp_bind_ok(host, 0)
            msg = f"地址 {host} 可用 (端口自动分配)" if ok else f"地址 {host} 不可用"
        else:
            ok = udp_bind_ok(host, port)
            msg = f"{host}:{port} 已被占用" if not ok else f"{host}:{port} 可以使用"
        toast(self.window(), msg, "error" if not ok else "success")

    def build(self) -> UdpUnicastSource:
        peer_host = self.peer_host.text().strip()
        peer_port = self.peer_port.value()
        if peer_host and not peer_port:
            raise ValueError("已填写对端地址, 请同时填写对端端口")
        return UdpUnicastSource(
            bind_host=self.bind_host.currentText().strip(),
            bind_port=self.bind_port.value(),
            peer_host=peer_host, peer_port=peer_port,
        )

    def on_opened(self, src: UdpUnicastSource) -> None:
        if src.local_port:  # 自动分配时回显实际端口
            self.bind_port.setSpecialValueText("")
            self.bind_port.setValue(src.local_port)

    def fill(self, kv: dict):
        if "host" in kv:
            self.bind_host.setCurrentText(kv["host"])
        if kv.get("port"):
            self.bind_port.setValue(int(kv["port"]))
        if kv.get("peer"):
            host, _, port = kv["peer"].rpartition(":")
            self.peer_host.setText(host)
            if port.isdigit():
                self.peer_port.setValue(int(port))


class MulticastForm(QWidget):
    TYPE = "multicast"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(7)
        self.group = QLineEdit("239.1.1.1")
        self.check = QPushButton("检测")
        self.check.setFixedWidth(56)
        self.check.clicked.connect(self._check)
        lay.addWidget(_row("组播地址:", _pair(self.group, self.check)))
        hint = QLabel("有效组播地址范围: 224.0.0.0/4 (224.0.0.0 ~ 239.255.255.255)")
        hint.setObjectName("hint")
        lay.addWidget(hint, alignment=Qt.AlignRight)
        self.port = QSpinBox(); self.port.setRange(1, 65535); self.port.setValue(5000)
        self.ttl = QSpinBox(); self.ttl.setRange(1, 255); self.ttl.setValue(1)
        lay.addWidget(_row("端口:", self.port, QLabel("TTL:"), self.ttl))
        self.local_ip = QComboBox(); self.local_ip.setEditable(True)
        self.local_ip.addItems(["0.0.0.0"] + [ip for ip in scan_local_addresses()
                                              if ip != "0.0.0.0"])
        lay.addWidget(_row("本地接口:", self.local_ip))
        hint2 = QLabel("本地接口 0.0.0.0 = 系统自动选择网卡; 指定后仅在该网卡收发组播")
        hint2.setObjectName("hint"); hint2.setWordWrap(True)
        lay.addWidget(hint2)
        hint3 = QLabel("已自动过滤自己发出的组播回环 (本机其他程序不受影响)")
        hint3.setObjectName("hint")
        lay.addWidget(hint3)
        lay.addStretch(1)

    def _check(self):
        ok = is_valid_multicast(self.group.text())
        msg = (f"{self.group.text()} 是有效组播地址"
               if ok else f"{self.group.text()} 不是有效组播地址 (范围 224.0.0.0/4)")
        toast(self.window(), msg, "success" if ok else "error")

    def build(self) -> MulticastSource:
        group = self.group.text().strip()
        if not is_valid_multicast(group):
            raise ValueError(f"无效的组播地址: {group} (范围 224.0.0.0/4)")
        return MulticastSource(group, self.port.value(),
                               local_ip=self.local_ip.currentText().strip(),
                               ttl=self.ttl.value())

    def fill(self, kv: dict):
        if "group" in kv:
            self.group.setText(kv["group"])
        if "port" in kv:
            self.port.setValue(int(kv["port"]))
        if "ttl" in kv:
            self.ttl.setValue(int(kv["ttl"]))
        if kv.get("local_host"):
            self.local_ip.setCurrentText(kv["local_host"])


class BroadcastForm(QWidget):
    TYPE = "broadcast"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(7)
        self.addr = QComboBox(); self.addr.setEditable(True)
        self.addr.addItems(scan_broadcast_addresses())
        self.port = QSpinBox(); self.port.setRange(1, 65535); self.port.setValue(5000)
        self.local_port = QSpinBox(); self.local_port.setRange(0, 65535)
        self.local_port.setSpecialValueText("自动分配")
        lay.addWidget(_row("广播地址:", self.addr))
        lay.addWidget(_row("广播端口:", self.port))
        lay.addWidget(_row("本地端口:", self.local_port))
        hint = QLabel("广播地址按网卡自动填充 (如 192.168.10.255), 也可手动输入; 已过滤自己的回环")
        hint.setObjectName("hint"); hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)

    def build(self) -> BroadcastSource:
        return BroadcastSource(addr=self.addr.currentText().strip(), port=self.port.value(),
                               local_port=self.local_port.value())

    def on_opened(self, src: BroadcastSource) -> None:
        if src.local_port:
            self.local_port.setSpecialValueText("")
            self.local_port.setValue(src.local_port)

    def fill(self, kv: dict):
        if "addr" in kv:
            self.addr.setCurrentText(kv["addr"])
        if "port" in kv:
            self.port.setValue(int(kv["port"]))
        if kv.get("local_port"):
            self.local_port.setValue(int(kv["local_port"]))


SOURCE_TYPES = [
    ("串口", SerialForm),
    ("文件", FileForm),
    ("TCP客户端", TcpClientForm),
    ("TCP服务端", TcpServerForm),
    ("UDP单播", UdpForm),
    ("组播", MulticastForm),
    ("广播", BroadcastForm),
]
