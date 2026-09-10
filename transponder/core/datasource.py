"""数据源抽象基类.

所有数据源 (串口/网络/文件) 统一实现该接口:
- open()/close()   打开与关闭
- start(on_data)/stop_read()  启停读取线程, 收到数据后通过 on_data 回调交给转发桥
- send(data)       线程安全的发送 (由另一端数据源的读取线程调用)

回调约定 (均在读取线程中调用, 使用方需自行保证线程安全):
- on_data(data: bytes)          收到数据
- on_error(msg: str)            发生错误 (随后源会自动关闭读取)
- on_state(desc: str)           状态变化提示 (如 "客户端已接入")
- on_peers()                    对端列表发生变化 (多对端源: TCP服务端/组播/广播)
- on_progress(done, total)      进度变化 (文件发送源: 已发送/总字节)

对端协议 (仅 TCP服务端/组播/广播 等多对端源有意义):
- peers: list[Peer]  只读视图, Peer 含 addr("ip:port")/rx_bytes/alive
- primary_peer: str|None  主要对端地址; None 表示"全部"模式
- set_primary_peer(addr|None)  运行中可切换
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Peer:
    """一个对端的描述信息."""

    addr: str                 # "ip:port" 展示形式
    rx_bytes: int = 0         # 从该对端累计收到的字节数
    alive: bool = True        # TCP: 连接是否仍存活; UDP类: 是否仍活跃
    seq: int = 0              # 接入序号(按连接顺序自增, 断开不回收)


class DataSource:
    """数据源基类: 子类只需实现 _open/_close/_read_once/_write 即可."""

    name = "数据源"

    def __init__(self) -> None:
        self._on_data: Optional[Callable[[bytes], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._on_state: Optional[Callable[[str], None]] = None
        self._on_peers: Optional[Callable[[], None]] = None
        self._on_progress: Optional[Callable[[int, int], None]] = None
        self._reader: Optional[threading.Thread] = None
        self._read_stop = threading.Event()
        self._send_lock = threading.Lock()
        self.opened = False
        # 对端列表 (单对端源为空即可)
        self._peers: list[Peer] = []
        self._peer_lock = threading.Lock()
        self._peer_seq = 0  # 对端接入序号, 自增不回收
        self.primary_peer: Optional[str] = None
        self.desired_primary: Optional[str] = None  # 期望主要对端, 该对端出现时自动生效

    # ---- 回调注入 -----------------------------------------------------
    def set_callbacks(
        self,
        on_data: Optional[Callable[[bytes], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_state: Optional[Callable[[str], None]] = None,
        on_peers: Optional[Callable[[], None]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        if on_data:
            self._on_data = on_data
        if on_error:
            self._on_error = on_error
        if on_state:
            self._on_state = on_state
        if on_peers:
            self._on_peers = on_peers
        if on_progress:
            self._on_progress = on_progress

    def _emit_state(self, desc: str) -> None:
        if self._on_state:
            self._on_state(desc)

    def _emit_error(self, msg: str) -> None:
        if self._on_error:
            self._on_error(msg)

    def _emit_peers(self) -> None:
        if self._on_peers:
            self._on_peers()

    def _emit_progress(self, done: int, total: int) -> None:
        if self._on_progress:
            self._on_progress(done, total)

    # ---- 对端管理 (多对端源使用; 单对端源保持默认空实现) ---------------
    @property
    def supports_peers(self) -> bool:
        return False

    def peers(self) -> list[Peer]:
        with self._peer_lock:
            return sorted(self._peers, key=lambda p: p.seq)

    def _add_peer(self, addr: str) -> Peer:
        with self._peer_lock:
            for p in self._peers:
                if p.addr == addr:
                    return p
            self._peer_seq += 1
            p = Peer(addr=addr, seq=self._peer_seq)
            self._peers.append(p)
            return p

    def _remove_peer(self, addr: str) -> None:
        with self._peer_lock:
            self._peers = [p for p in self._peers if p.addr != addr]

    def _touch_peer(self, addr: str, nbytes: int) -> None:
        p = self._add_peer(addr)
        with self._peer_lock:
            p.rx_bytes += nbytes
            p.alive = True
        self._apply_desired(addr)

    def _apply_desired(self, addr: str) -> None:
        """期望主要对端出现时自动生效 (多对端源在配置中预置)."""
        if self.desired_primary and addr == self.desired_primary:
            self.primary_peer = addr
            self.desired_primary = None
            self._emit_state(f"主要对端: {addr}")
            self._emit_peers()

    def set_primary_peer(self, addr: Optional[str]) -> None:
        """选择主要对端; None 恢复"全部"模式. 多对端源实现."""
        if self.supports_peers and addr is not None and not any(
                p.addr == addr for p in self.peers()):
            raise ValueError(f"对端 {addr} 不在列表中")
        self.primary_peer = addr
        self._emit_state(f"主要对端: {addr or '全部'}")
        self._emit_peers()

    # ---- 生命周期 -----------------------------------------------------
    def open(self) -> None:
        """打开数据源, 失败抛出异常."""
        if self.opened:
            return
        self._open()
        self.opened = True
        self._emit_state(f"{self.name} 已打开")

    def close(self) -> None:
        """关闭数据源 (同时停止读取线程)."""
        self.stop_read()
        if not self.opened:
            return
        try:
            self._close()
        finally:
            self.opened = False

    # ---- 读取 ---------------------------------------------------------
    def start(self) -> None:
        """启动读取线程."""
        if self._reader and self._reader.is_alive():
            return
        self._read_stop.clear()
        self._reader = threading.Thread(
            target=self._read_loop, name=f"read-{self.name}", daemon=True
        )
        self._reader.start()

    def stop_read(self) -> None:
        self._read_stop.set()
        reader = self._reader
        if reader and reader.is_alive() and reader is not threading.current_thread():
            reader.join(timeout=2.0)
        self._reader = None

    def _read_loop(self) -> None:
        """读取循环: 阻塞式读取, 出错或停止时退出."""
        while not self._read_stop.is_set():
            try:
                data = self._read_once()
            except StopRead:
                break
            except Exception as exc:  # 读取出错: 通知并退出读取线程
                if not self._read_stop.is_set():
                    self._emit_error(f"{self.name} 读取错误: {exc}")
                break
            if data:
                if self._on_data:
                    self._on_data(data)

    # ---- 发送 ---------------------------------------------------------
    def send(self, data: bytes) -> int:
        """线程安全发送, 返回发送字节数 (失败抛异常, 由转发桥捕获)."""
        with self._send_lock:
            if not self.opened:
                raise IOError(f"{self.name} 未打开")
            return self._write(data)

    # ---- 子类实现 -----------------------------------------------------
    def _open(self) -> None:
        raise NotImplementedError

    def _close(self) -> None:
        raise NotImplementedError

    def _read_once(self) -> Optional[bytes]:
        """阻塞读取一批数据; 返回 None/空表示本次无数据; 抛 StopRead 表示读完毕(如文件EOF)."""
        raise NotImplementedError

    def _write(self, data: bytes) -> int:
        raise NotImplementedError

    @property
    def direction(self) -> str:
        """显示用: 该源的可读写方向."""
        return "读写"


class StopRead(Exception):
    """读取端正常结束 (文件EOF等), 读取线程应退出."""
