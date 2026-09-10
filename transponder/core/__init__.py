"""核心转发引擎: 数据源抽象 + 各实现 + 转发桥."""

from .datasource import DataSource, StopRead, Peer
from .serial_source import SerialSource, scan_serial_ports
from .file_source import FileSendSource, FileRecvSource
from .net_source import (
    TcpClientSource, TcpServerSource, UdpUnicastSource,
    MulticastSource, BroadcastSource,
    scan_local_addresses, scan_broadcast_addresses, addr_in_use,
    is_valid_multicast,
)
from .bridge import Bridge, TrafficStats, SourceLog, LogSession
from .factory import parse_spec, parse_primary

__all__ = [
    "DataSource", "StopRead", "Peer",
    "SerialSource", "scan_serial_ports",
    "FileSendSource", "FileRecvSource",
    "TcpClientSource", "TcpServerSource", "UdpUnicastSource",
    "MulticastSource", "BroadcastSource",
    "scan_local_addresses", "scan_broadcast_addresses", "addr_in_use",
    "is_valid_multicast",
    "Bridge", "TrafficStats", "SourceLog", "LogSession",
    "parse_spec", "parse_primary",
]
