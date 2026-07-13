"""
SerialDevice — 串口通信模块。

提供串口连接的打开 / 关闭 / 写入操作。
被 node_editor IO 节点 (SerialSend) 和 Runtime 层使用。
"""

from __future__ import annotations

import threading
from typing import Optional


_serial_lock = threading.Lock()
_connections: dict[str, object] = {}  # key → pyserial.Serial


def open_serial(port: str, baud: int = 9600, timeout: float = 0.1) -> Optional[object]:
    """打开串口连接（线程安全）。返回 pyserial.Serial 实例或 None。"""
    key = f"{port}:{baud}"
    with _serial_lock:
        if key in _connections:
            ser = _connections[key]
            try:
                if ser.is_open:
                    return ser
            except Exception:
                pass
            del _connections[key]

        try:
            import serial
            ser = serial.Serial(port, baud, timeout=timeout)
            _connections[key] = ser
            return ser
        except Exception as e:
            print(f"[SerialDevice] Failed to open {port}@{baud}: {e}")
            return None


def close_serial(port: str, baud: int = 9600) -> None:
    """关闭串口连接。"""
    key = f"{port}:{baud}"
    with _serial_lock:
        ser = _connections.pop(key, None)
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass


def write_serial(port: str, baud: int, data: bytes) -> bool:
    """向串口写入数据。返回是否成功。"""
    ser = open_serial(port, baud)
    if ser is None:
        return False
    try:
        ser.write(data)
        return True
    except Exception as e:
        print(f"[SerialDevice] Write error on {port}@{baud}: {e}")
        return False


def close_all() -> None:
    """关闭所有已打开的串口连接。"""
    with _serial_lock:
        for key, ser in list(_connections.items()):
            try:
                ser.close()
            except Exception:
                pass
        _connections.clear()
