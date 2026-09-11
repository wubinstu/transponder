"""命令行无 UI 模式 (--nogui 时进入).

设计定位: 单次运行式 CLI —— 传入参数即开始转发, Ctrl+C 或 --duration 到时停止退出;
需要调整配置时退出后重新组织参数再执行. 无交互、无状态, 适合脚本/AI agent 调用
(stdout 可捕获, 退出码可判断). 与 GUI 共享同一套 core 转发引擎.

退出码: 0=正常结束; 1=运行错误(连接失败/文件不存在等); 2=参数错误; 3=无图形环境(GUI路径).
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time

from ._version import get_version
from .core import (
    Bridge, LogSession, parse_spec, parse_primary,
    scan_serial_ports, scan_local_addresses, scan_broadcast_addresses,
)

SPEC_HELP = """\
数据源规格 SPEC 格式:  类型:参数=值,参数=值  (顺序任意, 未给参数用默认值)

  serial      串口           port=COM3, baud=115200, data=8, parity=N|E|O, stop=1, flow=none|rtscts
  file-send   文件读→发送    path=文件, b=500,kb=20,mb=0   (限速=b+1024*kb+1024*1024*mb B/s, 全0=不限速; 读完即止)
  file-recv   文件写←接收    path=文件, append=0|1          (1=追加, 0=覆盖)
  tcp-client  TCP客户端      host=远端IP, port=远端端口, local_host=, local_port=0 (本地绑定, 0=自动)
  tcp-server  TCP服务端      host=0.0.0.0, port=9000, backlog=0(默认), primary=IP:PORT(主要对端)
  udp         UDP单播        host=0.0.0.0, port=0(自动), peer=IP:PORT (对端可选; 不填则锁定首个来源)
  multicast   组播           group=239.1.1.1 (224.0.0.0/4), port=5000, local_host=0.0.0.0, ttl=1
  broadcast   广播           addr=255.255.255.255, port=5000, local_host=0.0.0.0, local_port=0

说明:
  - M 的数据转发给 W, W 的数据转发给 M (双向); 文件只能单向.
  - tcp-server 的 primary 指定后仅与该客户端点对点, 不指定则发给全部客户端并接收全部.
  - 组播/广播自动过滤自己发出的回环数据, 本机其他程序可正常互通.
  - 落地记录: 每次开始转发在 --log-dir 下新建时间戳文件夹 (如 2026-09-11_10-20-56),
    内含 M.bin/M.txt 与 W.bin/W.txt; BIN=原始数据, TXT=文本+可选周期时间戳.

示例:
  %(prog)s --nogui --list-serial
  %(prog)s --nogui -m serial:port=COM3,baud=115200 -w tcp-client:host=192.168.1.10,port=9000
  %(prog)s --nogui -m file-send:path=data.bin,kb=20 -w tcp-server:port=9000 --duration 30
  %(prog)s --nogui -m udp:port=9000 -w file-recv:path=out.bin --log-dir logs --log-m --log-fmt bin
  %(prog)s --nogui -m multicast:group=239.1.1.1,port=5000 -w serial:port=COM3
  %(prog)s -m tcp-server:port=9000          # 不加 --nogui: 打开GUI并预填充该配置
