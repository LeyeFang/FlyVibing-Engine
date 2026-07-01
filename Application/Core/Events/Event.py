"""
事件系统 — 实例级别状态，支持多上下文。

架构:
  - MetaEvent (ABCMeta):  元类，让 Event 子类 print 时显示类名 + log_info
  - Event (metaclass=MetaEvent): 基类，实例级 __init__ / __str__ / unpack / Pack
  - 子类: 覆写 __init__ 持有数据, 覆写 unpack() 返回数据元组

Pack 流程:
  子类 .Pack(*args) → 创建实例 → app_callback_func(instance) → Application.OnEvent(instance)

类型检查:
  使用 isinstance(event, SomeEvent) 替代 event is SomeEvent

线程安全:
  实例创建 + 派发在调用线程完成 (通常是主线程)
"""

from Application.Core.Timer.Timer import GetRunTime

from abc import ABCMeta
from typing import Any


app_callback_func: callable = None

# ── Engine 事件回调注册表 ──────────────────────────────────────
# key = Engine 类 (如 EditorHost, GameRuntime)
# value = 该 Engine 的 _on_event 类方法
_engine_callbacks: dict[type, callable] = {}


def _register_engine(engine_cls: type) -> None:
    """注册一个 Engine 的 _on_event 回调。

    之后该 Engine 的子类可以通过 Event.Pack(..., engine=engine_cls) 路由事件。
    """
    _engine_callbacks[engine_cls] = engine_cls._on_event


def _is_first_bind() -> bool:
    """检查是否尚未绑定全局事件回调。"""
    global app_callback_func
    return app_callback_func is None


class MetaEvent(ABCMeta):
    """元类：让 Event 的子类在 print 时显示类名。

    仅对类本身生效 (print(WindowResizeEvent))。
    实例的 __str__ 由 Event 基类提供 (print(event))。
    """

    def __str__(cls):
        return f"Event Class: {cls.__name__}"

    def __repr__(cls):
        return cls.__str__()


class Event(metaclass=MetaEvent):
    """事件基类 — 实例级别状态。

    每个事件实例携带独立的数据, 不共享类属性,
    因此支持多个窗口/上下文同时使用不同的事件流。

    子类用法:
        class MyEvent(Event):
            def __init__(self, x, y):
                super().__init__()
                self.x = x
                self.y = y

            def unpack(self):
                return self.x, self.y

        # 派发
        MyEvent.Pack(10, 20)
    """

    def __init__(self) -> None:
        self._consumed: bool = False
        self._source_engine: type | None = None  # 由 Pack/_dispatch 设置

    # ── 日志 ──

    @property
    def log_info(self) -> str:
        """子类可覆写为 property 以动态生成日志信息。"""
        return ''

    def _engine_prefix(self) -> str:
        """返回事件来源 Engine 的前缀标签，如 '[EditorHost] '。"""
        if self._source_engine is not None:
            name = self._source_engine.__name__
            return f"[{name}] "
        return ''

    def __str__(self) -> str:
        info = self.log_info
        prefix = self._engine_prefix()
        if info:
            return f"{prefix}Time: {GetRunTime():.4f}, Event: {type(self).__name__}, {info}"
        return f"{prefix}Time: {GetRunTime():.4f}, Event: {type(self).__name__}"

    def __repr__(self) -> str:
        return self.__str__()

    # ── 派发 ──

    @classmethod
    def Pack(cls, *args, engine=None, **kwargs) -> None:
        """创建事件实例并派发到指定 Engine 的回调。

        Args:
            *args: 传给 __init__ 的位置参数。
            engine: 目标 Engine 类 (如 EditorHost / GameRuntime)。
                    为 None 时回退到全局 app_callback_func。
            **kwargs: 传给 __init__ 的关键字参数。

        子类可覆写 (如 MouseGragEvent 需持久状态计算位移),
        覆写时应在末尾调用 super().Pack(..., engine=engine, **kwargs)。
        """
        instance = cls(*args, **kwargs)
        instance._source_engine = engine
        if engine is not None and engine in _engine_callbacks:
            _engine_callbacks[engine](instance)
        else:
            app_callback_func(instance)

    @classmethod
    def _dispatch(cls, instance: 'Event', engine=None) -> None:
        """直接派发已创建的事件实例 (供子类 Pack 覆写使用)。"""
        instance._source_engine = engine
        if engine is not None and engine in _engine_callbacks:
            _engine_callbacks[engine](instance)
        else:
            app_callback_func(instance)

    # ── 数据读取 ──

    def unpack(self) -> Any:
        """返回事件携带的数据 (子类覆写)。

        Returns:
            任意类型的数据元组
        """
        return None

    # ── 消费标记 ──

    @property
    def consumed(self) -> bool:
        """事件是否已被消费 (被消费后后续处理器应跳过)。"""
        return self._consumed

    def consume(self) -> None:
        """标记事件已消费。"""
        self._consumed = True


def BindPackCallback(
    cb_func: callable
) -> None:
    """绑定全局事件回调 (由 Application.Create 调用)。"""
    global app_callback_func
    app_callback_func = cb_func


def _is_first_bind() -> bool:
    """检查是否尚未绑定事件回调（防止 GameRuntime 覆盖 EditorHost 的回调）。"""
    global app_callback_func
    return app_callback_func is None
