"""
CommandQueue — 线程安全的主线程→渲染线程命令队列。

设计:
  - SPSC (单生产者单消费者) — 主线程 enqueue, 渲染线程 dequeue_all+execute
  - 无阻塞 — enqueue 只加锁, execute 消费全部后清空
  - 不提供 Future 机制 (当前被动命令不需要回执; 未来资源命令再扩展)
"""

from __future__ import annotations

import threading
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Test.RHI.Engine.RenderCommand import RenderCommand


class CommandQueue:
    """线程安全的 SPSC 命令队列。

    主线程调用 enqueue(), 渲染线程调用 dequeue_all() + execute_all()。
    """

    def __init__(self):
        self._queue: deque[RenderCommand] = deque()
        self._lock = threading.Lock()

    def enqueue(self, cmd: RenderCommand) -> None:
        """主线程安全: 提交一条命令到队尾。"""
        with self._lock:
            self._queue.append(cmd)

    def dequeue_all(self) -> list[RenderCommand]:
        """渲染线程: 一次性取出所有待处理命令并清空队列。"""
        with self._lock:
            commands = list(self._queue)
            self._queue.clear()
        return commands

    def execute_all(self, commands: list[RenderCommand]) -> None:
        """渲染线程: 按顺序执行所有命令。"""
        for cmd in commands:
            cmd.execute()

    # ════════════════════════════════════════════════════════════
    # TODO: 以下内容需要从备份恢复
    # ════════════════════════════════════════════════════════════
    # - 原始文件包含更完整的实现细节
    # - 请从 git 历史或备份中恢复完整内容
