"""文件数据源 (只读发送 / 只写接收, 不支持同时读写)."""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

from .datasource import DataSource, StopRead


class FileSendSource(DataSource):
    """文件发送源: 按可选限速读取文件并发送, 读完即止; 提供进度回调.

    rate_bps=None 表示不限速; 否则为每秒字节数上限.
    """

    name = "文件(读)"

    READ_CHUNK = 4096

    def __init__(self, path: str, rate_bps: Optional[int] = None) -> None:
        super().__init__()
        self.path = path
        self.rate_bps = rate_bps
        self._f = None
        self._total = 0
        self._sent = 0

    def _open(self) -> None:
        self._f = open(self.path, "rb")
        self._f.seek(0, os.SEEK_END)
        self._total = self._f.tell()
        self._f.seek(0)
        self._sent = 0

    def _close(self) -> None:
        if self._f:
            self._f.close()
            self._f = None

    def _read_once(self) -> Optional[bytes]:
        if self._f is None:
            raise IOError("文件未打开")
        if self.rate_bps:  # 限速: 每 0.1s 读 rate/10 字节, 保证粒度足够细
            chunk = max(1, self.rate_bps // 10)
            data = self._f.read(min(chunk, self.READ_CHUNK))
            time.sleep(0.1)
        else:
            data = self._f.read(self.READ_CHUNK)
        if not data:
            self._emit_progress(self._total, self._total)
            self._emit_state("文件已读完, 该方向转发结束")
            raise StopRead
        self._sent += len(data)
        self._emit_progress(self._sent, self._total)
        return data

    def _write(self, data: bytes) -> int:
        raise IOError("文件(读)源不支持写入")

    @property
    def direction(self) -> str:
        return "只读"


class FileRecvSource(DataSource):
    """文件接收源: 把对端发来的数据写入文件, 不提供读取."""

    name = "文件(写)"

    def __init__(self, path: str, append: bool = False) -> None:
        super().__init__()
        self.path = path
        self.append = append
        self._f = None
        self._lock = threading.Lock()

    def _open(self) -> None:
        self._f = open(self.path, "ab" if self.append else "wb")

    def _close(self) -> None:
        with self._lock:
            if self._f:
                self._f.close()
                self._f = None

    def _read_once(self) -> Optional[bytes]:
        raise StopRead  # 接收源不读取

    def _write(self, data: bytes) -> int:
        with self._lock:
            if self._f is None:
                raise IOError("文件未打开")
            self._f.write(data)
            self._f.flush()
            return len(data)

    @property
    def direction(self) -> str:
        return "只写"
