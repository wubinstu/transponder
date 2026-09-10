"""UDP单播 + 虚拟串口对 转发测试 (v2)"""
import socket, subprocess, sys, time, threading

PORT = 19310
ECHO = 19311


def run_tp(m, w, duration=6):
    return subprocess.Popen(
        [sys.executable, "-m", "transponder", "--nogui", "-m", m, "-w", w,
         "--duration", str(duration)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def udp_echo():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", ECHO))
    while True:
        d, a = s.recvfrom(65536)
        s.sendto(d, a)


threading.Thread(target=udp_echo, daemon=True).start()

# UDP单播(未指定对端, 本地手动端口) <-> UDP单播(指定对端=echo)
p = run_tp(f"udp:host=127.0.0.1,port={PORT}",
           f"udp:host=127.0.0.1,peer=127.0.0.1:{ECHO}")
time.sleep(1.0)

c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
c.settimeout(3)
c.sendto(b"udp-ping-", ("127.0.0.1", PORT))  # 第一帧锁定对端
time.sleep(0.5)
c.sendto(b"x" * 2000, ("127.0.0.1", PORT))
got = b""
try:
    while len(got) < 2008:
        d, _ = c.recvfrom(65536)
        got += d
except socket.timeout:
    pass
print("UDP 收到", len(got), "bytes")
assert b"udp-ping-" in got and b"x" * 2000 in got, "UDP 转发数据不完整"
print("TEST-UDP PASS")
out = p.communicate(timeout=15)[0]
print(out)
assert "结束" in out

# 串口: 虚拟串口对 COM1<->COM2 (需两端都打开, 否则数据可能被驱动丢弃)
import serial
try:
    s1 = serial.Serial("COM1"); s1.close()
except Exception as e:
    print("虚拟串口不可用, 跳过串口测试:", e)
    sys.exit(0)

p = run_tp("serial:port=COM1,baud=115200", f"tcp-server:host=127.0.0.1,port={PORT}")
time.sleep(1.2)
s2 = serial.Serial("COM2", timeout=3)
c2 = socket.create_connection(("127.0.0.1", PORT), timeout=3)
c2.settimeout(3)
c2.sendall(b"serial-hello")
data = s2.read(12)
assert data == b"serial-hello", f"串口转发数据不一致: {data}"
print("TEST-SERIAL PASS")
s2.close(); c2.close()
out = p.communicate(timeout=15)[0]
print(out)
print("ALL PASS")
