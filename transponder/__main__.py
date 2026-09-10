"""程序入口.

- 无参数: 打开图形界面
- 查询类参数 (--list-serial/--list-net): 直接执行, 不开界面
- 带转发参数但无 --nogui: 打开图形界面, 并把参数填充到界面对应配置
- --nogui: 纯命令行模式
- 无图形化环境: 抛出异常并给出明确提示
"""

import sys

from .cli import build_argparser, info_commands


def main() -> int:
    parser = build_argparser()
    args = parser.parse_args()

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
