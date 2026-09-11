"""版本号 (与 git 提交序列对应, 每轮修改意见/功能迭代递增).

打包 exe 时由该文件固化版本; 源码运行时若可用则优先读 git 标签.
"""

__version__ = "6.4"


def get_version() -> str:
    """返回 'v6.4' 形式; 源码环境下尝试用 git 标签校准 (失败则用内置版本)."""
    try:
        import subprocess
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tag = subprocess.run(
            ["git", "-C", root, "describe", "--tags", "--exact-match", "HEAD"],
            capture_output=True, text=True, timeout=3).stdout.strip()
        if tag.startswith("v"):
            return tag
    except Exception:
        pass
    return f"v{__version__}"
