"""串口数据源."""

from __future__ import annotations

from typing import Optional

import serial
from serial.tools import list_ports

from .datasource import DataSource

_PARITY = {"无": serial.PARITY_NONE, "偶": serial.PARITY_EVEN, "奇": serial.PARITY_ODD}
_STOPBITS = {"1": serial.STOPBITS_ONE, "2": serial.STOPBITS_TWO}


def scan_serial_ports() -> list[dict]:
    """扫描所有串口, 返回 [{port, desc, busy}], busy=被其他程序占用."""
    result = []
    for p in list_ports.comports():
        busy = False
        try:
            s = serial.Serial(p.device)
            s.close()
        except Exception:
            busy = True
        result.append({"port": p.device, "desc": p.description, "busy": busy})
    return result


class SerialSource(DataSource):
    name = "串口"

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        bytesize: int = 8,
        parity: str = "无",
        stopbits: int = 1,
        flowctrl: str = "无",
    ) -> None:
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.flowctrl = flowctrl
        self._ser: Optional[serial.Serial] = None

    def _open(self) -> None:
        self._ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=self.bytesize,
            parity=_PARITY[self.parity],
            stopbits=_STOPBITS[str(self.stopbits)],
            rtscts=(self.flowctrl == "RTS/CTS"),
            timeout=0.2,  # 短超时轮询, 便于响应停止
        )

    def _close(self) -> None:
        if self._ser:
            self._ser.close()
            self._ser = None

    def _read_once(self) -> Optional[bytes]:
        if self._ser is None:
            raise IOError("串口未打开")
        n = self._ser.in_waiting
        if n:
            return self._ser.read(n)
        # 无数据时阻塞一个 timeout 周期
        return self._ser.read(1)

    def _write(self, data: bytes) -> int:
        if self._ser is None:
            raise IOError("串口未打开")
        return self._ser.write(data)
