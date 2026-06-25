"""
CommandQueue — 线程安全的主线程→渲染线程命令队列。

设计:
  - SPSC — 主线程 enqueue, 渲染线程 execute_all
  - 轻量锁 — enqueue/dequeue 各自加锁, 互不阻塞
"""

from __future__ import annotations

import threading
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Application.Core.Renderer.RenderCommand import RenderCommand


class CommandQueue:
    """线程安全的渲染命令队列。"""

    def __init__(self) -> None:
        self._queue: deque['RenderCommand'] = deque()
        self._lock = threading.Lock()

    def enqueue(self, cmd: 'RenderCommand') -> None:
        """主线程: 提交一条渲染命令。"""
        with self._lock:
            self._queue.append(cmd)

    def dequeue_all(self) -> list['RenderCommand']:
        """渲染线程: 取出并清空所有待执行命令。"""
        with self._lock:
            commands = list(self._queue)
            self._queue.clear()
            return commands

    def execute_all(self, renderer) -> None:
        """渲染线程: 取出所有命令并逐一执行。"""
        for cmd in self.dequeue_all():
            cmd.execute(renderer)

    def __len__(self) -> int:
        with self._lock:
            return len(self._queue)
