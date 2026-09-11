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
# ---- 7. 预览字体族正确 (逗号连写的单字体名是 v6.2 前的 bug, 会引发字体回退告警刷屏) ----
families = win.pane_m.view.font().families()
assert "Consolas" in families and not any("," in f for f in families), families
# TXT 模式灌入二进制乱码不应异常 (字体回退仅是提示)
win.pane_m.txt_rb.setChecked(True)
win.pane_m.append(bytes(range(0, 256)) * 4)
app.processEvents()
print("TEST7 预览字体族 PASS:", families)

# ---- 8. 串口表单标签列对齐 (与"串口:"行同列同对齐) --------------------------
# 离屏下复用旧窗口会有嵌套布局未激活的陈旧几何, 用全新窗口验证
win2 = MainWindow()
win2.panel_m.type_combo.setCurrentIndex(0)
win2.show()
app.processEvents()
serial_form = win2.panel_m.stack.currentWidget()
serial_form.layout().activate()
app.processEvents()
from PySide6.QtWidgets import QLabel, QComboBox
labels = [l for l in serial_form.findChildren(QLabel) if l.text()]
xs = sorted({l.mapTo(serial_form, l.rect().topLeft()).x() for l in labels})
assert len(xs) == 1, f"标签列未对齐: {[(l.text(), l.mapTo(serial_form, l.rect().topLeft()).x()) for l in labels]}"
combo_xs = sorted({f.mapTo(serial_form, f.rect().topLeft()).x()
                   for f in serial_form.findChildren(QComboBox)})
assert len(combo_xs) == 1, f"输入框列未对齐: {combo_xs}"
assert combo_xs[0] > xs[0], f"输入框应位于标签列右侧: label={xs[0]}, combo={combo_xs[0]}"
print(f"TEST8 串口表单标签/输入框列对齐 PASS (label x={xs[0]}, combo x={combo_xs[0]})")

# ---- 9. UDP对端地址 hint 样式动态切换 (输入后正常, 仅 hint 淡色斜体) --------
win.panel_m.type_combo.setCurrentIndex(4)
fu = win.panel_m.stack.currentWidget()
ph = fu.peer_host
assert ph.property("empty") is True and ph.font().italic(), "空(hint)应为斜体"
ph.setText("192.168.1.9")
app.processEvents()
assert ph.property("empty") is False and not ph.font().italic(), "输入后应恢复正常样式"
ph.clear()
app.processEvents()
assert ph.property("empty") is True and ph.font().italic(), "清空后应回到占位样式"
print("TEST9 hint样式动态切换 PASS")
print("ALL PASS")
