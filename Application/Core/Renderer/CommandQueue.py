"""
CommandQueue — 线程安全的主线程→渲染线程命令队列。

设计:
  - SPSC — 主线程 enqueue, 渲染线程 execute_all
  - 轻量锁 — enqueue/dequeue 各自加锁, 互不阻塞

原子批 (2026-10-07):
  - begin_batch()/end_batch() 线程局部批模式 (与逻辑 tick 同寿):
    批内本线程 enqueue 暂存于 staging, 批结束时一次性入队 —
    渲染线程的 drain 要么看到整批、要么看不到, **不会把一批命令切成两帧**。
    修复: 多部件 cue "箭把/箭头各自一帧出现" 的帧边界竞态 (MI-SSSEP 实测问题)。
  - 支持嵌套 (深度计数); 仅有批开启线程被暂存, 其他线程直进队列。
  - 调用方必须 try/finally 保证 end_batch (见 RuntimeNodeLayer.OnUpdate)。
"""

from __future__ import annotations

import threading
from collections import deque
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from Application.Core.Renderer.RenderCommand import RenderCommand


class CommandQueue:
    """线程安全的渲染命令队列 (含线程局部原子批)。"""

    def __init__(self) -> None:
        self._queue: deque['RenderCommand'] = deque()
        self._lock = threading.Lock()
        self._local = threading.local()

    # ════════════════════════════════════════════════════════════
    # 原子批 (线程局部 — 逻辑线程)
    # ════════════════════════════════════════════════════════════

    def _staging(self) -> list | None:
        return getattr(self._local, "staging", None)

    @property
    def batch_active(self) -> bool:
        """当前线程是否处于批模式。"""
        return self._staging() is not None

    def begin_batch(self) -> None:
        """开启原子批 (可嵌套) — 本线程后续 enqueue 暂存, end_batch 时一次性入队。"""
        if self._staging() is None:
            self._local.staging = []
            self._local.depth = 1
        else:
            self._local.depth += 1

    def end_batch(self) -> None:
        """结束原子批 — 深度归零时把暂存命令一次性并入队列。"""
        st = self._staging()
        if st is None:
            return
        self._local.depth -= 1
        if self._local.depth > 0:
            return
        self._local.staging = None
        self._local.depth = 0
        if st:
            with self._lock:
                self._queue.extend(st)

    # ════════════════════════════════════════════════════════════
    # 入队 / 消费
    # ════════════════════════════════════════════════════════════

    def enqueue(self, cmd: 'RenderCommand') -> None:
        """提交一条渲染命令 (批模式下本线程暂存)。"""
        st = self._staging()
        if st is not None:
            st.append(cmd)
            return
        with self._lock:
            self._queue.append(cmd)

    def enqueue_many(self, cmds: Iterable['RenderCommand']) -> None:
        """提交一组命令 — 同一批的成员保证被同一个 drain 消费 (同帧生效)。"""
        st = self._staging()
        if st is not None:
            st.extend(cmds)
            return
        with self._lock:
            self._queue.extend(cmds)

    def dequeue_all(self) -> list['RenderCommand']:
        """渲染线程: 取出并清空所有待执行命令 (批暂存不可见 — 原子性来源)。"""
        with self._lock:
            commands = list(self._queue)
            self._queue.clear()
            return commands

    def execute_all(self, renderer) -> None:
        """渲染线程: 取出所有命令并逐一执行。"""
        for cmd in self.dequeue_all():
            cmd.execute(renderer)

    def __len__(self) -> int:
        st = self._staging()
        staged = len(st) if st is not None else 0
        with self._lock:
            return len(self._queue) + staged
