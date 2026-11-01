"""Debug ▸ Terminal 事件上报配置（core，无头）。

背景（2026-11-01）:
  `RuntimeDebugLayer` 原来用硬编码 `_SILENT_EVENTS` 屏蔽高频事件。现在事件类型
  归入 `DebugEvents.EVENT_CATALOG`，由设置 `debug.terminal.enabled/events` 控制，
  设置变更经 apply 钩子同步到 `DebugReportConfig`；CLI/MCP 用 `debug.events` op。

本测试锁定:
  1. 分类表 key 唯一、覆盖全部已登记事件类
  2. 默认勾选集 == 旧 `_SILENT_EVENTS` 行为（只关鼠标移动/拖拽、相机、统计）
  3. `should_report` 开关/白名单语义（未登记类型落 `other`）
  4. `normalize_keys` 解析（逗号串 / 列表 / 未知 key 丢弃 / 去重）
  5. EditorSettings 写入后经 `apply_pending` 同步到 `DebugReportConfig`
"""

# TIER: core

from __future__ import annotations

import os
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _parent = os.path.dirname(_d)
    if _parent == _d:
        _d = ""
        break
    _d = _parent
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402,F401

# 设置写盘隔离（不得污染开发者真实 settings.json）
_TMP = tempfile.mkdtemp(prefix="mge_debug_settings_")
os.environ["MGE_EDITOR_SETTINGS"] = os.path.join(_TMP, "settings.json")

from Application.Core.Diagnostics.DebugEvents import (  # noqa: E402
    DEFAULT_KEYS,
    EVENT_CATALOG,
    DebugReportConfig,
    normalize_keys,
    spec_for_type,
)
from Application.Core.Events.EngineEvent import EngineLifecycleEvent, LayerLifecycleEvent  # noqa: E402
from Application.Core.Events.Event import Event  # noqa: E402
from Application.Core.Events.InputEvent import (  # noqa: E402
    KeyboardButtonEvent,
    MouseButtonEvent,
    MouseGragEvent,
    MouseMoveEvent,
    ScrollerEvent,
)
from Application.Core.Events.RendererEvent import RendererMeshReleaseEvent  # noqa: E402
from Application.Core.Events.SceneEvent import (  # noqa: E402
    ComponentModifiedEvent,
    NewComponentEvent,
    NewSceneEvent,
    SceneCameraUpdateEvent,
    UpdateShaderUniformsEvent,
)
from Application.Core.Events.StatsEvent import PerformanceStatsEvent  # noqa: E402
from Application.Core.Events.WindowEvent import WindowCloseEvent, WindowResizeEvent  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


_EXPECTED = {
    WindowCloseEvent: "window.close",
    WindowResizeEvent: "window.resize",
    KeyboardButtonEvent: "input.key",
    MouseButtonEvent: "input.mouse.button",
    MouseMoveEvent: "input.mouse.move",
    MouseGragEvent: "input.mouse.drag",
    ScrollerEvent: "input.scroll",
    NewSceneEvent: "scene.new",
    NewComponentEvent: "scene.component.new",
    ComponentModifiedEvent: "scene.component.modified",
    UpdateShaderUniformsEvent: "scene.shader.uniforms",
    SceneCameraUpdateEvent: "scene.camera",
    EngineLifecycleEvent: "engine.lifecycle",
    LayerLifecycleEvent: "layer.lifecycle",
    RendererMeshReleaseEvent: "renderer.mesh.release",
    PerformanceStatsEvent: "stats.performance",
}


class _UnregisteredEvent(Event):
    pass


def test_catalog() -> None:
    print("-- catalog --")
    keys = [s.key for s in EVENT_CATALOG]
    check("catalog keys unique", len(keys) == len(set(keys)))
    check("catalog has other fallback", "other" in keys)
    check("every spec has label_key", all(s.label_key for s in EVENT_CATALOG))
    check("13 defaults (old silent set excluded)",
          len(DEFAULT_KEYS) == 13 and len(EVENT_CATALOG) == 17,
          f"{len(DEFAULT_KEYS)}/{len(EVENT_CATALOG)}")
    for cls, key in _EXPECTED.items():
        check(f"{cls.__name__} -> {key}", spec_for_type(cls).key == key,
              spec_for_type(cls).key)
    check("unregistered event -> other", spec_for_type(_UnregisteredEvent).key == "other")


def _probe(cls):
    """构造未初始化实例（只看类型分类，不依赖构造签名）。"""
    return cls.__new__(cls)


def test_should_report() -> None:
    print("-- should_report --")
    DebugReportConfig.reset()
    check("key on by default", DebugReportConfig.should_report(_probe(KeyboardButtonEvent)))
    check("resize on by default", DebugReportConfig.should_report(_probe(WindowResizeEvent)))
    check("mouse move off by default", not DebugReportConfig.should_report(_probe(MouseMoveEvent)))
    check("camera off by default", not DebugReportConfig.should_report(_probe(SceneCameraUpdateEvent)))
    check("stats off by default", not DebugReportConfig.should_report(_probe(PerformanceStatsEvent)))

    DebugReportConfig.configure(keys=["window.close"])
    check("whitelist keeps close", DebugReportConfig.should_report(_probe(WindowCloseEvent)))
    check("whitelist drops resize", not DebugReportConfig.should_report(_probe(WindowResizeEvent)))

    DebugReportConfig.configure(enabled=False)
    check("disabled reports nothing", not DebugReportConfig.should_report(_probe(WindowCloseEvent)))
    DebugReportConfig.reset()
    check("reset restores defaults", DebugReportConfig.should_report(_probe(WindowCloseEvent)))


def test_normalize_keys() -> None:
    print("-- normalize_keys --")
    check("comma string",
          normalize_keys("window.close, input.key ,bogus") == ["window.close", "input.key"],
          str(normalize_keys("window.close, input.key ,bogus")))
    check("list dedupe",
          normalize_keys(["window.close", "window.close", "other"]) == ["window.close", "other"])
    check("semicolon accepted", normalize_keys("window.close;input.key") == ["window.close", "input.key"])
    check("empty list stays empty", normalize_keys([]) == [])
    check("None -> defaults", normalize_keys(None) == list(DEFAULT_KEYS))


def test_settings_bridge() -> None:
    print("-- settings -> DebugReportConfig --")
    from Application.Editor.EditorSettings import EditorSettings

    EditorSettings.load()
    DebugReportConfig.reset()

    EditorSettings.set("debug.terminal.enabled", "false")
    EditorSettings.set("debug.terminal.events", "window.close, bogus")
    EditorSettings.apply_pending()
    check("enabled=false applied", DebugReportConfig.is_enabled() is False)
    check("events coerced (bogus dropped)", DebugReportConfig.keys() == ["window.close"],
          str(DebugReportConfig.keys()))

    EditorSettings.set("debug.terminal.enabled", True)
    EditorSettings.set("debug.terminal.events", list(DEFAULT_KEYS))
    EditorSettings.apply_pending()
    check("restored enabled", DebugReportConfig.is_enabled() is True)
    check("restored keys", DebugReportConfig.keys() == sorted(DEFAULT_KEYS))


def main() -> int:
    print("== debug report config tests ==")
    test_catalog()
    test_should_report()
    test_normalize_keys()
    test_settings_bridge()

    total = _RESULTS["pass"] + _RESULTS["fail"]
    ok = _RESULTS["fail"] == 0
    print()
    print(f"RESULT: {'OK' if ok else 'FAIL'} ({_RESULTS['pass']}/{total})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
