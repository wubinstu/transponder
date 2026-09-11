"""版本号 (与 git 提交序列对应, 每轮修改意见/功能迭代递增).

- 打包 exe (sys.frozen): 直接使用本文件固化的版本, 不调用 git
  (窗口程序调用外部命令会闪黑色控制台窗口, 且拖慢启动);
- 源码运行: 优先读 git 精确标签, 结果缓存; 子进程带 CREATE_NO_WINDOW 防闪框.
"""

import sys

__version__ = "6.5"

_cached: str | None = None


def get_version() -> str:
    """返回 'v6.4.1' 形式版本号."""
    global _cached
    if _cached:
        return _cached
    if not getattr(sys, "frozen", False):  # 源码环境尝试 git 标签
        try:
            import os
            import subprocess
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            tag = subprocess.run(
                ["git", "-C", root, "describe", "--tags", "--exact-match", "HEAD"],
                capture_output=True, text=True, timeout=3,
                creationflags=no_window).stdout.strip()
            if tag.startswith("v"):
                _cached = tag
                return tag
        except Exception:
            pass
    _cached = f"v{__version__}"
    return _cached
