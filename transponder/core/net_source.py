"""网络数据源: TCP 客户端/服务端, UDP单播, 组播, 广播; 以及地址扫描辅助."""

from __future__ import annotations

import ipaddress
import re
import socket
import struct
import subprocess
import sys
import threading
from typing import Optional, Tuple

from .datasource import DataSource, Peer, StopRead

ADDR = Tuple[str, int]


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def scan_local_addresses() -> list[str]:
    """本机 IPv4 地址列表 (供绑定地址下拉框), 固定包含 0.0.0.0 与 127.0.0.1."""
    ips = ["0.0.0.0", "127.0.0.1"]
    try:  # 连接外部地址后查本地出口 (UDP 无连接, 不会真正发包)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ips:
            ips.append(ip)
    except OSError:
        pass
    for ip in _iface_infos():
        if ip.address not in ips:
            ips.append(ip.address)
    return ips


def scan_broadcast_addresses() -> list[str]:
    """各网卡的广播地址 (供广播地址下拉框), 如 192.168.10.255 / 127.255.255.255."""
    result = ["255.255.255.255"]
    for info in _iface_infos():
        bcast = info.broadcast
        if bcast and bcast not in result:
            result.append(bcast)
    return result


class IfaceInfo:
    __slots__ = ("address", "netmask", "broadcast")

    def __init__(self, address, netmask, broadcast):
        self.address = address
        self.netmask = netmask
        self.broadcast = broadcast


def _iface_infos() -> list[IfaceInfo]:
    """枚举网卡 IPv4 信息 (地址/掩码/广播), psutil 优先, 失败时回退解析命令行输出."""
    infos: list[IfaceInfo] = []
    try:
        import psutil
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family == socket.AF_INET and a.address:
                    infos.append(IfaceInfo(
                        a.address, a.netmask,
                        a.broadcast if a.broadcast else _calc_bcast(a.address, a.netmask)))
        if infos:
            return infos
    except Exception:
        pass
    # 回退: 解析 ip / ipconfig 输出 (仅地址, 无掩码则无广播地址)
    try:
        cmd = ["ipconfig"] if _is_windows() else ["ip", "-4", "addr"]
        out = subprocess.run(cmd, capture_output=True, timeout=3
                             ).stdout.decode(errors="replace")
        for m in re.finditer(r"(\d+\.\d+\.\d+\.\d+)[^\n]*?(\d+\.\d+\.\d+\.\d+)?", out):
            ip = m.group(1)
            if not ip.startswith("127."):
                infos.append(IfaceInfo(ip, None, None))
    except Exception:
        pass
    return infos


def _calc_bcast(addr: str, netmask: Optional[str]) -> Optional[str]:
    """由 地址+掩码 计算广播地址: 网络号 | 掩码取反."""
    try:
        if not addr or not netmask:
            return None
        ip_int = int(ipaddress.IPv4Address(addr))
        mask_int = int(ipaddress.IPv4Address(netmask))
        bcast_int = (ip_int & mask_int) | (~mask_int & 0xFFFFFFFF)
        return str(ipaddress.IPv4Address(bcast_int))
    except Exception:
        return None


def addr_in_use(host: str, port: int) -> bool:
    """检测 TCP 绑定地址是否已被占用."""
    try:
        s = socket.create_server((host, port))
        s.close()
        return False
    except OSError:
        return True


def is_valid_multicast(addr: str) -> bool:
    """是否为有效组播地址 (224.0.0.0/4)."""
    try:
        ip = ipaddress.IPv4Address(addr.strip())
        return ip.is_multicast
    except Exception:
        return False


def _fmt(addr: ADDR) -> str:
    return f"{addr[0]}:{addr[1]}"


