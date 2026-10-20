"""SerialParallelDevice — 串口连接生命周期管理。"""

from __future__ import annotations

from . import state


def port_key(port: str, baud: int) -> str:
    """生成串口连接的唯一标识键。"""
    return f"{port}:{baud}"


def resolve_port(port: str) -> str:
    """把物理端口直写或逻辑设备名（`@mibox`）解析为**物理端口**。

    协议: `Doc/Dev/device_io_protocol.md` §10（两级设备身份）。
      - `"COM5"`        → 原样返回（兼容旧场景的物理直写）;
      - `"@mibox"`      → 查机器侧注册表（`Application.Core.DeviceRegistry`）;
      - 未绑定/缺 port  → 抛 `DeviceUnresolved`（**绝不静默回退** —— 静默发错端口比报错更糟）;
      - `""`            → 抛 `ValueError`（未配置端口）。
    """
    text = str(port or "").strip()
    if not text:
        raise ValueError("serial port is empty — configure the node/panel port or a @device name")
    from Application.Core.DeviceRegistry import is_ref, resolve
    if not is_ref(text):
        return text
    entry = resolve(text)                      # 未绑定 → DeviceUnresolved（可操作提示）
    physical = str(entry.get("port") or "").strip()
    if not physical:
        from Application.Core.DeviceRegistry import DeviceUnresolved
        raise DeviceUnresolved(
            f"device '{text}' is bound but has no 'port' field — rebind it "
            f"(ext.device.bind_alias name={text[1:]} port=COMx)")
    return physical


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
