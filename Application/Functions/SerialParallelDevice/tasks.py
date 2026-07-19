"""SerialParallelDevice — 任务类型定义。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SerialTask:
    """串口发送任务。"""
    port: str
    baud: int
    data: bytes


@dataclass
class ParallelTask:
    """并口写入任务。"""
    address: int        # I/O 端口基地址 (如 0x378)
    data: bytes         # 已编码的字节
