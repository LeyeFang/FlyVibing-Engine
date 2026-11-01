"""Debug 事件分类 + 终端上报过滤（Core 层，无 Editor 依赖）。

背景（2026-11-01）:
  `RuntimeDebugLayer` 以前用硬编码 `_SILENT_EVENTS` 元组屏蔽高频事件，
  其余全部 `print(event)`。现在把"哪些事件类型要上报"变成可配置项：

  - 分类表 `EVENT_CATALOG` 是**唯一权威**（key / 分组 / 默认开 / 是否高频）；
  - `DebugReportConfig` 持有当前开关与勾选集合，`RuntimeDebugLayer` 每事件查一次；
  - 编辑器设置 `debug.terminal.enabled` / `debug.terminal.events` 经 EditorSettings
    的 apply 钩子写入本配置（见 `EditorSettings._apply_one`）；
  - CLI / MCP：`debug.events` op 读写同一状态（持久化在编辑器设置）。

约定:
  - **默认值与旧行为一致** —— 只关掉原本的高频静默项（鼠标移动/拖拽、相机更新、
    性能统计），因此本次改造不改变默认控制台观感；
  - 未在分类表登记的事件走 `other` 分组（默认上报，避免新事件被静默吞掉）；
  - 被过滤的事件**不 consume**，仍会传给后续层（与旧 `_SILENT_EVENTS` 行为一致）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Type

from Application.Core.Events.EngineEvent import EngineLifecycleEvent, LayerLifecycleEvent
from Application.Core.Events.Event import Event
from Application.Core.Events.InputEvent import (
    KeyboardButtonEvent,
    MouseButtonEvent,
    MouseGragEvent,
    MouseMoveEvent,
    ScrollerEvent,
)
from Application.Core.Events.RendererEvent import RendererMeshReleaseEvent
from Application.Core.Events.SceneEvent import (
    ComponentModifiedEvent,
    NewComponentEvent,
    NewSceneEvent,
    SceneCameraUpdateEvent,
    UpdateShaderUniformsEvent,
)
from Application.Core.Events.StatsEvent import PerformanceStatsEvent
from Application.Core.Events.WindowEvent import WindowCloseEvent, WindowResizeEvent


@dataclass(frozen=True)
class DebugEventSpec:
    """一个可勾选的事件类型。"""

    key: str                      # 设置里的稳定键（"window.close"）
    group: str                    # UI 分组（Window / Input / Scene / ...）
    label_key: str                # I18n 键
    types: tuple[Type[Event], ...] = ()
    default: bool = True          # 默认是否上报（旧行为基准）
    hot: bool = False             # 高频（默认关闭优先考虑）

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "group": self.group,
            "label_key": self.label_key,
            "default": self.default,
            "hot": self.hot,
            "types": [t.__name__ for t in self.types],
        }


EVENT_CATALOG: tuple[DebugEventSpec, ...] = (
    # ── Window ──
    DebugEventSpec("window.close", "Window", "settings.debug.event.close",
                   (WindowCloseEvent,)),
    DebugEventSpec("window.resize", "Window", "settings.debug.event.resize",
                   (WindowResizeEvent,)),
    # ── Input ──
    DebugEventSpec("input.key", "Input", "settings.debug.event.key",
                   (KeyboardButtonEvent,)),
    DebugEventSpec("input.mouse.button", "Input", "settings.debug.event.mouse_button",
                   (MouseButtonEvent,)),
    DebugEventSpec("input.mouse.move", "Input", "settings.debug.event.mouse_move",
                   (MouseMoveEvent,), default=False, hot=True),
    DebugEventSpec("input.mouse.drag", "Input", "settings.debug.event.mouse_drag",
                   (MouseGragEvent,), default=False, hot=True),
    DebugEventSpec("input.scroll", "Input", "settings.debug.event.scroll",
                   (ScrollerEvent,)),
    # ── Scene ──
    DebugEventSpec("scene.new", "Scene", "settings.debug.event.scene",
                   (NewSceneEvent,)),
    DebugEventSpec("scene.component.new", "Scene", "settings.debug.event.component_new",
                   (NewComponentEvent,)),
    DebugEventSpec("scene.component.modified", "Scene",
                   "settings.debug.event.component_modified",
                   (ComponentModifiedEvent,)),
    DebugEventSpec("scene.shader.uniforms", "Scene", "settings.debug.event.shader",
                   (UpdateShaderUniformsEvent,)),
    DebugEventSpec("scene.camera", "Scene", "settings.debug.event.camera",
                   (SceneCameraUpdateEvent,), default=False, hot=True),
    # ── Engine / Renderer / Stats ──
    DebugEventSpec("engine.lifecycle", "Engine", "settings.debug.event.engine",
                   (EngineLifecycleEvent,)),
    DebugEventSpec("layer.lifecycle", "Engine", "settings.debug.event.layer",
                   (LayerLifecycleEvent,)),
    DebugEventSpec("renderer.mesh.release", "Renderer", "settings.debug.event.mesh_release",
                   (RendererMeshReleaseEvent,)),
    DebugEventSpec("stats.performance", "Stats", "settings.debug.event.stats",
                   (PerformanceStatsEvent,), default=False, hot=True),
    # ── 兜底：未登记的新事件类型 ──
    DebugEventSpec("other", "Other", "settings.debug.event.other", ()),
)

_BY_KEY = {spec.key: spec for spec in EVENT_CATALOG}
_BY_CLASS: dict[type, DebugEventSpec] = {}
for _spec in EVENT_CATALOG:
    for _cls in _spec.types:
        _BY_CLASS[_cls] = _spec
_FALLBACK = _BY_KEY["other"]

DEFAULT_KEYS: tuple[str, ...] = tuple(s.key for s in EVENT_CATALOG if s.default)


def all_keys() -> tuple[str, ...]:
    return tuple(_BY_KEY)


def default_keys() -> tuple[str, ...]:
    return DEFAULT_KEYS


def spec_for(event: Event) -> DebugEventSpec:
    """按 MRO 找最近的事件分类；未登记 → `other`。"""
    return spec_for_type(type(event))


def spec_for_type(cls: type) -> DebugEventSpec:
    for base in getattr(cls, "__mro__", ()):
        spec = _BY_CLASS.get(base)
        if spec is not None:
            return spec
    return _FALLBACK


def catalog() -> list[dict]:
    return [spec.to_dict() for spec in EVENT_CATALOG]


def normalize_keys(value: object) -> list[str]:
    """把设置值归一成合法 key 列表（未知 key 丢弃、去重、保序）。"""
    if value is None:
        return list(DEFAULT_KEYS)
    if isinstance(value, str):
        raw = [p for p in value.replace(";", ",").split(",")]
    elif isinstance(value, (list, tuple, set, frozenset)):
        raw = list(value)
    else:
        return list(DEFAULT_KEYS)
    out: list[str] = []
    for item in raw:
        key = str(item).strip()
        if key and key in _BY_KEY and key not in out:
            out.append(key)
    return out


class DebugReportConfig:
    """终端上报开关 + 事件白名单（类级单例；线程安全靠原子引用替换）。"""

    _enabled: bool = True
    _keys: frozenset[str] = frozenset(DEFAULT_KEYS)

    @classmethod
    def configure(cls, *, enabled: bool | None = None,
                  keys: Iterable[str] | str | None = None) -> dict:
        if enabled is not None:
            cls._enabled = bool(enabled)
        if keys is not None:
            cls._keys = frozenset(normalize_keys(keys))
        return cls.state()

    @classmethod
    def reset(cls) -> None:
        cls._enabled = True
        cls._keys = frozenset(DEFAULT_KEYS)

    @classmethod
    def set_enabled(cls, value: object) -> None:
        cls._enabled = bool(value)

    @classmethod
    def set_keys(cls, value: object) -> None:
        cls._keys = frozenset(normalize_keys(value))

    @classmethod
    def is_enabled(cls) -> bool:
        return cls._enabled

    @classmethod
    def keys(cls) -> list[str]:
        return sorted(cls._keys)

    @classmethod
    def should_report(cls, event: Event) -> bool:
        if not cls._enabled:
            return False
        return spec_for(event).key in cls._keys

    @classmethod
    def state(cls) -> dict:
        return {"enabled": cls._enabled, "events": cls.keys()}