class TcpClientSource(DataSource):
    """TCP 客户端: 主动连接远程服务端; 本地 IP:PORT 可自动分配或手动绑定."""

    name = "TCP客户端"

    CONNECT_TIMEOUT = 5.0

    def __init__(self, host: str, port: int,
                 local_host: str = "", local_port: int = 0) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.local_host = local_host  # 空 = 系统自动选择
        self.local_port = local_port  # 0 = 系统自动分配
        self._sock: Optional[socket.socket] = None

    def _open(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if self.local_host or self.local_port:
            self._sock.bind((self.local_host or "0.0.0.0", self.local_port))
            self._emit_state(f"本地绑定 {_fmt(self._sock.getsockname())}")
        self._sock.settimeout(self.CONNECT_TIMEOUT)
        self._sock.connect((self.host, self.port))
        self._sock.settimeout(0.2)
        self._emit_state(f"已连接 {self.host}:{self.port}, 本地 {_fmt(self._sock.getsockname())}")

    def _close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _read_once(self) -> Optional[bytes]:
        if self._sock is None:
            raise IOError("未连接")
        try:
            return self._sock.recv(4096)
        except socket.timeout:
            return None

    def _write(self, data: bytes) -> int:
        if self._sock is None:
            raise IOError("未连接")
        return self._sock.sendall(data) or len(data)


class TcpServerSource(DataSource):
    """TCP 服务端.

    - 所有接入的客户端保持连接并进入对端列表
    - 选定主要对端: 仅与其点对点 (收发都只针对它)
    - 未选主要对端: 发送扇出给所有客户端, 接收所有客户端的数据
    - 主要对端断开: 自动清空选择恢复"全部"模式并提示
    """

    name = "TCP服务端"

    def __init__(self, host: str, port: int, backlog: int = 0) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.backlog = backlog  # 0 = 系统默认
        self._listen: Optional[socket.socket] = None
        self._clients: dict[str, socket.socket] = {}  # addr -> conn
        self._clients_lock = threading.Lock()
        self._accept_thread: Optional[threading.Thread] = None
        self._closing = threading.Event()  # 不用 self.opened 判断: 它在 open() 尾部才置位, 线程启动时有竞态
        self._has_client = threading.Event()

    @property
    def supports_peers(self) -> bool:
        return True

    def _open(self) -> None:
        self._closing.clear()
        self._listen = socket.create_server(
            (self.host, self.port), backlog=self.backlog or 5)
        self._listen.settimeout(0.2)
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="tcp-accept", daemon=True)
        self._accept_thread.start()
        self._emit_state(f"监听 {self.host}:{self.port}, 等待客户端接入")

    def _wait_first_client(self) -> None:
        if any(self._clients):
            return
        self._emit_state("等待客户端接入后再发送...")
        while not self._closing.is_set():
            with self._clients_lock:
                if self._clients:
                    return
            if not self._has_client.wait(0.5):
                continue
            with self._clients_lock:
                if self._clients:
                    return

    def _accept_loop(self) -> None:
        while not self._closing.is_set() and self._listen is not None:
            try:
                conn, addr = self._listen.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            key = _fmt(addr)
            conn.settimeout(0.2)
            with self._clients_lock:
                self._clients[key] = conn
            self._has_client.set()
            self._add_peer(key)
            self._apply_desired(key)
            self._emit_state(f"客户端 {key} 已接入")
            self._emit_peers()
            threading.Thread(target=self._client_loop, args=(conn, key),
                             name=f"tcp-read-{key}", daemon=True).start()

    def _client_loop(self, conn: socket.socket, key: str) -> None:
        """单客户端读取线程."""
        while not self._closing.is_set() and not self._read_stop.is_set():
            try:
                data = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            # 主要对端模式下, 非主要对端的数据不转发
            if self.primary_peer and key != self.primary_peer:
                continue
            self._touch_peer(key, len(data))
            if self._on_data:
                self._on_data(data)
        self._drop_client(key)

    def _drop_client(self, key: str) -> None:
        with self._clients_lock:
            conn = self._clients.pop(key, None)
            if not self._clients:
                self._has_client.clear()
        if conn:
            try:
                conn.close()
            except OSError:
                pass
        self._remove_peer(key)
        if self.primary_peer == key:
            self.primary_peer = None
            self._emit_state(f"主要对端 {key} 已断开, 恢复全部接收模式")
        else:
            self._emit_state(f"客户端 {key} 已断开")
        self._emit_peers()

    def _read_once(self) -> Optional[bytes]:
        raise StopRead  # 数据由每客户端线程直接产出, 不使用通用读取循环

    def _write(self, data: bytes) -> int:
        # 无客户端时阻塞等待, 避免转发启动早期数据被丢弃 (与文件源配合)
        self._wait_first_client()
        with self._clients_lock:
            targets = dict(self._clients)
        if not targets:
            raise IOError("无已连接的客户端")
        if self.primary_peer:
            conn = targets.get(self.primary_peer)
            if conn is None:
                raise IOError(f"主要对端 {self.primary_peer} 已断开")
            conn.sendall(data)
            return len(data)
        # 全部模式: 扇出给所有客户端, 单个失败仅丢弃该客户端
        for key, conn in targets.items():
            try:
                conn.sendall(data)
            except OSError:
                self._drop_client(key)
        return len(data)

    def _close(self) -> None:
        self._closing.set()
        if self._listen:
            try:
                self._listen.close()
            except OSError:
                pass
            self._listen = None
        with self._clients_lock:
            conns = list(self._clients.values())
            self._clients.clear()
        for conn in conns:
            try:
                conn.close()
            except OSError:
                pass
        with self._peer_lock:
            self._peers.clear()


