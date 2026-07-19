"""SerialParallelDevice — 串口连接生命周期管理。"""

from __future__ import annotations

from . import state


def port_key(port: str, baud: int) -> str:
    """生成串口连接的唯一标识键。"""
    return f"{port}:{baud}"


def get_or_open_serial(key: str, port: str, baud: int):
    """获取或打开串口。返回 pyserial.Serial 或 None。"""
    with state._lock:
        ser = state._ports.get(key)
        if ser is not None:
            try:
                if ser.is_open:
                    return ser
            except Exception:
                pass
            state._ports.pop(key, None)

        try:
            import serial
            ser = serial.Serial(port, baud, timeout=0.1)
            state._ports[key] = ser
            print(f"{state._TAG} Opened {key}")
            return ser
        except Exception as e:
            print(f"{state._TAG} Failed to open {key}: {e}")
            return None


def close_port(key: str) -> None:
    """关闭并移除单个端口。"""
    with state._lock:
        ser = state._ports.pop(key, None)
        if ser is not None:
            try:
                ser.close()
                print(f"{state._TAG} Closed {key}")
            except Exception as e:
                print(f"{state._TAG} Error closing {key}: {e}")


def close_all() -> None:
    """关闭所有端口。"""
    with state._lock:
        for key in list(state._ports.keys()):
            ser = state._ports.pop(key, None)
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass
    state._ports.clear()
