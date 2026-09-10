"""新功能核心测试: UDP单播对端过滤 / 组播回环禁用 / 广播 / TXT时间戳落地 / 文件进度 / 对端扇出"""
import os, socket, sys, tempfile, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from transponder.core import (
    UdpUnicastSource, MulticastSource, BroadcastSource,
    LogSession, FileSendSource, TcpServerSource, is_valid_multicast,
    scan_local_addresses, scan_broadcast_addresses,
)

PORT = 19340


def drain(src, seconds=1.0, action=None):
    """注册 on_data 回调 -> 执行 action -> 收集 seconds 内的数据."""
    out = []
    src.set_callbacks(on_data=out.append)
    if action:
        action()
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        time.sleep(0.05)
    return out


# ---- UDP单播: 指定对端后仅接收该对端 ------------------------------------
src = UdpUnicastSource(bind_host="127.0.0.1", bind_port=PORT,
                       peer_host="127.0.0.1", peer_port=19341)
src.open(); src.start()
peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
peer.bind(("127.0.0.1", 19341))  # 对端端口须与配置一致 (过滤按 ip:port 匹配)
other = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
other.bind(("127.0.0.1", 0))
time.sleep(0.2)
got = drain(src, 0.8, action=lambda: [
    peer.sendto(b"FROM_PEER", ("127.0.0.1", PORT)),
    other.sendto(b"FROM_OTHER", ("127.0.0.1", PORT)),
])
assert got == [b"FROM_PEER"], f"对端过滤失败: {got}"
# 发送给指定对端
peer.settimeout(2)
src.send(b"TO_PEER")
assert peer.recv(100) == b"TO_PEER"
src.close()
print("TEST UDP单播对端过滤 PASS")

# ---- 组播: 回环禁用 (自己发的不回到自己) + 地址校验 ----------------------
assert is_valid_multicast("239.1.1.1") and not is_valid_multicast("192.168.1.1")
mc = MulticastSource("239.8.8.8", PORT, ttl=1)
mc.open(); mc.start()
# IP_MULTICAST_LOOP=0: 自己发出的组播不会回到本机任何 socket (Windows 上为整机行为)
got = drain(mc, 0.8, action=lambda: mc.send(b"LOOP_TEST"))
assert b"LOOP_TEST" not in b"".join(got), f"组播回环未禁用: {got}"
mc.close()
print("TEST 组播回环禁用 PASS")

# ---- 广播: 发送至指定广播地址, 接收方绑定同端口可收到 --------------------
bc = BroadcastSource(addr="127.255.255.255", port=PORT)
bc.open(); bc.start()
rcv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rcv.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
rcv.bind(("0.0.0.0", PORT))
rcv.settimeout(2)
bc.send(b"BCAST")
data, addr = rcv.recvfrom(100)
assert data == b"BCAST"
bc.close(); rcv.close()
print("TEST 广播 PASS")

# ---- 落地记录: TXT 时间戳间隔 ------------------------------------------
tmp = tempfile.mkdtemp()
s = LogSession(tmp)
w = s.writer("M", "txt", ts_interval_ms=200)
w.log(b"hello ")
time.sleep(0.3)
w.log(b"world")
w.close(); s.close()
import re
dirs = os.listdir(tmp)
assert len(dirs) == 1 and re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", dirs[0])
content = open(os.path.join(tmp, dirs[0], "M.txt"), encoding="utf-8").read()
assert "hello " in content and "world" in content
assert re.search(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\]", content), "应有时间戳行"
assert content.count("[") >= 2, "间隔超过200ms应输出至少两次时间戳"
print("TEST TXT时间戳落地 PASS")

# ---- 文件进度回调 --------------------------------------------------------
f2 = os.path.join(tmp, "prog.bin")
open(f2, "wb").write(b"A" * 10000)
fs = FileSendSource(f2, rate_bps=50000)
prog = []
fs.set_callbacks(on_progress=lambda d, t: prog.append((d, t)))
fs.open()
chunks = []
fs.set_callbacks(on_data=chunks.append)
while True:
    try:
        d = fs._read_once()
        if d:
            chunks.append(d)
    except Exception:
        break
assert prog and prog[-1] == (10000, 10000), f"进度回调异常: {prog[-1] if prog else None}"
assert sum(len(c) for c in chunks) == 10000
fs.close()
print("TEST 文件进度 PASS")

# ---- TCP服务端扇出: 无主要对端时发给全部 --------------------------------
srv = TcpServerSource("127.0.0.1", PORT)
srv.open()
time.sleep(0.2)
ca = socket.create_connection(("127.0.0.1", PORT), timeout=2)
cb = socket.create_connection(("127.0.0.1", PORT), timeout=2)
time.sleep(0.5)
assert len(srv.peers()) == 2, f"对端列表: {len(srv.peers())}"
srv.send(b"FANOUT")  # 未选主要对端 -> 全部客户端收到
ca.settimeout(2); cb.settimeout(2)
assert ca.recv(100) == b"FANOUT" and cb.recv(100) == b"FANOUT", "扇出失败"
# 选主要对端 -> 只有它收到
key = srv.peers()[0].addr
srv.set_primary_peer(key)
srv.send(b"MAIN_ONLY")
assert ca.recv(100) == b"MAIN_ONLY" or cb.recv(100) == b"MAIN_ONLY"
# 检查另一个确实没收到 (再发一条, 主要对端会收到, 另一个超时)
import threading
recv_other = []
def other_reader(sock):
    sock.settimeout(0.8)
    try:
        recv_other.append(sock.recv(100))
    except socket.timeout:
        pass
main_sock = ca if f"{ca.getsockname()[0]}:{ca.getsockname()[1]}" == key else cb
other_sock = cb if main_sock is ca else ca
threading.Thread(target=other_reader, args=(other_sock,), daemon=True).start()
srv.send(b"SECOND")
main_sock.settimeout(2)
assert main_sock.recv(100) == b"SECOND"
time.sleep(1.0)
assert recv_other == [], f"非主要对端收到了数据: {recv_other}"
ca.close(); cb.close(); srv.close()
print("TEST TCP服务端扇出/主要对端 PASS")

# ---- 地址扫描 ------------------------------------------------------------
ips = scan_local_addresses()
assert "0.0.0.0" in ips and "127.0.0.1" in ips
bcasts = scan_broadcast_addresses()
assert "255.255.255.255" in bcasts
print("TEST 地址扫描 PASS:", ips, bcasts)

print("ALL PASS")
