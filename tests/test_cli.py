"""命令行版本全面测试: 正常用例 + 异常用例 (subprocess 端到端).

运行: python tests/test_cli.py
覆盖: --help/--version/查询命令/双向转发(各数据源)/落地记录/主对端/限速/进度/
      退出码(参数错误2/运行错误1)/事件输出/duration
"""
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable
PORT_BASE = 19800  # 本文件专用端口段, 避免与其他测试冲突


def cli(*args, timeout=20):
    """运行命令行版本, 返回 (returncode, stdout, stderr)."""
    p = subprocess.run([PYTHON, "-u", "-m", "transponder", "--nogui", *args],
                       capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    return p.returncode, p.stdout, p.stderr


def tcp_echo(port, accept_count=1):
    """起一个 TCP 回声服务 (单次 accept 若 accept_count=1)."""
    srv = socket.create_server(("127.0.0.1", port))
    def loop():
        conns = []
        for _ in range(accept_count):
            try:
                conn, _ = srv.accept()
            except OSError:
                break
            conns.append(conn)
            def h(c):
                try:
                    while True:
                        d = c.recv(65536)
                        if not d:
                            break
                        c.sendall(d)
                except OSError:
                    pass
            threading.Thread(target=h, args=(conn,), daemon=True).start()
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return srv


PASS = 0


def ok(name, cond, detail=""):
    global PASS
    assert cond, f"[{name}] FAIL {detail}"
    PASS += 1
    print(f"  PASS {name}")


# ============ 查询与元信息 ============
rc, out, err = cli("--version")
ok("version", rc == 0 and "MW数据转发器" in out and re.search(r"v\d+\.\d+", out), out)

rc, out, err = cli("--help")
ok("help-exit", rc == 0)
for token in ["--nogui", "--duration", "--log-dir", "--log-fmt-m", "--list-serial",
              "--list-net", "--version", "serial", "file-send", "tcp-client",
              "tcp-server", "udp", "multicast", "broadcast", "示例"]:
    assert token in out, f"help 缺少 {token}"
ok("help-content", True)

rc, out, err = cli("--list-serial")
ok("list-serial", rc == 0 and ("[" in out or "未发现串口" in out), out)

rc, out, err = cli("--list-net")
ok("list-net", rc == 0 and "本机地址" in out and "广播地址" in out
   and "0.0.0.0" in out and "127.0.0.1" in out, out)

# ============ 正常转发用例 ============
print("== 正常转发 ==")
TMP = tempfile.mkdtemp(prefix="tcli_")

# T1: tcp-client <-> tcp-server 双向回声 (外部客户端经 W 到 M 的 echo)
ECHO = PORT_BASE + 1
SRV = PORT_BASE + 2      # T1
SRV2 = PORT_BASE + 5     # T2
SRV3A = PORT_BASE + 6   # T3
SRV3B = PORT_BASE + 7
SRV5 = PORT_BASE + 8     # T5
SRV6 = PORT_BASE + 9     # T6
SRV7 = PORT_BASE + 10    # T7
SRV8 = PORT_BASE + 11    # T8
SRV9 = PORT_BASE + 12    # T9
echo_srv = tcp_echo(ECHO)
p = subprocess.Popen(
    [PYTHON, "-u", "-m", "transponder", "--nogui",
     "-m", f"tcp-client:host=127.0.0.1,port={ECHO},local_host=127.0.0.1,local_port={PORT_BASE+3}",
     "-w", f"tcp-server:host=127.0.0.1,port={SRV},backlog=8",
     "--duration", "4"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
time.sleep(1.2)
c = socket.create_connection(("127.0.0.1", SRV), timeout=3)
c.settimeout(3)
payload = b"cli-echo-test" * 40
c.sendall(payload)
got = b""
while len(got) < len(payload):
    d = c.recv(65536)
    if not d:
        break
    got += d
c.close()
out = p.communicate(timeout=10)[0]
ok("T1-tcp-echo", got == payload, f"{len(got)}/{len(payload)}")
ok("T1-summary", "结束: M→W" in out and f"M→W {len(payload)} 字节" in out, out[-120:])
ok("T1-events", "[事件]" in out and "已接入" in out)
ok("T1-stats-w2m", f"W→M {len(payload)} 字节" in out)
echo_srv.close()

# T2: file-send 限速 -> tcp-server, 文件内容一致 + 进度输出
data = bytes(range(256)) * 48  # 12KB
sendfile = os.path.join(TMP, "send.bin")
open(sendfile, "wb").write(data)
p = subprocess.Popen(
    [PYTHON, "-u", "-m", "transponder", "--nogui",
     "-m", f"file-send:path={sendfile},b=500,kb=30",
     "-w", f"tcp-server:host=127.0.0.1,port={SRV2}",
     "--duration", "10"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
time.sleep(1.2)
got = b""
c = socket.create_connection(("127.0.0.1", SRV2), timeout=3)
c.settimeout(5)
while len(got) < len(data):
    d = c.recv(65536)
    if not d:
        break
    got += d
c.close()
out = p.communicate(timeout=15)[0]
ok("T2-file-send", got == data, f"{len(got)}/{len(data)}")
ok("T2-progress", "进度:" in out, out[-200:])
ok("T2-filedone-event", "文件已读完" in out)

# T3: tcp-server(M) <- 外部客户端发送, file-recv(W) 落盘
recvfile = os.path.join(TMP, "recv.bin")
p = subprocess.Popen(
    [PYTHON, "-u", "-m", "transponder", "--nogui",
     "-m", f"tcp-server:host=127.0.0.1,port={SRV3A}",
     "-w", f"file-recv:path={recvfile},append=0",
     "--duration", "4"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
time.sleep(1.0)
c = socket.create_connection(("127.0.0.1", SRV3A), timeout=3)
payload3 = b"store-me-" * 300
c.sendall(payload3)
time.sleep(0.8)
c.close()
out = p.communicate(timeout=10)[0]
ok("T3-file-recv", open(recvfile, "rb").read() == payload3)
# 再验证 append=1 追加
p = subprocess.Popen(
    [PYTHON, "-u", "-m", "transponder", "--nogui",
     "-m", f"tcp-server:host=127.0.0.1,port={SRV3B}",
     "-w", f"file-recv:path={recvfile},append=1",
     "--duration", "3"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
time.sleep(1.0)
c = socket.create_connection(("127.0.0.1", SRV3B), timeout=3)
c.sendall(b"APPEND")
time.sleep(0.6)
c.close()
p.communicate(timeout=10)
ok("T3-append", open(recvfile, "rb").read() == payload3 + b"APPEND")

# T4: UDP 单播 (未指定对端, 锁定第一帧来源; 经外部 echo 回程)
UE = PORT_BASE + 11
US = PORT_BASE + 12
udp_echo = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_echo.bind(("127.0.0.1", UE))
def udp_echo_loop():
    while True:
        d, a = udp_echo.recvfrom(65536)
        udp_echo.sendto(d, a)
threading.Thread(target=udp_echo_loop, daemon=True).start()
p = subprocess.Popen(
    [PYTHON, "-u", "-m", "transponder", "--nogui",
     "-m", f"udp:host=127.0.0.1,port={US}",
     "-w", f"udp:host=127.0.0.1,peer=127.0.0.1:{UE}",
     "--duration", "4"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
time.sleep(1.0)
c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
c.settimeout(3)
c.sendto(b"udp-lock-", ("127.0.0.1", US))  # 第一帧: 锁定对端
time.sleep(0.4)
c.sendto(b"U" * 1500, ("127.0.0.1", US))
got = b""
try:
    while len(got) < 8 + 1500:
        d, _ = c.recvfrom(65536)
        got += d
except socket.timeout:
    pass
out = p.communicate(timeout=10)[0]
ok("T4-udp-lock", b"udp-lock-" in got and b"U" * 1500 in got, f"{len(got)}B")
ok("T4-lock-event", "对端锁定为" in out)

# T5: UDP 指定对端过滤 (非对端来源的数据不转发)
UF = PORT_BASE + 13
PEERPORT = PORT_BASE + 15
p = subprocess.Popen(
    [PYTHON, "-u", "-m", "transponder", "--nogui",
     "-m", f"udp:host=127.0.0.1,port={UF},peer=127.0.0.1:{PEERPORT}",
     "-w", f"tcp-server:host=127.0.0.1,port={SRV5}",
     "--duration", "3"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
time.sleep(0.8)
other = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
other.bind(("127.0.0.1", PORT_BASE + 14))
other.sendto(b"IGNORED", ("127.0.0.1", UF))  # 非指定对端 -> 过滤
peer_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
peer_sock.bind(("127.0.0.1", PEERPORT))
peer_sock.sendto(b"PEEROK", ("127.0.0.1", UF))  # 指定对端 -> 转发
time.sleep(1.5)
c = socket.create_connection(("127.0.0.1", SRV5), timeout=2)
c.settimeout(2)
try:
    rx = c.recv(100)
except socket.timeout:
    rx = b""
out = p.communicate(timeout=10)[0]
ok("T5-udp-filter", rx == b"PEEROK", rx)
udp_echo.close()

# T6: 组播自回环过滤 (进程自己发的不回到自己, 本机其他成员能收)
MG, MP = "239.11.11.11", PORT_BASE + 21
p = subprocess.Popen(
    [PYTHON, "-u", "-m", "transponder", "--nogui",
     "-m", f"multicast:group={MG},port={MP},ttl=1",
     "-w", f"tcp-server:host=127.0.0.1,port={SRV6}",
     "--duration", "4"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
time.sleep(1.0)
member = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
member.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
mreq = socket.inet_aton(MG) + socket.inet_aton("0.0.0.0")
member.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
member.bind(("0.0.0.0", MP))
member.settimeout(2)
c = socket.create_connection(("127.0.0.1", SRV6), timeout=3)
c.sendall(b"MCAST-FROM-OUTSIDE")  # 外部客户端 -> 组播 W 侧
time.sleep(1.2)
try:
    d, _ = member.recvfrom(100)
except socket.timeout:
    d = b""
out = p.communicate(timeout=10)[0]
ok("T6-multicast-forward", d == b"MCAST-FROM-OUTSIDE", d)
c.close()
member.close()

# T7: 广播 (自定义广播地址+本地端口), 外部接收者能收到
BP = PORT_BASE + 31
p = subprocess.Popen(
    [PYTHON, "-u", "-m", "transponder", "--nogui",
     "-m", f"broadcast:addr=127.255.255.255,port={BP},local_port={PORT_BASE+32}",
     "-w", f"tcp-server:host=127.0.0.1,port={SRV7}",
     "--duration", "3"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
time.sleep(0.8)
r = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
r.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
r.bind(("0.0.0.0", BP))
r.settimeout(2)
c = socket.create_connection(("127.0.0.1", SRV7), timeout=3)
c.sendall(b"BCAST-OUT")
time.sleep(1.0)
try:
    d, _ = r.recvfrom(100)
except socket.timeout:
    d = b""
out = p.communicate(timeout=10)[0]
ok("T7-broadcast", d == b"BCAST-OUT", d)
c.close(); r.close()

# T8: 落地记录 分侧格式 (M=bin, W=txt+时间戳), 文件夹名格式
logs = os.path.join(TMP, "logs")
p = subprocess.Popen(
    [PYTHON, "-u", "-m", "transponder", "--nogui",
     "-m", f"tcp-client:host=127.0.0.1,port={ECHO}",
     "-w", f"tcp-server:host=127.0.0.1,port={SRV8}",
     "--log-dir", logs, "--log-m", "--log-fmt-m", "bin",
     "--log-w", "--log-fmt-w", "txt", "--log-ts-w", "200",
     "--duration", "4"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
echo_srv2 = tcp_echo(ECHO)
time.sleep(1.0)
c = socket.create_connection(("127.0.0.1", SRV8), timeout=3)
c.settimeout(3)
c.sendall(b"LOGTEST")
try:
    c.recv(100)
except socket.timeout:
    pass
c.close()
out = p.communicate(timeout=10)[0]
dirs = [d for d in os.listdir(logs) if os.path.isdir(os.path.join(logs, d))]
ok("T8-folder", len(dirs) == 1 and re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", dirs[0]), dirs)
files = sorted(os.listdir(os.path.join(logs, dirs[0])))
ok("T8-files", files == ["M.bin", "W.txt"], files)
ok("T8-bin", open(os.path.join(logs, dirs[0], "M.bin"), "rb").read() == b"LOGTEST")
wtxt = open(os.path.join(logs, dirs[0], "W.txt"), encoding="utf-8").read()
ok("T8-txt", "LOGTEST" in wtxt and re.search(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\]", wtxt))
echo_srv2.close()

# T9: tcp-server primary 指定 (客户端绑定固定本地端口)
PP = PORT_BASE + 41
main_c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
main_c.bind(("127.0.0.1", PP))  # 固定本地端口以便 primary 匹配
other_c = socket.socket()
p = subprocess.Popen(
    [PYTHON, "-u", "-m", "transponder", "--nogui",
     "-m", f"tcp-server:host=127.0.0.1,port={SRV9},primary=127.0.0.1:{PP}",
     "-w", f"tcp-client:host=127.0.0.1,port={ECHO}",
     "--duration", "4"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
echo_srv3 = tcp_echo(ECHO)
time.sleep(1.0)
main_c.settimeout(3); main_c.connect(("127.0.0.1", SRV9))
other_c.settimeout(0.8); other_c.connect(("127.0.0.1", SRV9))
time.sleep(0.5)
other_recv = []
def other_reader():
    try:
        other_recv.append(other_c.recv(100))
    except socket.timeout:
        other_recv.append(None)
threading.Thread(target=other_reader, daemon=True).start()
main_c.sendall(b"MAIN")
echo_back = b""
try:
    while len(echo_back) < 4:
        d = main_c.recv(100)
        if not d:
            break
        echo_back += d  # 经 primary -> tcp-client -> echo -> 回到 main
except socket.timeout:
    pass
time.sleep(1.2)
out = p.communicate(timeout=10)[0]
ok("T9-primary-echo", echo_back == b"MAIN", echo_back)
ok("T9-other-silent", other_recv == [None], other_recv)  # 非主要对端不收
ok("T9-primary-event", "主要对端" in out)
main_c.close(); other_c.close()
echo_srv3.close()

# ============ 异常用例 ============
print("== 异常用例 ==")
rc, out, err = cli()
ok("E1-no-spec", rc == 2 and "需要同时指定 -m 和 -w" in err, f"{rc} {err}")
rc, out, err = cli("-m", "udp:port=19001")
ok("E2-only-m", rc == 2)
rc, out, err = cli("-m", "nosuchtype:x=1", "-w", "udp:port=19001")
ok("E3-unknown-type", rc == 2 and "未知数据源类型" in err)
rc, out, err = cli("-m", "serial:baud=115200", "-w", "udp:port=19001")
ok("E4-serial-noport", rc == 2 and "缺少参数 port" in err)
rc, out, err = cli("-m", "tcp-client:port=9000", "-w", "udp:port=19001")
ok("E5-tcpclient-nohost", rc == 2 and "缺少参数 host" in err)
rc, out, err = cli("-m", "multicast:group=192.168.1.1,port=5000", "-w", "udp:port=19001")
ok("E6-bad-mcast", rc == 2 and "224.0.0.0/4" in err)
rc, out, err = cli("-m", "udp:port=19001,peer=notaddr", "-w", "udp:port=19002")
ok("E7-bad-peer", rc == 2 and "ip:port" in err)
rc, out, err = cli("-m", "file-send:path=/no/such/file.bin", "-w", "udp:port=19001")
ok("E8-file-notfound", rc == 1 and "错误" in err, f"{rc} {err}")
rc, out, err = cli("-m", f"tcp-client:host=127.0.0.1,port={PORT_BASE+99}", "-w", "udp:port=19001",
                    "--duration", "2")
ok("E9-connect-refused", rc == 1 and "错误" in err, f"{rc} {err}")
rc, out, err = cli("-m", "serial:port=COM255,baud=1", "-w", "udp:port=19001")
ok("E10-serial-openfail", rc == 1, f"{rc} {err}")
rc, out, err = cli("-m", "udp:port=19001", "-w", "udp:port=19002",
                   "--log-m", "--duration", "1")
ok("E11-log-without-dir", rc == 0 and "未指定 --log-dir" in err, f"{rc} {err}")
rc, out, err = cli("-m", "udp:port=19001", "-w", "udp:port=19002", "--log-fmt", "badfmt")
ok("E12-bad-fmt", rc == 2 and "invalid choice" in err.lower() + err)
rc, out, err = cli("-m", ":x=1", "-w", "udp:port=19001")
ok("E13-empty-type", rc == 2 and "未知数据源类型" in err)
rc, out, err = cli("-m", "udp:port=abc", "-w", "udp:port=19002", "--duration", "1")
ok("E14-bad-int", rc == 2 and "参数错误" in err)

print(f"\nALL {PASS} CASES PASS")
