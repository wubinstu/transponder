"""GUI 通用格式化工具 (各模块共用, 避免重复实现)."""

from __future__ import annotations


def fmt_bytes(n: float) -> str:
    """字节数智能单位显示, 保留一位小数."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_rate(bps: float) -> str:
    """速率显示: 智能单位, 保留两位小数."""
    for unit, factor in (("B", 1), ("KB", 1024), ("MB", 1024 * 1024)):
        if bps < 1024 * factor:
            return f"{bps / factor:.2f} {unit}/s"
    return f"{bps / 1024**3:.2f} GB/s"
