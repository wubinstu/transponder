"""GUI 入口: run_gui(args) 打开图形界面并按命令行参数预填充."""

from __future__ import annotations

import sys


def run_gui(args=None) -> int:
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
    except Exception as e:  # PySide6 未安装
        print(f"错误: 无法加载图形界面依赖 PySide6: {e}", file=sys.stderr)
        return 3

    try:
        app = QApplication(sys.argv)
    except Exception as e:  # 无显示环境 (如无 X server / 远程终端)
        print(f"错误: 当前系统无图形化环境, 无法启动 UI ({e}); "
              f"可加 --nogui 使用命令行模式", file=sys.stderr)
        return 3

    from PySide6.QtWidgets import QMessageBox
    app.setStyle("Fusion")
    from .theme import QSS
    app.setStyleSheet(QSS)
    from .main_window import MainWindow

    prefill = None
    if args is not None and (args.spec_m or args.spec_w):
        prefill = {"m": args.spec_m, "w": args.spec_w,
                   "log_dir": args.log_dir, "log_m": args.log_m,
                   "log_w": args.log_w, "log_fmt": args.log_fmt,
                   "log_ts": args.log_ts}
    win = MainWindow(prefill)
    win.show()
    return app.exec()
