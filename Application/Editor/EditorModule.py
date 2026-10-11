"""
EditorModule — 编辑器宿主装配模块（L0 EngineModule 实现）。

职责:
  - 暴露编辑器 Layer: EditorImguiLayer / EditorLayer / EditorGizmoLayer /
    EditorInputLayer / DebugLayer
  - 装配级初始化/清理（LiveCommandServer 启停；未来 ImGui 上下文管理等从 EditorLayer 搬来）

生命周期:
  EditorHost.init() → EditorHost.load_module(EditorModule())
    ├── EditorModule.on_load(engine)
    └── Engine.push_layer(...) ×5

  EditorHost.run() → ... → EditorHost.shutdown()
    └── EditorModule.on_unload()

架构定位: 见 Doc/Dev/extension_protocol.md §1/§2 — 本文件属于 L0 宿主装配层,
不是对外扩展（Extension）机制; 扩展请使用 Functions/** + extension.json（Doc/ExtDev/extension_dev_protocol.md）。

历史: 原名 EditorPlugin（2026-10-11 更名; EditorPlugin.py 为过渡别名 shim）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from Application.Core.EngineModule import EngineModule
from Application.Core.Layers.Layer import Layer

if TYPE_CHECKING:
    from Application.Core.Engine import Engine


class EditorModule(EngineModule):
    """编辑器装配模块 — 管理所有编辑器 UI 子系统的加载/卸载。"""

    name: str = "EditorModule"
    version: str = "0.1.0"

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    def on_load(self, engine: 'Engine') -> None:
        """编辑器装配加载（主线程）。"""
        # ── 实时命令总线（agent MCP 热注入; 仅本机回环 127.0.0.1）──
        try:
            from Application.Editor.Services.LiveCommandServer import LiveCommandServer
            LiveCommandServer.start()
        except Exception as e:  # noqa: BLE001
            print(f"[Live] command server failed to start: {e}")

    def on_unload(self) -> None:
        """编辑器装配卸载（主线程）。"""
        # ── 扩展体系清理（L1, M0）: 卸载全部已装载扩展（不改变持久化启用状态） ──
        try:
            from Application.Editor.Extensions.ExtensionManager import ExtensionManager
            ExtensionManager.unload_all()
        except Exception:  # noqa: BLE001
            pass
        try:
            from Application.Editor.Services.LiveCommandServer import LiveCommandServer
            LiveCommandServer.stop()
        except Exception:  # noqa: BLE001
            pass

    # ════════════════════════════════════════════════════════════
    # Layer 暴露
    # ════════════════════════════════════════════════════════════

    def get_layers(self) -> list[type[Layer]]:
        """返回编辑器装配拥有的 Layer 类（按 OnAttach 执行顺序）。

        EditorImguiLayer → ImGui 上下文 / 字体 / Backend / 面板 (必须在最前)
        EditorLayer      → 渲染器接入 / overlay 注册 / 层间连线
        EditorGizmoLayer → Camera entity gizmo 可视化 / 预览切换
        EditorInputLayer → 输入事件路由 (鼠标/键盘/滚轮/窗口)
        DebugLayer       → 性能 HUD + 场景调试实体
        """
        from Application.Editor.EditorImguiLayer import EditorImguiLayer
        from Application.Editor.EditorLayer import EditorLayer
        from Application.Editor.EditorGizmoLayer import EditorGizmoLayer
        from Application.Editor.EditorInputLayer import EditorInputLayer
        from Application.Editor.EditorDebugLayer import DebugLayer
        return [EditorImguiLayer, EditorLayer, EditorGizmoLayer, EditorInputLayer, DebugLayer]
