"""
InputBackend — 窗口输入后端抽象
════════════════════════════════════

将 InputPipeline 与具体窗口系统 (GLFW / SDL2 / ...) 解耦。
后端负责:
  - 注册/注销输入回调
  - 提供光标位置
  - 定义事件动作常量 (PRESS / RELEASE / REPEAT)

扩展新后端:
  继承 InputBackend, 实现全部抽象方法。
  GLFWInputBackend 是参考实现。

设计约定:
  - 键盘/鼠标按键码沿用 GLFW 约定 (KeyButtonCode / MouseButtonCode 枚举),
    新后端需将自身码值转换为 GLFW 约定码。
  - 回调签名与 GLFW 标准一致:
      key(window, key, scancode, action, mods)
      mouse_button(window, button, action, mods)
      cursor_pos(window, x, y)
      scroll(window, xoff, yoff)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional

import glfw


# ═══════════════════════════════════════════════════════════════
# 抽象后端
# ═══════════════════════════════════════════════════════════════

class InputBackend(ABC):
    """窗口输入后端抽象接口。

    子类需提供:
      - 事件动作常量 (PRESS / RELEASE / REPEAT)
      - 回调注册/注销方法
      - 光标位置查询
    """

    # ── 事件动作常量 (子类覆写) ──
    PRESS: int
    RELEASE: int
    REPEAT: int

    # ── 回调注册 ──

    @abstractmethod
    def set_key_callback(self, cb: Callable) -> Optional[Callable]:
        """注册键盘回调。返回之前的回调 (用于 detach 恢复)。"""
        ...

    @abstractmethod
    def set_mouse_button_callback(self, cb: Callable) -> Optional[Callable]:
        """注册鼠标按键回调。返回之前的回调。"""
        ...

    @abstractmethod
    def set_cursor_pos_callback(self, cb: Callable) -> Optional[Callable]:
        """注册光标位置回调。返回之前的回调。"""
        ...

    @abstractmethod
    def set_scroll_callback(self, cb: Callable) -> Optional[Callable]:
        """注册滚轮回调。返回之前的回调。"""
        ...

    # ── 查询 ──

    @abstractmethod
    def get_cursor_pos(self) -> tuple[float, float]:
        """返回当前光标位置 (x, y)。"""
        ...


# ═══════════════════════════════════════════════════════════════
# GLFW 实现
# ═══════════════════════════════════════════════════════════════

class GLFWInputBackend(InputBackend):
    """GLFW 输入后端 — 将 InputBackend 接口委托给 GLFW。

    Usage:
        backend = GLFWInputBackend(glfw_window)
        pipeline = InputPipeline(backend)
    """

    PRESS: int = glfw.PRESS
    RELEASE: int = glfw.RELEASE
    REPEAT: int = glfw.REPEAT

    def __init__(self, glfw_window) -> None:
        self._window = glfw_window

    # ── 回调注册 ──

    def set_key_callback(self, cb: Callable) -> Optional[Callable]:
        return glfw.set_key_callback(self._window, cb)

    def set_mouse_button_callback(self, cb: Callable) -> Optional[Callable]:
        return glfw.set_mouse_button_callback(self._window, cb)

    def set_cursor_pos_callback(self, cb: Callable) -> Optional[Callable]:
        return glfw.set_cursor_pos_callback(self._window, cb)

    def set_scroll_callback(self, cb: Callable) -> Optional[Callable]:
        return glfw.set_scroll_callback(self._window, cb)

    # ── 查询 ──

    def get_cursor_pos(self) -> tuple[float, float]:
        return glfw.get_cursor_pos(self._window)