"""


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="transponder",
        description=f"MW数据转发器 {get_version()} - 在串口/TCP/UDP单播/组播/广播/文件之间转发数据\n"
                    "带参数但未加 --nogui 时打开图形界面并填充参数; 加 --nogui 进入纯命令行转发模式.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=SPEC_HELP,
    )
    p.add_argument("-m", dest="spec_m", metavar="SPEC",
                   help="数据源 M 规格 (格式与示例见下方说明)")
    p.add_argument("-w", dest="spec_w", metavar="SPEC",
                   help="数据源 W 规格 (格式与示例见下方说明)")
    p.add_argument("--nogui", action="store_true",
                   help="使用命令行模式 (默认带参数时打开图形界面并填充参数)")
    p.add_argument("--duration", type=float, metavar="SEC", default=0,
                   help="转发指定秒数后自动停止并退出 (0=一直转发直到 Ctrl+C; 仅命令行模式)")
    p.add_argument("--version", action="version",
                   version=f"MW数据转发器 {get_version()}",
                   help="显示版本号并退出")
    p.add_argument("--log-dir", metavar="DIR",
                   help="数据落地记录根目录 (需配合 --log-m/--log-w)")
    p.add_argument("--log-m", action="store_true", help="记录数据源 M 的数据到文件")
    p.add_argument("--log-w", action="store_true", help="记录数据源 W 的数据到文件")
    p.add_argument("--log-fmt", choices=["bin", "txt"], default="bin",
                   help="落地格式默认值: bin=原始二进制, txt=文本 (默认 bin)")
    p.add_argument("--log-fmt-m", choices=["bin", "txt"],
                   help="M 侧落地格式 (覆盖 --log-fmt)")
    p.add_argument("--log-fmt-w", choices=["bin", "txt"],
                   help="W 侧落地格式 (覆盖 --log-fmt)")
    p.add_argument("--log-ts", type=int, metavar="MS", default=0,
                   help="txt 格式的时间戳输出间隔毫秒默认值 (0=不输出)")
    p.add_argument("--log-ts-m", type=int, metavar="MS",
                   help="M 侧时间戳间隔毫秒 (覆盖 --log-ts)")
    p.add_argument("--log-ts-w", type=int, metavar="MS",
                   help="W 侧时间戳间隔毫秒 (覆盖 --log-ts)")
    p.add_argument("--list-serial", action="store_true",
                   help="列出可用串口 (占用状态) 后退出")
    p.add_argument("--list-net", action="store_true",
                   help="列出本机网卡地址与广播地址后退出")
    return p


def info_commands(args: argparse.Namespace) -> int:
    """查询类命令: 直接执行输出, 不需要 GUI. 返回 -1 表示无查询命令."""
    if args.list_serial:
        ports = scan_serial_ports()
        if not ports:
            print("未发现串口")
        for p in ports:
            print(f"{p['port']}\t{'[占用]' if p['busy'] else '[可用]'}\t{p['desc']}")
        return 0
    if args.list_net:
        print("本机地址:")
        for ip in scan_local_addresses():
            print(f"  {ip}")
        print("广播地址:")
        for ip in scan_broadcast_addresses():
            print(f"  {ip}")
        return 0
    return -1


def run(args: argparse.Namespace) -> int:
    """无 UI 转发主流程."""
    r = info_commands(args)
    if r >= 0:
        return r
    if not args.spec_m or not args.spec_w:
        print("错误: 无UI模式需要同时指定 -m 和 -w (规格格式见 --help)", file=sys.stderr)
        return 2

    try:
        src_m = parse_spec(args.spec_m)
        src_w = parse_spec(args.spec_w)
        primary = parse_primary(args.spec_m) or parse_primary(args.spec_w)
    except ValueError as e:
        print(f"参数错误: {e}", file=sys.stderr)
        return 2

    session = None
    log_m = log_w = None
    if (args.log_m or args.log_w) and args.log_dir:
        session = LogSession(args.log_dir)
        if args.log_m:
            log_m = session.writer("M", args.log_fmt_m or args.log_fmt,
                                   args.log_ts_m if args.log_ts_m is not None else args.log_ts)
        if args.log_w:
            log_w = session.writer("W", args.log_fmt_w or args.log_fmt,
                                   args.log_ts_w if args.log_ts_w is not None else args.log_ts)
        print(f"落地记录目录: {session.dir}", flush=True)
    elif args.log_m or args.log_w:
        print("提示: 已指定 --log-m/--log-w 但未指定 --log-dir, 不记录", file=sys.stderr)

    def on_progress(done: int, total: int) -> None:
        if total and done % (256 * 1024) < 4096:  # 避免刷屏, 约每256KB打印一次
            print(f"\r进度: {done}/{total} ({done * 100 // total}%)", end="", flush=True)

    bridge = Bridge(
        src_m, src_w, log_m=log_m, log_w=log_w,
        on_event=lambda msg: print(f"[事件] {msg}", flush=True),
    )
    src_m.set_callbacks(on_progress=on_progress)
    src_w.set_callbacks(on_progress=on_progress)

    stop_evt = threading.Event()
    signal.signal(signal.SIGINT, lambda sig, frm: stop_evt.set())

    try:
        src_m.open()
        src_w.open()
        if primary:
            for src in (src_m, src_w):
                if src.supports_peers:
                    src.desired_primary = primary
        bridge.start()
        print("转发中... Ctrl+C 停止", flush=True)
        t0 = time.monotonic()
        while not stop_evt.is_set():
            time.sleep(0.2)
            if args.duration and time.monotonic() - t0 >= args.duration:
                break
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    finally:
        bridge.stop()
        src_m.close()
        src_w.close()
        if session:
            session.close()

    tm, _ = bridge.stats_m2w.snapshot()
    tw, _ = bridge.stats_w2m.snapshot()
    print(f"\n结束: M→W {tm} 字节, W→M {tw} 字节")
    return 0


def main() -> int:
    return run(build_argparser().parse_args())


if __name__ == "__main__":
    sys.exit(main())
