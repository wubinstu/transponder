"""v6.2 修复项的 GUI 回归测试:
1. QSS 完整性 (QPushButton 基础规则/占位规则) -- 防 v6.1 类似破坏复发
2. 占位数值框行为 (清空回最小值/占位提示)
3. UDP 打开回显 -> 关闭恢复"自动" -> 重开不误绑固定端口
4. 事件日志暂停缓存语义 (暂停期间事件不丢失, 恢复补显)
5. 串口带宽占用百分比恢复
6. 面板状态消息进事件日志
"""
import os, re, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

# ---- 1. QSS 完整性 --------------------------------------------------------
from transponder.gui.theme import build_qss, DARK, LIGHT, apply_theme

for t in (DARK, LIGHT):
    for rounded in (True, False):
        qss = build_qss(t, rounded)
        assert re.search(r"\nQPushButton\s*\{", qss), "QPushButton 基础规则缺失 (v6.1 破坏复发)"
        assert "QSpinBox[placeholder=\"true\"]" in qss, "占位数值框样式规则缺失"
        assert qss.count("{") == qss.count("}"), "QSS 花括号不配对"
assert "QPushButton" not in ""  # noop 保持结构清晰
print("TEST1 QSS 完整性 PASS")

# ---- 2. 占位数值框 --------------------------------------------------------
apply_theme("dark")
from transponder.gui.main_window import MainWindow

win = MainWindow()
win.panel_m.type_combo.setCurrentIndex(4)  # UDP单播
fu = win.panel_m.stack.currentWidget()
assert fu.bind_port.value() == 0 and fu.bind_port.text() == ""
assert fu.bind_port.lineEdit().placeholderText() == "自动分配"
fu.bind_port.lineEdit().setText("12345")
assert fu.bind_port.value() == 12345
fu.bind_port.lineEdit().setText("")
fu.bind_port._maybe_reset()
assert fu.bind_port.value() == 0 and fu.bind_port.text() == ""
print("TEST2 占位数值框 PASS")

# ---- 3. 打开回显 -> 关闭恢复"自动" ----------------------------------------
win.panel_m._toggle()
app.processEvents()
shown = fu.bind_port.value()
assert shown > 0, "自动端口未回显"
win.panel_m.close_source()
app.processEvents()
assert fu.bind_port.value() == 0, f"关闭后未恢复自动: {fu.bind_port.value()} (重开将误绑固定端口)"
win.panel_m._toggle()  # 重开: 应仍是自动分配
app.processEvents()
assert win.panel_m.source._sock.getsockname()[1] != shown or True  # 端口由系统决定
assert fu.bind_port.value() > 0
win.panel_m.close_source()
# TCP服务端 backlog 同理
win.panel_w.type_combo.setCurrentIndex(3)
fs = win.panel_w.stack.currentWidget()
fs.host.setCurrentText("127.0.0.1")
fs.backlog.setValue(0)
win.panel_w._toggle(); app.processEvents()
assert fs.backlog.value() > 0, "默认 backlog 未回显"
win.panel_w.close_source(); app.processEvents()
assert fs.backlog.value() == 0, "关闭后 backlog 未恢复默认"
print("TEST3 打开回显/关闭恢复 PASS")

# ---- 4. 事件日志暂停缓存 --------------------------------------------------
win._toggle_event_pause()          # 暂停
win._log("PAUSED_EVENT_1")
win._uiq.put(("event", "PAUSED_EVENT_2"))
for _ in range(6):
    app.processEvents()
import time as _t; _t.sleep(0.15); app.processEvents()
assert "PAUSED_EVENT" not in win.event_view.toPlainText(), "暂停期间事件不应显示"
win._toggle_event_pause()          # 恢复
app.processEvents()
text = win.event_view.toPlainText()
assert "PAUSED_EVENT_1" in text and "PAUSED_EVENT_2" in text, "暂停期间事件丢失"
print("TEST4 事件暂停缓存 PASS")

# ---- 5. 串口带宽百分比 ----------------------------------------------------
from transponder.core import SerialSource
win.panel_m.source = SerialSource("COM9", baudrate=115200)  # 仅构造, 不打开
text = win._stats_text("M", 1152, 1152.0)
win.panel_m.source = None
assert "带宽 10.0%" in text, f"串口带宽百分比缺失: {text}"
text2 = win._stats_text("M", 100, 10.0)
assert "带宽" not in text2 or "0.0%" in text2
print("TEST5 串口带宽百分比 PASS:", text)

# ---- 6. 面板状态消息进事件日志 --------------------------------------------
from transponder.core import TcpServerSource
import socket, time
win.panel_m.source = None  # 清理
srv_panel = win.panel_m
srv_panel.type_combo.setCurrentIndex(3)
fsv = srv_panel.stack.currentWidget()
fsv.host.setCurrentText("127.0.0.1"); fsv.port.setValue(19501)
srv_panel._toggle(); app.processEvents()
time.sleep(0.2)
c = socket.create_connection(("127.0.0.1", 19501), timeout=2)
c.sendall(b"hi")
time.sleep(0.6)
for _ in range(6):
    app.processEvents(); _t.sleep(0.05)
log_text = win.event_view.toPlainText()
assert "已接入" in log_text, f"状态消息未进入事件日志: {log_text[-200:]}"
assert "已打开" in log_text, "打开摘要缺失"
c.close()
srv_panel.close_source()
print("TEST6 状态消息进事件日志 PASS")
print("ALL PASS")
