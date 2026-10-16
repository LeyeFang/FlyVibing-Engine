"""
VirtualDevice.ServiceProtocol — 品牌服务进程 ↔ 引擎 的通信协议 (纯 stdlib)。

帧格式: [4 字节大端长度][pickle(protocol=4) 载荷]
消息形态:
  - 请求  {"cmd": "...", "rid": <int>, ...参数}
  - 响应  {"ok": bool, "rid": <int>, "detail": str, ...}
  - 推送  {"type": "block", "seq": <int>, "data": np.ndarray}   (push 模式数据流)

约定:
  - pickle protocol=4 固定 — 服务进程可能运行于更低的 Python (品牌自有环境);
  - 仅限本机受信通道 (localhost) — pickle 不做安全校验, 勿暴露到网络;
  - 所有发送经调用方 send_lock 串行化 (采集线程与控制响应可能并发写同一 socket)。
"""

from __future__ import annotations

import pickle
import socket
import struct

_FRAME = struct.Struct(">I")
MAX_FRAME_BYTES = 512 * 1024 * 1024      # 单帧上限 (防御损坏/非法长度)
PICKLE_PROTOCOL = 4                       # 跨版本兼容 (3.9+)


def pack_message(obj) -> bytes:
    """pickle + 长度前缀成帧。"""
    payload = pickle.dumps(obj, protocol=PICKLE_PROTOCOL)
    return _FRAME.pack(len(payload)) + payload


def send_message(sock: socket.socket, obj, lock=None) -> None:
    """发送一条消息 (并发写需传 lock — 采集线程/控制线程)。"""
    frame = pack_message(obj)
    if lock is None:
        sock.sendall(frame)
    else:
        with lock:
            sock.sendall(frame)


def recv_exact(sock: socket.socket, n: int):
    """读满 n 字节; 连接正常关闭返回 None。"""
    chunks = bytearray()
    while len(chunks) < n:
        chunk = sock.recv(n - len(chunks))
        if not chunk:
            return None
        chunks.extend(chunk)
    return bytes(chunks)


def recv_message(sock: socket.socket):
    """读一条消息; 连接正常关闭返回 None。中途异常抛出 ConnectionError。"""
    head = recv_exact(sock, 4)
    if head is None:
        return None
    (length,) = _FRAME.unpack(head)
    if length <= 0 or length > MAX_FRAME_BYTES:
        raise ConnectionError(f"invalid frame length: {length}")
    payload = recv_exact(sock, length)
    if payload is None:
        raise ConnectionError("connection closed mid-frame")
    return pickle.loads(payload)
