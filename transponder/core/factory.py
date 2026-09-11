"""数据源工厂: 从 "type:key=value,..." 形式的规格字符串构造数据源.

规格示例:
    serial:port=COM3,baud=115200,data=8,parity=N,stop=1
    file-send:path=data.bin,b=500,kb=20,mb=0     # 限速=b+1024*kb+1024*mb B/s, 全0=不限速
    file-recv:path=out.bin,append=0
    tcp-client:host=192.168.1.10,port=9000,local_host=,local_port=0
    tcp-server:host=0.0.0.0,port=9000,backlog=0,primary=192.168.1.5:40001
    udp:host=0.0.0.0,port=9000,peer=192.168.1.9:9001     # peer 可省略(自动锁定首个来源)
    multicast:group=239.1.1.1,port=5000,ttl=1
    broadcast:addr=192.168.10.255,port=5000,local_host=0.0.0.0,local_port=0
"""

from __future__ import annotations

from .datasource import DataSource
from .serial_source import SerialSource
from .file_source import FileSendSource, FileRecvSource
from .net_source import (
    TcpClientSource, TcpServerSource, UdpUnicastSource,
    MulticastSource, BroadcastSource,
    is_valid_multicast,
)

_PARITY = {"N": "无", "E": "偶", "O": "奇"}


def _split_spec(spec: str) -> tuple[str, dict[str, str]]:
    spec = spec.strip()
    stype, _, kv_str = spec.partition(":")
    kv: dict[str, str] = {}
    for part in kv_str.split(","):
        part = part.strip()
        if not part:
            continue
        k, _, v = part.partition("=")
        kv[k.strip()] = v.strip()
    return stype, kv


def _need(kv: dict, stype: str, key: str) -> str:
    if key not in kv:
        raise ValueError(f"{stype} 缺少参数 {key}")
    return kv[key]


def _opt(kv: dict, key: str, default: str) -> str:
    return kv.get(key, default)


def _peer(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    if not host or not port.isdigit():
        raise ValueError(f"对端格式应为 ip:port, 得到 {value}")
    return host, int(port)


def parse_spec(spec: str) -> DataSource:
    """解析规格字符串并构造数据源实例, 非法时抛 ValueError."""
    stype, kv = _split_spec(spec)

    if stype == "serial":
        return SerialSource(
            port=_need(kv, stype, "port"),
            baudrate=int(_opt(kv, "baud", "115200")),
            bytesize=int(_opt(kv, "data", "8")),
            parity=_PARITY[_opt(kv, "parity", "N").upper()],
            stopbits=int(_opt(kv, "stop", "1")),
            flowctrl={"none": "无", "rtscts": "RTS/CTS"}.get(
                _opt(kv, "flow", "none").lower(), "无"),
        )
    if stype == "file-send":
        rate = (int(_opt(kv, "b", "0")) + 1024 * int(_opt(kv, "kb", "0"))
                + 1024 * 1024 * int(_opt(kv, "mb", "0")))
        return FileSendSource(_need(kv, stype, "path"), rate_bps=rate or None)
    if stype == "file-recv":
        return FileRecvSource(_need(kv, stype, "path"),
                              append=_opt(kv, "append", "0") == "1")
    if stype == "tcp-client":
        return TcpClientSource(
            _need(kv, stype, "host"), int(_need(kv, stype, "port")),
            local_host=_opt(kv, "local_host", ""),
            local_port=int(_opt(kv, "local_port", "0")),
        )
    if stype == "tcp-server":
        src = TcpServerSource(
            _opt(kv, "host", "0.0.0.0"), int(_need(kv, stype, "port")),
            backlog=int(_opt(kv, "backlog", "0")),
        )
        if "primary" in kv:
            # 对端尚未接入, 记为"期望主要对端", 该对端出现时自动生效
            src.desired_primary = _opt(kv, "primary", "")
        return src
    if stype == "udp":
        peer_host = peer_port = ""
        if kv.get("peer"):
            peer_host, peer_port = _peer(kv["peer"])
            peer_port = str(peer_port)
        return UdpUnicastSource(
            bind_host=_opt(kv, "host", "0.0.0.0"), bind_port=int(_opt(kv, "port", "0")),
            peer_host=peer_host, peer_port=int(peer_port or 0),
        )
    if stype == "multicast":
        group = _need(kv, stype, "group")
        if not is_valid_multicast(group):
            raise ValueError(f"无效的组播地址: {group} (有效范围 224.0.0.0/4)")
        return MulticastSource(group, int(_need(kv, stype, "port")),
                               local_ip=_opt(kv, "local_host", "0.0.0.0"),
                               ttl=int(_opt(kv, "ttl", "1")))
    if stype == "broadcast":
        return BroadcastSource(
            addr=_opt(kv, "addr", "255.255.255.255"),
            port=int(_need(kv, stype, "port")),
            local_host=_opt(kv, "local_host", "0.0.0.0"),
            local_port=int(_opt(kv, "local_port", "0")),
        )
    raise ValueError(f"未知数据源类型: {stype}")


def parse_primary(spec: str) -> str | None:
    """从规格串中取出 primary 参数 (供 CLI/GUI 在打开后设置主要对端)."""
    _, kv = _split_spec(spec)
    return kv.get("primary") or None
