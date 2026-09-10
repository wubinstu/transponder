"""转发桥: 把两个数据源 M/W 的数据互相转发, 并提供统计与数据落地记录."""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

from .datasource import DataSource


class TrafficStats:
    """单方向流量统计: 累计字节 + 瞬时速率 (1s 滑动窗口估算)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.total = 0
        self.rate = 0.0
        self._window: list[tuple[float, int]] = []
        self._last_calc = 0.0

    def add(self, n: int) -> None:
        with self._lock:
            self.total += n
            self._window.append((time.monotonic(), n))
            now = time.monotonic()
            if now - self._last_calc >= 0.5:
                self._recalc(now)

    def _recalc(self, now: float) -> None:
        self._window = [(t, n) for t, n in self._window if now - t <= 1.0]
        self.rate = sum(n for _, n in self._window)
        self._last_calc = now

    def snapshot(self) -> tuple[int, float]:
        with self._lock:
            if time.monotonic() - self._last_calc >= 0.5:
                self._recalc(time.monotonic())
            return self.total, self.rate


class SourceLog:
    """单侧数据源的落地记录.

    fmt='bin': 仅写入原始二进制数据
    fmt='txt': 写入数据文本; ts_interval_ms>0 时每隔该间隔输出一次时间戳行(自动换行)
    """

    def __init__(self, path: str, fmt: str, ts_interval_ms: int = 0) -> None:
        self.fmt = fmt
        self.ts_interval_ms = ts_interval_ms
        self.path = path
        self._f = open(path, "wb" if fmt == "bin" else "a", encoding=None if fmt == "bin" else "utf-8")
        self._lock = threading.Lock()
        self._last_ts = 0.0

    def log(self, data: bytes) -> None:
        with self._lock:
            if self.fmt == "bin":
                self._f.write(data)
            else:
                now = time.monotonic()
                if self.ts_interval_ms > 0 and \
                        (now - self._last_ts) * 1000 >= self.ts_interval_ms:
                    self._f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}.{int(time.time()*1000)%1000:03d}]\n")
                    self._last_ts = now
                self._f.write(data.decode("utf-8", errors="replace"))

    def close(self) -> None:
        with self._lock:
            self._f.close()


class LogSession:
    """一次落地记录会话: 在 basedir 下自动创建时间戳文件夹.

    文件夹命名如 2026-09-10_11-20-56 (Windows 文件名不允许冒号),
    内含 M.bin/M.txt/W.bin/W.txt, 按需创建.
    """

    def __init__(self, basedir: str) -> None:
        self.dir = os.path.join(basedir, time.strftime("%Y-%m-%d_%H-%M-%S"))
        os.makedirs(self.dir, exist_ok=True)
        self._writers: dict[str, SourceLog] = {}

    def writer(self, side: str, fmt: str, ts_interval_ms: int = 0) -> SourceLog:
        """side: 'M' | 'W'; fmt: 'bin' | 'txt'."""
        key = f"{side}.{fmt}"
        if key not in self._writers:
            self._writers[key] = SourceLog(
                os.path.join(self.dir, f"{side}.{fmt}"), fmt, ts_interval_ms)
        return self._writers[key]

    def close(self) -> None:
        for w in self._writers.values():
            w.close()
        self._writers.clear()


class Bridge:
    """连接数据源 M 与 W: M 收到的数据发给 W, 反之亦然."""

    def __init__(
        self,
        src_m: DataSource,
        src_w: DataSource,
        log_m: Optional[SourceLog] = None,
        log_w: Optional[SourceLog] = None,
        on_event: Optional[Callable[[str], None]] = None,
        on_preview: Optional[Callable[[str, bytes], None]] = None,
    ) -> None:
        self.m = src_m
        self.w = src_w
        self.log_m = log_m
        self.log_w = log_w
        self.on_event = on_event
        self.on_preview = on_preview
        self.stats_m2w = TrafficStats()
        self.stats_w2m = TrafficStats()
        self.running = False

    def _event(self, msg: str) -> None:
        if self.on_event:
            self.on_event(msg)

    def _make_relay(self, src: DataSource, dst: DataSource,
                    stats: TrafficStats, direction: str,
                    log: Optional[SourceLog]):
        def on_data(data: bytes) -> None:
            stats.add(len(data))
            if log:
                try:
                    log.log(data)
                except Exception as exc:
                    self._event(f"记录失败: {exc}")
            if self.on_preview:
                self.on_preview(direction, data)
            try:
                dst.send(data)
            except Exception as exc:
                self._event(f"{direction} 转发失败: {exc}")

        src.set_callbacks(on_data=on_data,
                          on_error=lambda msg: self._event(msg),
                          on_state=lambda msg: self._event(msg))

    def start(self) -> None:
        """开始双向转发 (要求两个源均已 open)."""
        if self.running:
            return
        self._make_relay(self.m, self.w, self.stats_m2w, "M→W", self.log_m)
        self._make_relay(self.w, self.m, self.stats_w2m, "W→M", self.log_w)
        self.m.start()
        self.w.start()
        self.running = True
        self._event("转发已开始")

    def stop(self) -> None:
        """停止转发 (数据源保持打开)."""
        if not self.running:
            return
        self.m.stop_read()
        self.w.stop_read()
        self.running = False
        self._event("转发已停止")
