"""命令行无 UI 模式 (--nogui 时进入).

用法示例:
    python -m transponder --nogui --list-serial
    python -m transponder --nogui -m serial:port=COM3,baud=115200 -w tcp-client:host=192.168.1.10,port=9000
    python -m transponder --nogui -m file-send:path=a.bin,b=100,kb=1 -w udp:port=9000 --log-dir logs --log-m --log-fmt bin
Ctrl+C 停止转发并退出.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time

from .core import (
    Bridge, LogSession, parse_spec, parse_primary,
    scan_serial_ports, scan_local_addresses, scan_broadcast_addresses,
)


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="transponder",
        description="数据转发器: 在串口/网络/文件之间转发数据 (加 --nogui 进入无UI模式, 不加则打开图形界面并填充参数)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-m", dest="spec_m", metavar="SPEC",
                   help="数据源 M 规格, 如 serial:port=COM3,baud=115200")
    p.add_argument("-w", dest="spec_w", metavar="SPEC",
                   help="数据源 W 规格, 如 tcp-client:host=192.168.1.10,port=9000")
    p.add_argument("--nogui", action="store_true",
                   help="使用命令行模式 (默认带参数时打开图形界面并填充参数)")
    p.add_argument("--duration", type=float, metavar="SEC", default=0,
                   help="转发指定秒数后自动停止 (0=一直转发)")
    p.add_argument("--log-dir", metavar="DIR",
                   help="数据落地根目录 (需配合 --log-m/--log-w)")
    p.add_argument("--log-m", action="store_true", help="记录数据源 M 的数据")
    p.add_argument("--log-w", action="store_true", help="记录数据源 W 的数据")
    p.add_argument("--log-fmt", choices=["bin", "txt"], default="bin",
                   help="落地格式默认值: bin=原始二进制, txt=文本 (默认 bin)")
    p.add_argument("--log-fmt-m", choices=["bin", "txt"],
                   help="M 侧落地格式 (覆盖 --log-fmt)")
    p.add_argument("--log-fmt-w", choices=["bin", "txt"],
                   help="W 侧落地格式 (覆盖 --log-fmt)")
    p.add_argument("--log-ts", type=int, metavar="MS", default=0,
                   help="txt 格式的时间戳输出间隔毫秒默认值 (0=不输出)")
    p.add_argument("--log-ts-m", type=int, metavar="MS",
                   help="M 侧时间戳间隔 (覆盖 --log-ts)")
    p.add_argument("--log-ts-w", type=int, metavar="MS",
                   help="W 侧时间戳间隔 (覆盖 --log-ts)")
    p.add_argument("--list-serial", action="store_true", help="列出可用串口后退出")
    p.add_argument("--list-net", action="store_true", help="列出本机网卡地址/广播地址后退出")
    return p


def info_commands(args: argparse.Namespace) -> int:
    """查询类命令: 直接执行输出, 不需要 GUI."""
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
    return -1  # 无查询命令


def run(args: argparse.Namespace) -> int:
    """无 UI 转发主流程."""
    r = info_commands(args)
    if r >= 0:
        return r
    if not args.spec_m or not args.spec_w:
        print("错误: 无UI模式需要同时指定 -m 和 -w", file=sys.stderr)
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
