"""端到端回环测试 (v2: --nogui, 落地记录 bin):
1. tcp-client(local bind) <-> tcp-server: 外部客户端收到经由转发的回声
2. 落地记录: 时间戳文件夹 + M.bin 原始数据
3. file-send(限速) -> tcp-server 文件内容一致
"""
import socket, subprocess, sys, time, os, tempfile, threading

PORT = 19301
ECHO_PORT = 19302


def echo_server():
    srv = socket.create_server(("127.0.0.1", ECHO_PORT))
    while True:
        conn, _ = srv.accept()
        def handle(c):
            try:
                while True:
                    d = c.recv(65536)
                    if not d:
                        break
                    c.sendall(d)
            except OSError:
                pass
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


threading.Thread(target=echo_server, daemon=True).start()

tmp = tempfile.mkdtemp()
sendfile = os.path.join(tmp, "send.bin")


def run_tp(args, duration=4):
    return subprocess.Popen(
        [sys.executable, "-m", "transponder", "--nogui", *args, "--duration", str(duration)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


# 拓扑: 外部测试客户端 <-> W(tcp-server:19301) <-> M(tcp-client -> echo:19302)
# 指定 M 的本地绑定端口以验证 local_port 参数
p = run_tp(["-m", f"tcp-client:host=127.0.0.1,port={ECHO_PORT},local_host=127.0.0.1,local_port=19399",
            "-w", f"tcp-server:host=127.0.0.1,port={PORT}",
            "--log-dir", tmp, "--log-m", "--log-fmt", "bin"])
time.sleep(1.5)
try:
    c = socket.create_connection(("127.0.0.1", PORT), timeout=3)
    c.settimeout(3)
    payload = b"hello transponder " * 50
    c.sendall(payload)
    got = b""
    while len(got) < len(payload):
        chunk = c.recv(65536)
        if not chunk:
            break
        got += chunk
    assert got == payload, f"回声数据不一致: {len(got)}/{len(payload)}"
    print("TEST1 PASS: tcp 回声转发 + 本地绑定", len(got), "bytes")
    c.close()
    out = p.communicate(timeout=10)[0]
finally:
    if p.poll() is None:
        p.terminate()
print(out)
assert "结束" in out

# 落地记录: 自动创建时间戳文件夹 + M.bin 内容与 payload 一致
dirs = [d for d in os.listdir(tmp) if d != "send.bin" and os.path.isdir(os.path.join(tmp, d))]
assert len(dirs) == 1, f"应创建一个时间戳文件夹: {dirs}"
import re
assert re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", dirs[0]), dirs[0]
mbin = os.path.join(tmp, dirs[0], "M.bin")
data = open(mbin, "rb").read()
assert data == payload, f"M.bin 应为 {len(payload)} 字节, 实际 {len(data)}"
assert not os.path.exists(os.path.join(tmp, dirs[0], "W.bin")), "未开启 W 记录不应生成 W.bin"
print("TEST2 PASS: 落地记录 (时间戳文件夹 + M.bin)")

# file-send 限速 -> tcp-server
data3 = bytes(range(256)) * 40
with open(sendfile, "wb") as f:
    f.write(data3)
p = run_tp(["-m", f"file-send:path={sendfile},b=500,kb=20", "-w",
            f"tcp-server:host=127.0.0.1,port={PORT}"], duration=10)
time.sleep(1.5)
got = b""
try:
    c = socket.create_connection(("127.0.0.1", PORT), timeout=3)
    c.settimeout(5)
    while len(got) < len(data3):
        chunk = c.recv(65536)
        if not chunk:
            break
        got += chunk
    assert got == data3, f"文件转发不一致: {len(got)}/{len(data3)}"
    print("TEST3 PASS: 文件三滑块限速转发", len(got), "bytes")
    c.close()
    out = p.communicate(timeout=15)[0]
finally:
    if p.poll() is None:
        p.terminate()
print(out)
print("ALL PASS")
