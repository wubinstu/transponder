"""程序入口.

- 无参数: 打开图形界面
- 查询类参数 (--list-serial/--list-net/--version/--help): 直接执行, 不开界面
- 带转发参数但无 --nogui: 打开图形界面, 并把参数填充到界面对应配置
- --nogui: 纯命令行模式 (单次运行, 适合脚本/AI agent)
- 无图形化环境: 抛出异常并给出明确提示
"""

import sys


def _attach_parent_console() -> None:
    """窗口子系统 exe (-w 打包) 从终端启动时, 附加父控制台以恢复 stdout/stderr.

    双击运行 (explorer 启动, 无控制台) 时 AttachConsole 失败, 保持纯 GUI;
    被脚本/agent 以管道方式调用时标准流本身有效, 无需附加.
    """
    if sys.platform != "win32":
        return
    if sys.stdout is not None and sys.stderr is not None:
        return  # 已有有效标准流 (管道/真实控制台)
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if kernel32.GetConsoleWindow():
            return
        ATTACH_PARENT_PROCESS = -1  # noqa: N806
        if not kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            return
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", closefd=False)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", closefd=False)
        sys.stdin = open("CONIN$", "r", encoding="utf-8", closefd=False)
    except Exception:
        pass


def _force_utf8_streams() -> None:
    """统一输出编码为 UTF-8 (打包 exe 在中文 Windows 下 stdout 默认是 GBK,
    会导致按 UTF-8 读取管道的脚本/agent 解码失败)."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main() -> int:
    if len(sys.argv) > 1:
        _attach_parent_console()
    _force_utf8_streams()

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
