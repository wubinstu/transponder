"""程序入口.

- 无参数: 打开图形界面
- 查询类参数 (--list-serial/--list-net/--version/--help): 直接执行, 不开界面
- 带转发参数但无 --nogui: 打开图形界面, 并把参数填充到界面对应配置
- --nogui: 纯命令行模式 (单次运行, 适合脚本/AI agent)
- 无图形化环境: 抛出异常并给出明确提示

exe 定位 (v6.5 起): 双击/任何参数均进入 GUI (带参数时预填充配置)。
命令行模式请使用源码: python -m transponder --nogui ...
(窗口子系统 exe 在各种终端下恢复控制台输出的行为不一致, 不再尝试)。
"""

import sys


def _force_utf8_streams() -> None:
    """统一输出编码为 UTF-8 (中文 Windows 下 locale 默认 GBK,
    会导致按 UTF-8 读取管道的脚本/agent 解码失败)."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main() -> int:
    _force_utf8_streams()

    if getattr(sys, "frozen", False):
        # 打包 exe: 只走 GUI (带参数则预填充); 命令行请使用源码方式
        from .gui import run_gui
        return run_gui()

    from .cli import build_argparser, info_commands
    parser = build_argparser()
    args = parser.parse_args()  # --version/--help 在此自行处理并退出

    r = info_commands(args)
    if r >= 0:  # 查询类命令已处理
        return r

    if args.nogui:
        from .cli import run
        return run(args)

    from .gui import run_gui
    return run_gui(args)


if __name__ == "__main__":
    sys.exit(main())
