"""
RuntimeNodeLayer — 由节点图驱动的 GameRuntime Layer。

职责:
  - OnAttach:  从 NodeCanvas 构建 GraphEvaluator，触发 OnGameStart
  - OnUpdate:  更新 ExecutionContext（deltaTime），触发 OnFrameUpdate，
               + 同步场景摄像机矩阵到渲染器
  - OnDetach:  触发 OnGameStop

节点图来源:
  生产环境: 从 JSON 反序列化 NodeCanvas
  测试环境: 直接注入预设的 NodeCanvas

使用方式:
    from Application.Runtime.RuntimeNodeLayer import RuntimeNodeLayer
    GameRuntime.push_layer(RuntimeNodeLayer)
    RuntimeNodeLayer.set_canvas(my_canvas)  # 注入节点图
"""

from __future__ import annotations

import numpy as np

from Application.Core.Layers.Layer import Layer
from Application.Core.Events.Event import Event
from Application.Core.Events.EngineEvent import LayerLifecycleEvent
from Application.Core.Renderer.RenderCommand import SetViewProjectionCommand
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.NodeGraph import _TYPES
from Application.Core.NodeGraph.evaluator_engine import (
    GraphEvaluator,
    ExecutionContext,
)


class RuntimeNodeLayer(Layer):
    """由节点图驱动的游戏逻辑层。"""

    # ── 外部注入: 节点图 + 场景 ─────────────────────────────
    _canvas = None          # NodeCanvas 实例
    _scene = None           # Scene 对象 (EntitySpawn 模板来源)
    _evaluator: GraphEvaluator | None = None
    _context: ExecutionContext | None = None
    _pending_start: bool = False  # 延迟 OnGameStart 到逻辑线程
    _frame: int = 0               # 逻辑帧计数 — 必须有类默认值:
                                  # OnAttach(渲染线程) 与 OnUpdate(逻辑线程) 并发 (free-threading 无 GIL)
    # ── 宿主注入: 上下文钩子 (PIE 由 SimulationController 设置; 独立运行留空) ──
    _on_stop_request = None       # callable | None — ExitGame 停止请求 → 宿主处理

    @classmethod
    def set_canvas(cls, canvas) -> None:
        """注入节点图。必须在 push_layer 之前调用。"""
        cls._canvas = canvas

    @classmethod
    def set_scene(cls, scene) -> None:
        """注入 Scene 对象 (提供 EntitySpawn 的 entity 模板)。

        必须在 push_layer 之前调用。
        PIE 模式: EditorHost.get_active_scene() 深拷贝
        导出模式: 从 .scene 文件反序列化
        """
        cls._scene = scene

    @classmethod
    def set_context_hooks(cls, on_stop_request=None) -> None:
        """注册宿主上下文钩子 (None = 清除)。

        on_stop_request: ExitGame 停止请求回调 —
                         PIE 传 SimulationController.stop; 独立运行留空
                         (留空时由本层在帧末以中性方式结束 GameRuntime)。
        """
        cls._on_stop_request = on_stop_request

    @classmethod
    def _consume_stop_request(cls) -> None:
        """ExitGame 停止请求兜底: 宿主未注册回调时用运行时中立方式结束 GameRuntime。"""
        if cls._context is None:
            return
        if cls._context.stop_requested and cls._context.on_stop_request is None:
            from Application.Runtime.GameRuntime import GameRuntime
            GameRuntime.run_state = False

    # ════════════════════════════════════════════════════════════
    # Layer 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def OnAttach(cls):
        LayerLifecycleEvent.Pack(
            layer_name=cls.__name__, stage="attach", engine=cls._engine
        )
        if cls._canvas is None:
            print("[RuntimeNodeLayer] WARNING: No canvas set — graph will not execute")
            return

        # 防止重复初始化
        if cls._evaluator is not None:
            return

        cls._context = ExecutionContext()
        cls._context.scene = cls._engine.scene     # ★ 注入 SceneManager 实例
        # ★ 宿主注入: 模板场景 (EntitySpawn) + 停止回调 (ExitGame)
        cls._context.template_scene = cls._scene
        cls._context.on_stop_request = cls._on_stop_request
        cls._frame = 0

        # ── 延迟 OnGameStart 到逻辑线程的第一次 OnUpdate ──
        # (避免渲染线程操作 esper / 世界切换冲突)
        cls._context.elapsed_time = 0.0
        cls._context.delta_time = 0.0
        cls._pending_start = True

        # ★ _evaluator 最后赋值 — 它是 OnUpdate 的"可见性开关":
        #   OnAttach 在渲染线程执行，逻辑线程的 OnUpdate 循环与其并发
        #   (Engine._render_loop: run_ready 放行后两线程同时起步)。
        #   OnUpdate 只有越过 `_evaluator is None` 守卫后才执行帧逻辑，
        #   因此必须先备齐 _context / _frame / _pending_start，最后再赋值 _evaluator。
        #   顺序错误 → 逻辑线程读到半初始化状态 → _frame AttributeError (free-threading 无 GIL)。
        #   回归测试: Test/Application/Runtime/test_runtime_node_layer_race.py
        cls._evaluator = GraphEvaluator(cls._canvas, _TYPES)

        # ★ 首帧推送摄像机矩阵 — 确保渲染器第一帧就有合法的 view/proj
        cls._sync_camera_to_renderer()

    @classmethod
    def OnDetach(cls):
        if cls._evaluator is not None and cls._context is not None:
            cls._evaluator.trigger("OnGameStop", cls._context)
            print("[RuntimeNodeLayer] Graph execution stopped")
        cls._evaluator = None
        cls._context = None
        cls._pending_start = False
        LayerLifecycleEvent.Pack(
            layer_name=cls.__name__, stage="detach", engine=cls._engine
        )

    @classmethod
    def OnUpdate(cls):
        if cls._evaluator is None or cls._context is None:
            return

        # ── ★ 原子拍 (atomic beat): 本次逻辑 tick 产生的全部渲染命令作为一批入队 ──
        #    (批暂存于本线程, tick 结束时整批可见 — 渲染线程的帧边界不会把
        #     同一 tick 的多部件显隐/生成命令切成两帧; 见 CommandQueue 头注)
        _renderer = getattr(cls._engine, 'renderer', None) if cls._engine is not None else None
        if _renderer is not None:
            _renderer.begin_command_batch()
        try:
            # ── 延迟的 OnGameStart: 在逻辑线程首次 OnUpdate 执行 ──
            if cls._pending_start:
                cls._pending_start = False
                cls._evaluator.trigger("OnGameStart", cls._context)
                print("[RuntimeNodeLayer] Graph execution started")
                # ★ ExitGame 等节点请求停止 (宿主未注册回调时的兜底)
                cls._consume_stop_request()
                # 首帧后立即同步摄像机
                cls._sync_camera_to_renderer()
                return

            cls._frame += 1
            # 仅当 frame 为奇数时执行（跳过重复实例的第二次调用）
            if cls._frame % 2 == 1:
                if cls._engine is not None:
                    cls._context.delta_time = cls._engine.get_delta_time()
                    cls._context.elapsed_time = cls._engine.get_elapsed_time()
                cls._evaluator.trigger("OnFrameUpdate", cls._context)

                # ★ ExitGame 等节点请求停止 (宿主未注册回调时的兜底)
                cls._consume_stop_request()

                # ★ 每帧同步场景摄像机矩阵到渲染器
                cls._sync_camera_to_renderer()
        finally:
            if _renderer is not None:
                _renderer.end_command_batch()

    @classmethod
    def _sync_camera_to_renderer(cls) -> None:
        """从 SceneManager.scene_camera_id 读取 Camera + Transform，
        计算 view/proj 矩阵并通过 SetViewProjectionCommand 推送给渲染器。

        支持透视和正交两种投影类型：
          - perspective → pure numpy perspective projection (fov + aspect_ratio)
          - orthographic → pure numpy orthogonal projection (ortho_size + aspect_ratio)

        若 scene_camera_id 无效（实体不存在 / 缺少组件），跳过推送。
        """
        if cls._engine is None:
            return
        renderer = getattr(cls._engine, 'renderer', None)
        if renderer is None:
            return

        from Application.Core.Math.Camera import perspective_projection, orthogonal_projection
        from Application.Core.Scene.BasicComponents import Camera, Transform, ProjectionType
        from Application.Core.Math.Transform import calculate_entity_model

        scene = cls._engine.scene
        if scene is None:
            return
        cam_id = scene.scene_camera_id
        if cam_id is None or not scene.EntityExists(cam_id):
            return

        try:
            cam = scene.GetComponent(cam_id, Camera)
            xform = scene.GetComponent(cam_id, Transform)
        except Exception:
            return

        # ── 视图矩阵: inverse(model) ──
        model = calculate_entity_model(
            position=(xform.position_x, xform.position_y, xform.position_z),
            rotation=(xform.rotation_x, xform.rotation_y, xform.rotation_z),
            scale=(xform.scale_x, xform.scale_y, xform.scale_z),
        )
        view = np.linalg.inv(model)

        # ── 投影矩阵 ──
        aspect = getattr(renderer, 'aspect_ratio', 16.0 / 9.0)
        if cam.projection_type == ProjectionType.ORTHOGRAPHIC:
            half_h = cam.ortho_size
            half_w = half_h * aspect
            proj = orthogonal_projection(
                -half_w, half_w, -half_h, half_h,
                cam.near_plane, cam.far_plane,
            )
            is_ortho = True
            ortho_sz = cam.ortho_size
        else:
            proj = perspective_projection(
                cam.fov, aspect,
                cam.near_plane, cam.far_plane,
            )
            is_ortho = False
            ortho_sz = 10.0

        renderer.enqueue(SetViewProjectionCommand(
            view=view,
            proj=proj,
            orbit_target=np.array(
                [xform.position_x, xform.position_y, xform.position_z],
                dtype=np.float32,
            ),
            orbit_distance=float(np.linalg.norm(
                [xform.position_x, xform.position_y, xform.position_z],
            )),
            is_orthographic=is_ortho,
            ortho_size=ortho_sz,
        ))