class UdpUnicastSource(DataSource):
    """UDP 单播 (点对点): 本地 IP:PORT 自动或手动; 对端可选.

    - 未指定对端: 收到第一帧数据后锁定其来源为对端
    - 指定对端: 发送发给该对端, 且仅接收该对端的数据报
    """

    name = "UDP单播"

    def __init__(self, bind_host: str = "0.0.0.0", bind_port: int = 0,
                 peer_host: str = "", peer_port: int = 0) -> None:
        super().__init__()
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.peer_host = peer_host
        self.peer_port = peer_port
        self._sock: Optional[socket.socket] = None
        self._peer: Optional[ADDR] = None
        self._lock = threading.Lock()

    def _open(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((self.bind_host, self.bind_port))
        self._sock.settimeout(0.2)
        if self.peer_host and self.peer_port:
            self._peer = (self.peer_host, self.peer_port)
        local = self._sock.getsockname()
        self._emit_state(f"UDP 绑定 {local[0]}:{local[1]}"
                         + (f", 对端 {self.peer_host}:{self.peer_port}" if self._peer else ""))

    def _close(self) -> None:
        with self._lock:
            if self._sock:
                self._sock.close()
                self._sock = None

    @property
    def local_port(self) -> int:
        return self._sock.getsockname()[1] if self._sock else 0

    def _read_once(self) -> Optional[bytes]:
        if self._sock is None:
            raise IOError("未打开")
        try:
            data, addr = self._sock.recvfrom(65536)
        except socket.timeout:
            return None
        if self._peer is None:  # 未指定对端: 锁定第一帧来源
            self._peer = addr
            self._emit_state(f"对端锁定为 {_fmt(addr)}")
        elif addr != self._peer:  # 已指定对端: 仅接收该对端
            return None
        return data

    def _write(self, data: bytes) -> int:
        with self._lock:
            if self._sock is None:
                raise IOError("未打开")
            if self._peer is None:
                raise IOError("尚无对端 (未指定对端且未收到过对端数据)")
            self._sock.sendto(data, self._peer)
            return len(data)


class _UdpGroupBase(DataSource):
    """组播/广播公共: 单 socket 收发, 跟踪发送方地址形成对端列表."""

    name = "UDP组"

    def __init__(self) -> None:
        super().__init__()
        self._sock: Optional[socket.socket] = None
        self._target: ADDR = ("", 0)  # 发送目标 (组地址或广播地址:端口)
        self._lock = threading.Lock()

    @property
    def supports_peers(self) -> bool:
        return True

    def _read_once(self) -> Optional[bytes]:
        if self._sock is None:
            raise IOError("未打开")
        try:
            data, addr = self._sock.recvfrom(65536)
        except socket.timeout:
            return None
        key = _fmt(addr)
        # 主要对端模式: 只接收主要对端的数据
        if self.primary_peer and key != self.primary_peer:
            return None
        self._touch_peer(key, len(data))
        self._emit_peers()
        return data

    def _write(self, data: bytes) -> int:
        with self._lock:
            if self._sock is None:
                raise IOError("未打开")
            self._sock.sendto(data, self._target)
            return len(data)

    def _close(self) -> None:
        with self._lock:
            if self._sock:
                self._sock.close()
                self._sock = None
        with self._peer_lock:
            self._peers.clear()


class MulticastSource(_UdpGroupBase):
    """组播源: 加入组收发; 禁用 IP_MULTICAST_LOOP 避免收到自己发出的数据."""

    name = "组播"

    def __init__(self, group: str, port: int, ttl: int = 1) -> None:
        super().__init__()
        if not is_valid_multicast(group):
            raise ValueError(f"无效的组播地址: {group} (有效范围 224.0.0.0/4)")
        self.group = group
        self.port = port
        self.ttl = ttl

    def _open(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(0.2)
        # 允许多个组播监听者绑定同一端口 (跨进程/跨实例测试的前提)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.ttl)
        # 关闭组播回环: 自己发的组播数据不会回到自己的接收端
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
        mreq = struct.pack("4sl", socket.inet_aton(self.group), socket.INADDR_ANY)
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self._sock.bind(("0.0.0.0", self.port))
        self._target = (self.group, self.port)
        self._emit_state(f"已加入组播组 {self.group}:{self.port}")


class BroadcastSource(_UdpGroupBase):
    """广播源: 向指定广播地址发送, 接收任意来源; 本地端口自动或手动."""

    name = "广播"

    def __init__(self, addr: str = "255.255.255.255", port: int = 5000,
                 local_host: str = "0.0.0.0", local_port: int = 0) -> None:
        super().__init__()
        self.bcast_addr = addr
        self.port = port
        self.local_host = local_host
        self.local_port = local_port

    def _open(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(0.2)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.bind((self.local_host, self.local_port))
        self._target = (self.bcast_addr, self.port)
        local = self._sock.getsockname()
        self._emit_state(f"广播 {self.bcast_addr}:{self.port} (本地 {local[0]}:{local[1]})")
