"""
编码/解码工具 — 纯函数，无状态。

"string" → UTF-8 文本
"bytes"  → float32 小端 4 字节
"""

import struct


def encode(value, fmt: str = "string") -> bytes:
    """将 Python 值按格式编码为字节串。

    Args:
        value:  数字或字符串
        fmt:    "string" → str(value).encode("utf-8")
                "bytes"  → struct.pack("<f", float(value))

    Returns:
        编码后的字节串。非法 value 时静默回退为 0.0 / 空串。
    """
    if fmt == "bytes":
        try:
            return struct.pack("<f", float(value))
        except (TypeError, ValueError, struct.error):
            return struct.pack("<f", 0.0)
    else:
        return str(value).encode("utf-8")


def decode(data: bytes, fmt: str = "bytes"):
    """将字节串按格式解码为 Python 值。

    Args:
        data:  原始字节
        fmt:   "bytes"  → struct.unpack("<f", data[:4])[0]
               "string" → data.decode("utf-8")

    Returns:
        解码后的值。数据不足或格式错误时返回 None。
    """
    if fmt == "bytes":
        if len(data) < 4:
            return None
        try:
            return struct.unpack("<f", data[:4])[0]
        except struct.error:
            return None
    else:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None
