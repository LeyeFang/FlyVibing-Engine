"""
编码/解码工具 — 纯函数，无状态。

"string" → UTF-8 文本行（可选 prefix/suffix: `prefix + 最短数字 + suffix + "\\n"`）
"bytes"  → float32 小端 4 字节
"byte"   → uint8 单字节 (1–255, 0 为复位保留)
"""

import struct


def format_scalar(value) -> str:
    """数字 → 最短十进制文本 — 串口**行协议**用（`14` 而不是 `14.0`）。

    14.0 / "14.0" → "14"; 14.5 → "14.5"; 0.1+0.2 → "0.3"（6 位有效数字）;
    非数字 → str(value) 原样; nan/inf 原样输出（调用方应自行校验）。
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num != num or num in (float("inf"), float("-inf")):
        return str(num)
    if num.is_integer():
        return str(int(num))
    return f"{num:.6g}"


def _check_affix(fmt: str, prefix: str, suffix: str) -> None:
    """prefix/suffix 只对文本行成立（其他格式显式报错 — 禁止静默忽略）。"""
    if not prefix and not suffix:
        return
    if fmt != "string":
        raise ValueError(
            f"prefix/suffix apply to text lines only (fmt={fmt!r}) — use fmt='string'")
    for name, text in (("prefix", prefix), ("suffix", suffix)):
        if "\n" in text or "\r" in text:
            raise ValueError(
                f"{name} must not contain CR/LF: one SerialSend call = one line "
                f"(got {text!r})")


def encode(value, fmt: str = "string", *, prefix: str = "",
           suffix: str = "") -> bytes:
    """将 Python 值按格式编码为字节串。

    Args:
        value:  数字或字符串
        fmt:    "string" → UTF-8 文本 + "\\n"（可带 prefix/suffix, 见下）
                "bytes"  → struct.pack("<f", float(value)) — float32 小端 4 字节
                "byte"   → struct.pack("<B", 1..255) — uint8 单字节（0 为复位保留,
                           复位由 I/O 线程自动写入, 不经本函数）
        prefix: 文本行前缀, 如 `"40,"` — **行协议头**（刺激器 `f,code` 的重复率）
        suffix: 文本行后缀（换行符由本函数统一追加，不要写进 prefix/suffix）

    prefix/suffix 非空时值用 `format_scalar()` 格式化（`40,14` 而不是 `40,14.0`）;
    两者都为空时与旧版完全一致（`str(value)`）—— 现有场景行为不变。

    Raises:
        ValueError — prefix/suffix 与 fmt 冲突，或含 CR/LF。

    Returns:
        编码后的字节串。bytes/byte 的非法 value 静默回退为 0.0 / 1。
    """
    _check_affix(fmt, prefix, suffix)
    if fmt == "bytes":
        try:
            return struct.pack("<f", float(value))
        except (TypeError, ValueError, struct.error):
            return struct.pack("<f", 0.0)
    elif fmt == "byte":
        try:
            v = max(1, min(255, int(float(value))))
            return struct.pack("<B", v)
        except (TypeError, ValueError, struct.error):
            return struct.pack("<B", 1)
    else:
        # string 格式: 标准化追加 "\n" 换行符 (避免尾部重复)
        if prefix or suffix:
            s = f"{prefix}{format_scalar(value)}{suffix}"
        else:
            s = str(value)          # 旧行为: 场景里算出的 14.0 原样发出
        if not s.endswith("\n"):
            s += "\n"
        return s.encode("utf-8")


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
