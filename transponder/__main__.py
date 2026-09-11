"""程序入口.

- 无参数: 打开图形界面
- 查询类参数 (--list-serial/--list-net/--version/--help): 直接执行, 不开界面
- 带转发参数但无 --nogui: 打开图形界面, 并把参数填充到界面对应配置
- --nogui: 纯命令行模式 (单次运行, 适合脚本/AI agent)
- 无图形化环境: 抛出异常并给出明确提示

打包说明: exe 用窗口子系统 (-w), 双击无黑框; 从终端带参数启动时自动附加父控制台
恢复输出; 被脚本/agent 以管道调用时标准流天然有效; 若终端无 Windows 控制台且无法
附加 (如 mintty), 弹窗提示改用 cmd/PowerShell 或源码方式运行命令行模式.
"""

import sys

# 需要控制台输出的命令行模式标记 (用于附加父控制台/提示)
_CONSOLE_FLAGS = {"--nogui", "--list-serial", "--list-net", "--version", "-h", "--help"}


def _needs_console() -> bool:
    return any(a in _CONSOLE_FLAGS for a in sys.argv[1:])


def _attach_parent_console() -> bool:
    """窗口子系统 exe 从终端启动时, 附加父控制台以恢复 stdout/stderr.

    双击运行 (无控制台父进程) 时失败, 保持纯 GUI;
    被脚本/agent 以管道方式调用时标准流本身有效, 无需附加.
    返回是否获得了可用的标准输出.
    """
    if sys.platform != "win32":
        return True  # 非 Windows 终端天然有效
    if sys.stdout is not None:
        return True
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if kernel32.GetConsoleWindow():
            return True
        ATTACH_PARENT_PROCESS = -1  # noqa: N806
        if not kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            return False
        kernel32.SetConsoleOutputCP(65001)  # UTF-8, 避免中文乱码
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", closefd=False)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", closefd=False)
        sys.stdin = open("CONIN$", "r", encoding="utf-8", closefd=False)
        return True
    except Exception:
        return False


def _force_utf8_streams() -> None:
    """统一输出编码为 UTF-8 (打包 exe 在中文 Windows 下 stdout 默认是 GBK,
    会导致按 UTF-8 读取管道的脚本/agent 解码失败)."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _no_console_hint() -> None:
    """命令行模式但无法获得控制台输出 (如 mintty 无 Windows 控制台): 弹窗告知.

    agent/管道调用不经过此分支 (标准流有效)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        MB_OK, MB_ICONINFORMATION = 0, 0x40
        ctypes.windll.user32.MessageBoxW(
            0,
            "当前终端没有可用的 Windows 控制台, 命令行输出无法显示。\n\n"
            "请改用 cmd / PowerShell 运行本 exe 的命令行模式,\n"
            "或使用源码方式: python -m transponder --nogui ...\n"
            "(双击打开图形界面不受影响)",
            "MW数据转发器", MB_OK | MB_ICONINFORMATION)
    except Exception:
        pass


def main() -> int:
    attached = True
    if len(sys.argv) > 1:
        attached = _attach_parent_console()
    _force_utf8_streams()

    from .cli import build_argparser, info_commands
    parser = build_argparser()
    args = parser.parse_args()  # --version/--help 在此自行处理并退出

    r = info_commands(args)
    if r >= 0:  # 查询类命令已处理
        return r

    if args.nogui:
        if not attached and sys.stdout is None:
            _no_console_hint()  # 附加失败且无标准流: 无法展示输出
        from .cli import run
        return run(args)

    from .gui import run_gui
    return run_gui(args)


if __name__ == "__main__":
    sys.exit(main())
