"""
LiveCommandServer — 编辑器实时命令总线（给 agent 的 MCP 热注入通道）。

架构（详见 Doc/Dev/editor_live_protocol.md）:
    socket 线程(仅收 JSON → 入队 → 等待回执)
        → queue.Queue（门缝）
        → 主线程 pump（EditorLayer.OnUpdate 每帧 drain）
        → op 处理器（复用编辑器现有 API：SimulationController / ViewportController / ...）

线程纪律（free-threading 无 GIL，硬约束）:
    - socket 线程只做 JSON 编解码 + 入队 + 等待回执;
    - 一切编辑器状态变更只在主线程 pump() 中执行 —
      与人类点按钮走完全相同的代码路径。

端点: 127.0.0.1:<port>（仅回环; 默认 8977, 可用环境变量 MGE_EDITOR_MCP_PORT 覆盖）。
协议: NDJSON — 一行一条 JSON:
    请求  {"id": 1, "op": "sim.play", "args": {}}
    回执  {"id": 1, "ok": true,  "result": {...}}
          {"id": 1, "ok": false, "error": "..."}

二进制尾随帧（v2 — 图像通道）:
    若回执行 result 中声明 binary_bytes=N（如 frame.fetch 的就绪帧）, 则该行之后
    紧跟 N 字节裸负载（RGBA8, bottom-up）; 客户端必须先读行、再精确读 N 字节。
    PNG 编码不在引擎侧 — 由 MCP 进程处理（不阻塞渲染/主线程）。
"""

from __future__ import annotations

import json
import os
import queue
import socket
import threading

DEFAULT_PORT = 8977
_ENV_PORT = "MGE_EDITOR_MCP_PORT"
_PUMP_TIMEOUT = 15.0    # 主线程回执等待上限（秒; 逐 op 可覆盖）
# 长任务 op 的主线程等待上限覆盖（引擎侧单一来源; 与 ops.py call_timeout 同口径, 服务器上限≥客户端）
_OP_PUMP_TIMEOUT_OVERRIDES = {
    "project.open": 120.0,     # 大工程资源+场景全量加载
    "project.export": 900.0,   # 游戏层复制 runtime 镜像（数百 MB / 上万文件）— 分钟级
}
_MAX_OPS_PER_FRAME = 16


class LiveCommandServer:
    """编辑器命令总线（类级单例; 随编辑器生命周期启停）。"""

    _sock: socket.socket | None = None
    _thread: threading.Thread | None = None
    _queue: "queue.Queue[dict] | None" = None
    _ops: dict[str, object] = {}
    # ── 扩展 op（增量扫描通道: ExtensionManager 注册, 不入核心注册表/守卫计数） ──
    _ext_ops: dict[str, object] = {}          # op 名 → handler
    _ext_ops_owner: dict[str, str] = {}       # op 名 → 扩展 id
    _ext_ops_summary: dict[str, str] = {}     # op 名 → 摘要
    port: int = 0
    _running: bool = False

    # ════════════════════════════════════════════════════════════
    # 生命周期（主线程调用）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def start(cls, port: int | None = None) -> bool:
        """启动监听（幂等）。port=None → 环境变量或默认 8977; port=0 → 系统分配（测试用）。"""
        if cls._running:
            return True
        if port is None:
            try:
                port = int(os.environ.get(_ENV_PORT, "") or DEFAULT_PORT)
            except ValueError:
                port = DEFAULT_PORT

        cls._queue = queue.Queue()
        cls._register_ops()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            sock.listen(4)
        except OSError as e:
            print(f"[Live] WARNING: cannot bind 127.0.0.1:{port} ({e}) — command server disabled")
            try:
                sock.close()
            except OSError:
                pass
            return False

        cls.port = sock.getsockname()[1]
        cls._sock = sock
        cls._running = True
        cls._thread = threading.Thread(
            target=cls._accept_loop, name="LiveCommandServer", daemon=True
        )
        cls._thread.start()
        print(
            f"[Live] Editor command server on 127.0.0.1:{cls.port} "
            f"(NDJSON) — ops: {', '.join(sorted(cls._ops))}"
        )
        return True

    @classmethod
    def stop(cls) -> None:
        """停止监听（编辑器关闭时调用; 幂等）。"""
        cls._running = False
        sock, cls._sock = cls._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    # ════════════════════════════════════════════════════════════
    # socket 线程（绝不触碰编辑器状态）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _accept_loop(cls) -> None:
        from Application.Core.ThreadRegistry import ThreadRegistry

        _reg = "LiveCommandServer"
        ThreadRegistry.register(_reg, owner="LiveCommandServer", expect_hz=2.0,
                                note="accept 循环 (0.5s 超时); 空闲正常")
        try:
            while cls._running and cls._sock is not None:
                ThreadRegistry.heartbeat(_reg)
                try:
                    cls._sock.settimeout(0.5)
                    conn, _addr = cls._sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                threading.Thread(
                    target=cls._handle_client, args=(conn,), daemon=True
                ).start()
        finally:
            ThreadRegistry.unregister(_reg)

    @classmethod
    def _handle_client(cls, conn: socket.socket) -> None:
        from Application.Core.ThreadRegistry import ThreadRegistry

        _reg = f"live-client:{threading.get_ident()}"
        ThreadRegistry.register(_reg, owner="LiveCommandServer", expect_hz=0.0,
                                note="每连接一线程; 阻塞 recv 不推进心跳=正常")
        try:
            reader = conn.makefile("r", encoding="utf-8", newline="\n")
            for line in reader:
                line = line.strip()
                if not line:
                    continue
                ThreadRegistry.heartbeat(_reg)
                resp = cls._dispatch_line(line)
                payload = None
                result = resp.get("result")
                if isinstance(result, dict) and "_payload" in result:
                    payload = result.pop("_payload")   # 二进制尾随帧: 行后追加, 不入 JSON
                conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                if payload:
                    conn.sendall(payload)
        except (OSError, ValueError):
            pass
        finally:
            ThreadRegistry.unregister(_reg)
            try:
                conn.close()
            except OSError:
                pass

    @classmethod
    def _dispatch_line(cls, line: str) -> dict:
        """解析一条请求 → 入队 → 等待主线程回执 → 组装响应。"""
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("request must be a JSON object")
            rid = req.get("id")
            op = str(req.get("op") or "")
            args = req.get("args") or {}
            if not isinstance(args, dict):
                raise ValueError("args must be a JSON object")
        except ValueError as e:
            return {"id": None, "ok": False, "error": f"invalid request: {e}"}

        if cls._queue is None or not cls._running:
            return {"id": rid, "ok": False, "error": "server not running"}

        work = {"id": rid, "op": op, "args": args, "event": threading.Event()}
        cls._queue.put(work)
        wait_timeout = _OP_PUMP_TIMEOUT_OVERRIDES.get(op, _PUMP_TIMEOUT)
        if not work["event"].wait(timeout=wait_timeout):
            return {"id": rid, "ok": False, "error": "timeout waiting for editor main thread"}
        if work.get("ok"):
            return {"id": rid, "ok": True, "result": work.get("result")}
        return {"id": rid, "ok": False, "error": work.get("error")}

    # ════════════════════════════════════════════════════════════
    # 主线程 pump（EditorLayer.OnUpdate 每帧调用）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def pump(cls, max_ops: int = _MAX_OPS_PER_FRAME) -> None:
        """取队列中的命令在本线程执行（每帧限量，保证帧率）。"""
        # 主线程维护点: 扩展挂起的停用请求（窗口 X 关闭等 — 每帧, 与 op 同线程）
        try:
            from Application.Editor.Extensions.ExtensionManager import ExtensionManager
            ExtensionManager.consume_pending_disables()
        except Exception:  # noqa: BLE001 — 无扩展体系环境跳过
            pass
        q = cls._queue
        if q is None:
            return
        for _ in range(max_ops):
            try:
                work = q.get_nowait()
            except queue.Empty:
                return
            try:
                handler = cls._ops.get(work["op"])
                if handler is None:
                    handler = cls._ext_ops.get(work["op"])
                if handler is None:
                    raise ValueError(
                        f"unknown op: '{work['op']}' "
                        f"(core: {len(cls._ops)}; extension ops: {', '.join(sorted(cls._ext_ops)) or 'none'} "
                        f"— see extension.list)"
                    )
                work["result"] = handler(work["args"])
                work["ok"] = True
            except Exception as e:  # noqa: BLE001
                work["ok"] = False
                work["error"] = f"{type(e).__name__}: {e}"
            tag = "ok" if work.get("ok") else f"ERR {work.get('error')}"
            print(f"[Live] id={work['id']} op={work['op']} → {tag}")
            work["event"].set()

    # ════════════════════════════════════════════════════════════
    # op 处理器（全部在主线程执行; 复用编辑器现有 API）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _register_ops(cls) -> None:
        cls._ops = {
            "sim.play": cls._op_sim_play,
            "sim.stop": cls._op_sim_stop,
            "sim.state": cls._op_sim_state,
            "view.set_mode": cls._op_view_set_mode,
            "view.set_grid": cls._op_view_set_grid,
            "camera.get": cls._op_camera_get,
            "camera.set": cls._op_camera_set,
            "graph.list": cls._op_graph_list,
            "graph.add": cls._op_graph_add,
            "graph.link": cls._op_graph_link,
            "graph.set_props": cls._op_graph_set_props,
            "graph.export": cls._op_graph_export,
            "graph.import": cls._op_graph_import,
            "graph.validate.start": cls._op_graph_validate_start,
            "graph.validate.state": cls._op_graph_validate_state,
            "graph.validate.report": cls._op_graph_validate_report,
            "graph.validate.cancel": cls._op_graph_validate_cancel,
            "project.open": cls._op_project_open,
            "project.save": cls._op_project_save,
            "project.export": cls._op_project_export,
            # ── 扩展体系（L1, M0; 扩展 op 本身经 register_extension_ops 增量注册） ──
            "extension.list": cls._op_extension_list,
            "extension.enable": cls._op_extension_enable,
            "extension.disable": cls._op_extension_disable,
            # ── settings（编辑器全局设置; 与设置面板同一业务单点 EditorSettings） ──
            "settings.get": cls._op_settings_get,
            "settings.set": cls._op_settings_set,
            "frame.request": cls._op_frame_request,
            "frame.fetch": cls._op_frame_fetch,
            "threads.snapshot": cls._op_threads_snapshot,
            "renderer.snapshot": cls._op_renderer_snapshot,
            # ── v3: 实体 / 选中 / 组件 / 场景 / 资源 ──
            "entity.list": cls._op_entity_list,
            "entity.get": cls._op_entity_get,
            "entity.add": cls._op_entity_add,
            "entity.rename": cls._op_entity_rename,
            "entity.delete": cls._op_entity_delete,
            "entity.transform": cls._op_entity_transform,
            "entity.visible": cls._op_entity_visible,
            "entity.reparent": cls._op_entity_reparent,
            "selection.get": cls._op_selection_get,
            "selection.set": cls._op_selection_set,
            "selection.clear": cls._op_selection_clear,
            "component.types": cls._op_component_types,
            "component.list": cls._op_component_list,
            "component.add": cls._op_component_add,
            "component.remove": cls._op_component_remove,
            "component.get": cls._op_component_get,
            "component.set": cls._op_component_set,
            "scene.list": cls._op_scene_list,
            "scene.switch": cls._op_scene_switch,
            "scene.create": cls._op_scene_create,
            "scene.save": cls._op_scene_save,
            "scene.load": cls._op_scene_load,
            "resource.list": cls._op_resource_list,
            "resource.find": cls._op_resource_find,
            "resource.material.get": cls._op_resource_material_get,
            "editor.quit": cls._op_editor_quit,
        }

    @staticmethod
    def _op_threads_snapshot(args: dict) -> dict:
        """线程注册表快照（协议: Doc/Dev/threading_protocol.md; 工具: Utils/Dev/thread_probe.py）。"""
        from Application.Core.ThreadRegistry import ThreadRegistry

        return ThreadRegistry.snapshot()

    @staticmethod
    def _op_renderer_snapshot(args: dict) -> dict:
        """渲染器状态快照（协议: Doc/Dev/rendering_protocol.md）。

        后端类型 / GL 信息 (渲染线程采集缓存) / 资源计数 / 视口 / 帧统计。
        无渲染器（无头/未初始化）→ available=false, 不报错。
        """
        from Application.Editor.EditorHost import EditorHost

        renderer = (getattr(EditorHost, "editor_renderer", None)
                    or getattr(EditorHost, "renderer", None))
        if renderer is None:
            return {"available": False, "reason": "no renderer (headless / not initialized)"}

        def _count(attr: str) -> int:
            return len(getattr(renderer, attr, None) or {})

        stats: dict = {}
        try:
            stats = EditorHost._get_profiler().get_current_stats()
        except Exception:  # noqa: BLE001
            pass
        # overlay 真身: OpenGL 后端存于 _resources._overlay_gpu_resources（基类占位字典未使用）
        overlay_res = (getattr(renderer, "_overlay_gpu_resources", None)
                       or getattr(renderer, "registered_overlays", None) or {})
        overlays = sorted(overlay_res.keys())
        return {
            "available": True,
            "backend": type(renderer).__name__,
            "gl": dict(getattr(renderer, "gl_info", None) or {}),
            "viewport": [int(getattr(renderer, "viewport_width", 0)),
                         int(getattr(renderer, "viewport_height", 0))],
            "counts": {
                "entities": _count("registered_entities"),
                "meshes": _count("registered_meshes"),
                "shaders": _count("registered_shaders"),
                "textures": _count("registered_textures"),
                "overlays": len(overlay_res),
            },
            "overlays": overlays,
            "stats": stats,
        }

    @staticmethod
    def _op_sim_play(args: dict) -> dict:
        """Run 按钮语义 — 请求 PIE 启动（主线程帧末由 SimulationController 消费）。"""
        from Application.Editor.UI.controllers.SimulationController import (
            SimulationController,
            SimulationState,
        )

        if SimulationController.get_state() != SimulationState.STOPPED:
            return {
                "requested": False,
                "state": SimulationController.get_state_label(),
                "note": "already running/paused",
            }
        SimulationController.play()
        return {"requested": True, "state": "pending_start"}

    @staticmethod
    def _op_view_set_mode(args: dict) -> dict:
        """场景类型按钮语义（Scene Type: 3D / 2D / Overlay）— 与 ScenePanel 按钮同路径。

        ① SceneBrowserController.set_game_type: 写 scene.game_type（决定 PIE 启动时用哪台
           场景摄像机; game_type=2d → 运行时使用 DefaultCamera2D 俯视正交）;
        ② ViewportController.switch_to_*: 编辑器视口（EditorCamera）切换 + 矩阵刷新。
        无活跃场景时（无头环境）只执行 ②。
        """
        from Application.Editor.UI.controllers.ViewportController import ViewportController

        mode = str(args.get("mode", "2d")).lower()
        if mode not in ("2d", "3d", "overlay"):
            raise ValueError(f"unsupported mode: {mode!r} (expected '2d', '3d' or 'overlay')")

        game_type = None
        try:
            from Application.Editor.EditorHost import EditorHost
            from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController
            if getattr(EditorHost, "scene", None) is not None:
                SceneBrowserController.set_game_type(mode)
                game_type = SceneBrowserController.get_game_type()
        except Exception as e:  # noqa: BLE001 — 场景侧失败不阻塞视口切换
            game_type = f"<scene error: {e}>"

        if mode == "2d":
            ViewportController.switch_to_2d()
        elif mode == "3d":
            ViewportController.switch_to_3d()
        else:
            ViewportController.switch_to_overlay()
        return {"mode": mode, "label": ViewportController.get_mode_label(), "game_type": game_type}

    @staticmethod
    def _op_view_set_grid(args: dict) -> dict:
        """显示/隐藏编辑器网格 — 与 View 菜单 Show Grid 同路径 (Grid.set_visible)。"""
        from Application.Editor.Gizmos.Grid import Grid

        if "visible" not in args:
            raise ValueError("visible is required (true/false)")
        state = Grid.set_visible(bool(args.get("visible")))
        return {"visible": state}

    @staticmethod
    def _op_sim_stop(args: dict) -> dict:
        """Stop 按钮语义 — 请求 PIE 停止（主线程帧末由 SimulationController 消费）。"""
        from Application.Editor.UI.controllers.SimulationController import (
            SimulationController,
            SimulationState,
        )

        if SimulationController.get_state() == SimulationState.STOPPED:
            return {"requested": False, "state": "Stopped", "note": "already stopped"}
        SimulationController.stop()
        return {"requested": True, "state": "pending_stop"}

    @staticmethod
    def _op_sim_state(args: dict) -> dict:
        """模拟状态查询（只读）— state: Stopped / Running / Paused; runtime_alive: PIE 线程存活。"""
        from Application.Editor.UI.controllers.SimulationController import SimulationController

        try:
            from Application.Runtime.GameRuntime import GameRuntime
            running = bool(GameRuntime.is_running())
        except Exception:  # noqa: BLE001
            running = False
        return {"state": SimulationController.get_state_label(), "runtime_alive": running,
                "last_error": getattr(SimulationController, "last_error", "")}

    @staticmethod
    def _op_camera_get(args: dict) -> dict:
        """读取场景摄像机实体（role: '3d' / '2d' / 'overlay'）。"""
        from Application.Core.Scene.BasicComponents import Camera, Transform

        role = str(args.get("role", "3d")).lower()
        scene, eid = _camera_entity_for_role(role)
        xform = scene.GetComponent(eid, Transform)
        cam = scene.GetComponent(eid, Camera)
        projection = getattr(cam.projection_type, "value", str(cam.projection_type))
        return {
            "role": role,
            "entity_id": int(eid),
            "position": [float(xform.position_x), float(xform.position_y), float(xform.position_z)],
            "rotation": [float(xform.rotation_x), float(xform.rotation_y), float(xform.rotation_z)],
            "projection": projection,
            "fov": float(cam.fov),
            "ortho_size": float(cam.ortho_size),
            "near_plane": float(cam.near_plane),
            "far_plane": float(cam.far_plane),
        }

    @staticmethod
    def _op_camera_set(args: dict) -> dict:
        """修改场景摄像机实体（仅编辑器场景; 只改传入字段）。

        args: role, 可选 position / rotation（[x,y,z]）、projection（'persp'|'ortho'）、
              ortho_size / fov / near_plane / far_plane。
        """
        from Application.Core.Scene.BasicComponents import ProjectionType

        role = str(args.get("role", "3d")).lower()
        scene, eid = _camera_entity_for_role(role)

        position = args.get("position")
        rotation = args.get("rotation")
        if position is not None:
            if len(position) != 3:
                raise ValueError("position must be [x, y, z]")
            scene.SetEntityTransform(eid, position_xyz=tuple(float(v) for v in position))
        if rotation is not None:
            if len(rotation) != 3:
                raise ValueError("rotation must be [x, y, z]")
            scene.SetEntityTransform(eid, rotation_xyz=tuple(float(v) for v in rotation))

        cam_kwargs: dict = {}
        if args.get("projection") is not None:
            p = str(args["projection"]).lower()
            if p in ("persp", "perspective"):
                cam_kwargs["projection_type"] = ProjectionType.PERSPECTIVE
            elif p in ("ortho", "orthographic"):
                cam_kwargs["projection_type"] = ProjectionType.ORTHOGRAPHIC
            else:
                raise ValueError(f"unsupported projection: {p!r} (expected 'persp' or 'ortho')")
        for key in ("ortho_size", "fov", "near_plane", "far_plane"):
            if args.get(key) is not None:
                cam_kwargs[key] = float(args[key])
        if cam_kwargs:
            scene.SetCameraProperties(eid, **cam_kwargs)
        return LiveCommandServer._op_camera_get({"role": role})

    @staticmethod
    def _op_graph_list(args: dict) -> dict:
        """节点图只读快照（nodes: id/type/props/pins; links: from_pin/to_pin）。"""
        canvas = _node_canvas()
        nodes = [
            {
                "id": int(nid),
                "type": inst.node_type,
                "props": dict(inst.props),
                "pins": {str(name): int(pid) for name, pid in inst.pin_ids.items()},
            }
            for nid, inst in canvas.nodes.items()
        ]
        links = [
            {"id": int(lid), "from_pin": int(lk.from_pin), "to_pin": int(lk.to_pin)}
            for lid, lk in canvas.links.items()
        ]
        return {"nodes": nodes, "links": links}

    @staticmethod
    def _op_graph_add(args: dict) -> dict:
        """添加节点（等同 Add 菜单 — 同一 canvas API）。args: type, props(可选), position(可选)。"""
        from Application.Core.NodeGraph import _TYPES

        type_name = str(args.get("type", ""))
        if type_name not in _TYPES:
            raise ValueError(f"unknown node type: {type_name!r}")
        pos = args.get("position") or (80.0, 80.0)
        canvas = _node_canvas()
        nid = int(canvas.add_node(type_name, (float(pos[0]), float(pos[1]))))
        props = args.get("props") or {}
        if props:
            canvas.nodes[nid].props.update(dict(props))
        return {"node_id": nid, "type": type_name, "props": dict(canvas.nodes[nid].props)}

    @staticmethod
    def _op_graph_set_props(args: dict) -> dict:
        """更新节点属性（等同内联控件改属性）。args: node, props。"""
        canvas = _node_canvas()
        nid = int(args.get("node", -1))
        inst = canvas.nodes.get(nid)
        if inst is None:
            raise ValueError(f"node {nid} not found")
        props = args.get("props") or {}
        inst.props.update(dict(props))
        return {"node_id": nid, "props": dict(inst.props)}

    @staticmethod
    def _op_graph_link(args: dict) -> dict:
        """连接两个引脚（等同画布拖线）。args: from={node,pin}, to={node,pin}。"""
        canvas = _node_canvas()

        def _resolve(spec: object, side: str) -> int:
            if not isinstance(spec, dict) or "node" not in spec or "pin" not in spec:
                raise ValueError(f"{side} must be {{'node': int, 'pin': str}}")
            nid = int(spec["node"])
            inst = canvas.nodes.get(nid)
            if inst is None:
                raise ValueError(f"node {nid} not found")
            pin_name = str(spec["pin"])
            pid = inst.pin_ids.get(pin_name)
            if pid is None:
                raise ValueError(
                    f"pin {pin_name!r} not found on node {nid} "
                    f"(available: {', '.join(inst.pin_ids)})"
                )
            return int(pid)

        lid = int(canvas.add_link(
            _resolve(args.get("from"), "from"),
            _resolve(args.get("to"), "to"),
        ))
        return {"link_id": lid}

    # ── v4: 图校验（引擎内服务） / 图导入导出 / 工程 ──

    @staticmethod
    def _op_graph_validate_start(args: dict) -> dict:
        """启动节点图校验任务（静态 + 干跑, worker 线程; 立即返回 task_id）。

        args:
          source: "canvas"（当前画布快照, 默认）| "graph"（直接传 graph dict）
          graph:  仅 source="graph" 时必填
          frames / verbose / seed: 干跑选项（默认 360 帧 / true / 0）
        """
        from Application.Core.NodeGraph.validation import get_service

        source = str(args.get("source") or "canvas")
        if source == "canvas":
            graph = _node_canvas().to_dict()
        elif source == "graph":
            graph = args.get("graph")
            if not isinstance(graph, dict) or "nodes" not in graph:
                raise ValueError("graph must be a dict with 'nodes' (or use source='canvas')")
        else:
            raise ValueError(f"unknown source: {source!r} (expected 'canvas' or 'graph')")

        options = {
            "frames": args.get("frames"),
            "verbose": args.get("verbose"),
            "seed": args.get("seed"),
        }
        result = get_service().start(graph, options)
        result["source"] = source
        return result

    @staticmethod
    def _op_graph_validate_state(args: dict) -> dict:
        """校验任务状态（task_id 省略 → 最新任务）。"""
        from Application.Core.NodeGraph.validation import get_service

        return get_service().state(args.get("task_id"))

    @staticmethod
    def _op_graph_validate_report(args: dict) -> dict:
        """取回校验报告（task_id 省略 → 最新; save_path 可落盘 .json/.txt）。"""
        from Application.Core.NodeGraph.validation import get_service

        service = get_service()
        task_id = args.get("task_id")
        report = service.report(task_id)
        if report is None:
            latest = service.latest_task_id()
            if task_id is not None and latest is not None:
                raise ValueError(f"no report for task {task_id} (latest task: {latest})")
            raise ValueError("no validation report yet — run graph.validate.start first")
        result: dict = {"found": True, "report": report}
        save_path = args.get("save_path")
        if save_path:
            result["saved_path"] = _save_validation_report(report, str(save_path))
        return result

    @staticmethod
    def _op_graph_validate_cancel(args: dict) -> dict:
        """取消当前校验任务（帧间生效）。"""
        from Application.Core.NodeGraph.validation import get_service

        return get_service().cancel(args.get("task_id"))

    @staticmethod
    def _op_graph_export(args: dict) -> dict:
        """导出当前画布为 graph JSON（含 _rules 文档; 可落盘 path）。

        args: path(可选, 落盘; 自动补 .json), include_rules(默认 true), inline(默认 true — 返回完整 JSON)
        实现: Application/Core/NodeGraph/graph_io.export_graph（与 GUI Export 同源）。
        """
        from Application.Core.NodeGraph.graph_io import export_graph

        canvas = _node_canvas()
        result = export_graph(
            canvas,
            path=args.get("path"),
            include_rules=args.get("include_rules") is not False,
            inline=bool(args.get("inline", True)),
        )
        if result["saved_path"]:
            print(f"[Live] graph exported: {result['nodes']} nodes → {result['saved_path']}")
        return result

    @staticmethod
    def _op_graph_import(args: dict) -> dict:
        """导入 graph JSON 替换当前画布（validate_first 默认开 — 静态 error 时拒绝）。

        args: graph(dict) 或 path(.json 文件), validate_first(默认 true)
        实现: graph_io.prepare_import + apply_to_canvas（与 GUI Import 同源）。
        顺序契约: 读入/校验先于画布获取（无画布时仍先报输入错误 — 回环测试依赖）。
        """
        from Application.Core.NodeGraph.graph_io import apply_to_canvas, prepare_import

        data, refused = prepare_import(
            graph=args.get("graph"),
            path=args.get("path"),
            validate_first=bool(args.get("validate_first", True)),
        )
        if refused is not None:
            return refused
        canvas = _node_canvas()
        result = apply_to_canvas(canvas, data)
        print(f"[Live] graph imported: {result['nodes']} nodes, {result['links']} links")
        return result

    @staticmethod
    def _op_project_open(args: dict) -> dict:
        """打开 .myproj 工程（等同 File ▸ Open Project — 资源 + 场景全加载, 启动场景激活）。

        args: path(.myproj)
        """
        from Application.Editor.ProjectManager import ProjectManager
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

        path = str(args.get("path") or "")
        if not path:
            raise ValueError("path is required (.myproj)")
        if not os.path.isfile(path):
            raise ValueError(f"project file not found: {path}")

        previous_name = ProjectManager.get_project_name() if ProjectManager.is_open() else ""
        previous_saved = ProjectManager.is_saved() if ProjectManager.is_open() else True

        ok = bool(ProjectManager.open_project(path))
        if not ok:
            raise RuntimeError(f"failed to open project: {path}")

        result: dict = {
            "opened": True,
            "name": ProjectManager.get_project_name(),
            "path": ProjectManager.get_project_path(),
            "scenes": SceneBrowserController.get_scene_names(),
            "active": SceneBrowserController.get_active_scene_name(),
        }
        if previous_name and not previous_saved:
            result["warning"] = f"previous project '{previous_name}' had unsaved changes"
        return result

    @staticmethod
    def _op_project_save(args: dict) -> dict:
        """保存工程（等同 File ▸ Save Project；提供 path 则为 Save As 语义 — 换根保存, 不复制文件）。

        args: path? (.myproj — 省略 = 保存到当前路径, 需已保存过)
        """
        from Application.Editor.ProjectManager import ProjectManager

        path = args.get("path")
        if path:
            if not ProjectManager.save_project_as(str(path)):
                raise RuntimeError(f"Save As failed: {path}")
            mode = "save_as"
        else:
            if not ProjectManager.get_project_path():
                raise ValueError(
                    "project is not saved yet — pass 'path' (Save As) for the first save")
            if not ProjectManager.save_project():
                raise RuntimeError("save_project failed — see editor log")
            mode = "save"
        return {
            "saved": True,
            "mode": mode,
            "path": ProjectManager.get_project_path(),
            "name": ProjectManager.get_project_name(),
        }

    @staticmethod
    def _op_project_export(args: dict) -> dict:
        """导出工程包（等同 File ▸ Export；include_player=true 时附游戏层 → 自包含成品）。

        args: target_parent (str 必填 — 输出到 <target_parent>/<ProjectName>/),
              include_player (bool, 默认 true — false = 纯工程包不含运行时)

        注意: 游戏层复制 runtime 镜像 (数百 MB / 上万文件), 耗时可达分钟级;
        客户端超时已在 op 注册表 call_timeout 放宽 (600s)。
        """
        from Application.Editor.ProjectManager import ProjectManager

        target = str(args.get("target_parent") or "")
        if not target:
            raise ValueError("target_parent is required (parent dir for <Name>/ bundle)")
        include_player = bool(args.get("include_player", True))
        summary = ProjectManager.export_project_bundle(target, include_player=include_player)
        if not summary:
            raise RuntimeError(
                "export failed — check editor log (project unsaved / target missing / "
                "non-empty non-export folder)")
        result = dict(summary)
        result["exported"] = True
        result["include_player"] = include_player
        return result

    # ════════════════════════════════════════════════════════════
    # 扩展 op 注册表（增量扫描通道 — 见 Doc/ExtDev/extension_dev_protocol.md §9）
    # ════════════════════════════════════════════════════════════

    @classmethod
    def register_extension_ops(cls, owner_id: str, ops: dict, summaries: dict | None = None) -> None:
        """注册扩展 op（强制命名 `ext.<owner_id>.*`）。由 ExtensionManager/ctx.ops 调用。"""
        prefix = f"ext.{owner_id}."
        for name, fn in ops.items():
            if not str(name).startswith(prefix):
                raise ValueError(f"extension op must start with '{prefix}': {name!r}")
            cls._ext_ops[str(name)] = fn
            cls._ext_ops_owner[str(name)] = owner_id
            if summaries and name in summaries:
                cls._ext_ops_summary[str(name)] = str(summaries[name])

    @classmethod
    def unregister_extension_ops(cls, owner_id: str) -> list[str]:
        """注销某扩展的全部 op（disable/unload 时调用）。返回被移除的 op 名。"""
        removed = [n for n, o in cls._ext_ops_owner.items() if o == owner_id]
        for n in removed:
            cls._ext_ops.pop(n, None)
            cls._ext_ops_owner.pop(n, None)
            cls._ext_ops_summary.pop(n, None)
        return removed

    @classmethod
    def extension_ops_snapshot(cls) -> dict:
        """当前扩展 op 快照 {op: {owner, summary}}（agent 侧经 `extension.list` 发现）。"""
        return {
            n: {"owner": cls._ext_ops_owner.get(n, ""), "summary": cls._ext_ops_summary.get(n, "")}
            for n in sorted(cls._ext_ops)
        }

    # ── extension.* ops ──

    @staticmethod
    def _op_extension_list(args: dict) -> dict:
        """列出扩展（发现/装载状态/贡献 ops）+ 已增量扫描到的扩展 op 清单。"""
        from Application.Editor.Extensions.ExtensionManager import ExtensionManager

        ExtensionManager.ensure_init()
        return {
            "extensions": ExtensionManager.list_infos(),
            "extension_ops": LiveCommandServer.extension_ops_snapshot(),
        }

    @staticmethod
    def _op_extension_enable(args: dict) -> dict:
        """启用扩展（加载 on_load/on_enable; 等同 Extensions 菜单勾选; 持久化）。"""
        ext_id = str(args.get("id") or "")
        if not ext_id:
            raise ValueError("id is required")
        from Application.Editor.Extensions.ExtensionManager import ExtensionManager

        info = ExtensionManager.enable(ext_id)
        return {"extension": info, "extension_ops": LiveCommandServer.extension_ops_snapshot()}

    @staticmethod
    def _op_extension_disable(args: dict) -> dict:
        """停用扩展（on_disable/on_unload + 注销其全部 ext.<id>.* ops; 持久化）。"""
        ext_id = str(args.get("id") or "")
        if not ext_id:
            raise ValueError("id is required")
        from Application.Editor.Extensions.ExtensionManager import ExtensionManager

        info = ExtensionManager.disable(ext_id)
        return {"extension": info, "extension_ops": LiveCommandServer.extension_ops_snapshot()}

    # ── settings.* ops（UI 同路径: Settings 面板 ▸ Common / Edit ▸ Preferences） ──

    @staticmethod
    def _op_settings_get(args: dict) -> dict:
        """读取编辑器设置（省略 key = 全量; UI: Settings 面板 Common 页）。"""
        from Application.Editor.EditorSettings import EditorSettings

        key = str(args.get("key") or "")
        if not key:
            return {"settings": EditorSettings.all()}
        return {"key": key, "value": EditorSettings.get(key)}

    @staticmethod
    def _op_settings_set(args: dict) -> dict:
        """写入编辑器设置（校验+钳制 → 立即持久化 → 下一渲染帧生效）。"""
        from Application.Editor.EditorSettings import EditorSettings

        key = str(args.get("key") or "")
        if not key:
            raise ValueError("key is required")
        if "value" not in args:
            raise ValueError("value is required")
        value = EditorSettings.set(key, args.get("value"))
        return {"key": key, "value": value, "applied": "next render frame"}

    @staticmethod
    def _op_frame_request(args: dict) -> dict:
        """请求抓取目标窗口“下一渲染帧”（立即返回; 结果用 frame.fetch 取回）。

        target: 'editor'（编辑器窗口）/ 'pie'（运行时窗口 — 必须运行中）。
        """
        target = str(args.get("target", "editor")).lower()
        engine_cls = _capture_engine_cls(target)
        info = engine_cls.request_capture()
        return {"target": target, "generation": int(info["generation"])}

    @staticmethod
    def _op_frame_fetch(args: dict) -> dict:
        """按代数取帧; 就绪时随回执附带二进制负载（result.binary_bytes 声明长度）。

        state: pending（未抓到）/ superseded（该代已被更新请求覆盖）/ error / ready。
        """
        target = str(args.get("target", "editor")).lower()
        engine_cls = _capture_engine_cls(target)
        raw_gen = args.get("generation")
        generation = int(raw_gen) if raw_gen is not None else None

        info = engine_cls.fetch_capture(generation)
        result: dict = {
            "target": target,
            "generation": generation,
            "ready": bool(info.get("ready")),
            "state": info.get("state"),
        }
        if not info.get("ready"):
            if info.get("error"):
                result["error"] = info["error"]
            if info.get("latest_generation") is not None:
                result["latest_generation"] = int(info["latest_generation"])
            return result
        payload = info["payload"]
        result.update({
            "generation": int(info["generation"]),
            "width": int(info["width"]),
            "height": int(info["height"]),
            "format": "rgba8",
            "origin": "bottom-left",
            "binary_bytes": len(payload),
            "_payload": payload,  # socket 线程: 行后追加裸负载; 不入 JSON
        })
        return result

    @staticmethod
    def _op_editor_quit(args: dict) -> dict:
        """关闭引擎 — 窗口关闭按钮语义（优先走 GLFW 正常关闭流程）。"""
        from Application.Editor.EditorHost import EditorHost

        window = None
        try:
            window = EditorHost.get_window()
        except Exception:  # noqa: BLE001
            window = None
        glfw_win = getattr(window, "glfw_window", None) if window is not None else None
        if glfw_win is not None:
            import glfw

            glfw.set_window_should_close(glfw_win, True)
            return {"closing": True, "via": "window_close_request"}
        EditorHost.run_state = False
        return {"closing": True, "via": "run_state"}

    # ════════════════════════════════════════════════════════════
    # op 处理器 — v3: 实体 / 选中 / 组件 / 场景 / 资源
    # （全部复用 SceneBrowserController / SelectionController / EditorHost / ResourceManager 现有 API）
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _op_entity_list(args: dict) -> dict:
        """实体列表（roots_only=true 时仅根实体）。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

        _require_editor_scene()
        infos = SceneBrowserController.get_all_entity_infos()
        if bool(args.get("roots_only")):
            roots = set(SceneBrowserController.get_root_entities())
            infos = [i for i in infos if i["entity_id"] in roots]
        return {"entities": infos, "count": len(infos)}

    @staticmethod
    def _op_entity_get(args: dict) -> dict:
        """实体快照: 名称/组件/层级/可见性/transform（编辑器坐标, 角度制）。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

        eid, extras = _resolve_entity(args)
        info = SceneBrowserController.get_entity_info(eid) or {}
        summary = SceneBrowserController.get_summary(eid)
        result: dict = {
            "entity_id": eid,
            "name": info.get("name", ""),
            "components": SceneBrowserController.get_entity_components(eid),
            "parent": SceneBrowserController.get_entity_parent(eid),
            "children": SceneBrowserController.get_entity_children(eid),
            "editor_visible": SceneBrowserController.is_editor_visible(eid),
            "render_visible": bool(info.get("render_visible", False)),
            "has_camera": bool(info.get("has_camera", False)),
            "mesh_id": info.get("mesh_id", -1),
            "material_id": info.get("material_id", -1),
        }
        if summary is not None:
            result["transform"] = {
                "position": [float(v) for v in summary.position],
                "rotation_deg": [float(v) for v in summary.rotation],
                "scale": [float(v) for v in summary.scale],
            }
        result.update(extras)
        return result

    @staticmethod
    def _op_entity_add(args: dict) -> dict:
        """新建实体（仅 Transform）。与面板 +New 一致: 有选中时成为其子级; 可用 parent 显式指定/解除。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

        _require_editor_scene()
        name = str(args.get("name") or "")
        eid = SceneBrowserController.add_entity(name)
        if "parent" in args:
            parent = args.get("parent")
            if parent in (None, "none", 0):
                SceneBrowserController.set_entity_parent(eid, 0)
            else:
                SceneBrowserController.set_entity_parent(eid, _entity_id_from_value(parent))
        result = LiveCommandServer._op_entity_get({"id": eid})
        result["created"] = True
        return result

    @staticmethod
    def _op_entity_rename(args: dict) -> dict:
        """重命名实体。名称不强制唯一 — 返回重名警告与模板索引提醒。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

        eid, extras = _resolve_entity(args)
        new_name = str(args.get("new_name") or "").strip()
        if not new_name:
            raise ValueError("new_name is required")
        SceneBrowserController.set_name(eid, new_name)
        result: dict = {"entity_id": eid, "name": new_name}
        duplicates = [
            i["entity_id"]
            for i in SceneBrowserController.get_all_entity_infos()
            if i["name"] == new_name and i["entity_id"] != eid
        ]
        if duplicates:
            result["duplicate_ids"] = duplicates
            result["warning"] = "name is not unique — 按名索引（如 EntitySpawn 模板）将匹配第一个"
        return result

    @staticmethod
    def _op_entity_delete(args: dict) -> dict:
        """删除实体及其子实体（等同面板 Delete; 删除选中者会清除选中）。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

        eid, extras = _resolve_entity(args)
        ok = SceneBrowserController.delete_entity(eid)
        if not ok:
            raise ValueError(f"delete failed: entity {eid} not found")
        return {"deleted": True, "entity_id": eid}

    @staticmethod
    def _op_entity_transform(args: dict) -> dict:
        """设置 transform（编辑器坐标系、角度制、含 NaN/范围钳制 — 与 Inspector 一致）。

        relative=true 时相对调整（位移加法 / 旋转加法 / 缩放乘法 — gizmo 拖拽语义）;
        scale 可传标量（等比缩放）。
        """
        eid, extras = _resolve_entity(args)
        spec = {key: args.get(key) for key in ("position", "rotation", "scale")}
        applied = _apply_transform_fields(
            eid, spec,
            use_local=bool(args.get("local", False)),
            relative=bool(args.get("relative", False)),
        )
        if not applied:
            raise ValueError("nothing to set — provide position / rotation / scale")
        result = LiveCommandServer._op_entity_get({"id": eid})
        result["applied"] = applied
        return result

    @staticmethod
    def _op_entity_visible(args: dict) -> dict:
        """编辑器视口可见性（眼图标）与渲染可见性（MeshRenderer.visible）。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

        eid, extras = _resolve_entity(args)
        changed = False
        if args.get("editor") is not None:
            SceneBrowserController.set_editor_visible(eid, bool(args["editor"]))
            changed = True
        if args.get("render") is not None:
            SceneBrowserController.set_entity_render_visible(eid, bool(args["render"]))
            changed = True
        if not changed:
            raise ValueError("nothing to set — provide editor and/or render")
        info = SceneBrowserController.get_entity_info(eid) or {}
        return {
            "entity_id": eid,
            "editor_visible": SceneBrowserController.is_editor_visible(eid),
            "render_visible": bool(info.get("render_visible", False)),
        }

    @staticmethod
    def _op_entity_reparent(args: dict) -> dict:
        """设置父实体（parent: id/name; None/"none" 解除）。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

        eid, extras = _resolve_entity(args)
        parent = args.get("parent")
        if parent in (None, "none", 0):
            SceneBrowserController.set_entity_parent(eid, 0)
        else:
            pid = _entity_id_from_value(parent)
            if pid == eid:
                raise ValueError("cannot parent an entity to itself")
            SceneBrowserController.set_entity_parent(eid, pid)
        return {
            "entity_id": eid,
            "parent": SceneBrowserController.get_entity_parent(eid),
            "children": SceneBrowserController.get_entity_children(eid),
        }

    @staticmethod
    def _op_selection_get(args: dict) -> dict:
        """当前选中实体（无选中返回 null）。"""
        from Application.Editor.UI.controllers.SelectionController import SelectionController

        eid = SelectionController.get_selected()
        if eid is None:
            return {"entity_id": None}
        scene = getattr(_editor_host(), "scene", None)
        name = scene.GetEntityName(eid) if scene is not None else ""
        return {"entity_id": int(eid), "name": name}

    @staticmethod
    def _op_selection_set(args: dict) -> dict:
        """选中实体（gizmo=true 显示变换 gizmo — 等同视口点选）。"""
        from Application.Editor.UI.controllers.SelectionController import SelectionController

        eid, extras = _resolve_entity(args)
        if bool(args.get("gizmo", True)):
            SelectionController.select_with_gizmo(eid)
            via = "gizmo"
        else:
            SelectionController.select(eid)
            via = "plain"
        return {"entity_id": eid, "via": via}

    @staticmethod
    def _op_selection_clear(args: dict) -> dict:
        """清除选中。"""
        from Application.Editor.UI.controllers.SelectionController import SelectionController

        SelectionController.clear()
        return {"cleared": True}

    @staticmethod
    def _op_component_types(args: dict) -> dict:
        """已注册的组件类型名（注册表）。"""
        scene = _require_editor_scene()
        return {"types": sorted(scene.GetRegisteredComponents().keys())}

    @staticmethod
    def _op_component_list(args: dict) -> dict:
        """实体当前拥有的组件名列表。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

        eid, extras = _resolve_entity(args)
        return {"entity_id": eid, "components": SceneBrowserController.get_entity_components(eid)}

    @staticmethod
    def _op_component_add(args: dict) -> dict:
        """按名添加组件（等同 Inspector Add Component; MeshRenderer 自动绑定 Cube 默认网格）。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

        eid, extras = _resolve_entity(args)
        type_name = _migrate_type_name(str(args.get("type") or ""))
        available = SceneBrowserController.get_available_components()
        if type_name not in available:
            raise ValueError(
                f"unknown component type: {type_name!r} "
                f"(available: {', '.join(sorted(available))})"
            )
        ok = bool(SceneBrowserController.add_component(eid, type_name))
        result = {"entity_id": eid, "type": type_name, "added": ok}
        if not ok:
            result["note"] = "component already present"
        result["components"] = SceneBrowserController.get_entity_components(eid)
        return result

    @staticmethod
    def _op_component_remove(args: dict) -> dict:
        """移除组件（Transform 为实体必需 — 不可移除; MeshRenderer 会同步注销 GPU 资源）。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

        eid, extras = _resolve_entity(args)
        type_name = _migrate_type_name(str(args.get("type") or ""))
        ok = bool(SceneBrowserController.remove_component(eid, type_name))
        return {
            "entity_id": eid,
            "type": type_name,
            "removed": ok,
            "components": SceneBrowserController.get_entity_components(eid),
        }

    @staticmethod
    def _op_component_get(args: dict) -> dict:
        """组件字段快照（DataclassContract.serialize 通用序列化）。

        MeshRenderer 额外附带 meta: 网格与材质的语义化摘要（名称/颜色/shader — 便于“读后再改”）。
        """
        eid, extras = _resolve_entity(args)
        type_name = _migrate_type_name(str(args.get("type") or ""))
        comp = _get_component_by_name(eid, type_name)
        result: dict = {"entity_id": eid, "type": type_name, "fields": comp.serialize()}
        if type_name == "MeshRenderer":
            meta: dict = {}
            mesh_id = result["fields"].get("mesh_id")
            if isinstance(mesh_id, int) and mesh_id >= 0:
                match = next((e for e in _resource_entries("mesh") if e["id"] == mesh_id), None)
                if match is not None:
                    meta["mesh"] = match
            material_id = result["fields"].get("material_id")
            if isinstance(material_id, int) and material_id >= 0:
                try:
                    meta["material"] = LiveCommandServer._op_resource_material_get({"id": material_id})
                except Exception:  # noqa: BLE001 — 摘要失败不影响字段快照
                    pass
            if meta:
                result["meta"] = meta
        return result

    @staticmethod
    def _op_component_set(args: dict) -> dict:
        """修改组件字段（专用路径优先 — Transform/MeshRenderer/Camera 与 UI 同路径）。

        fields 示例:
          Transform:    {"position": [..], "rotation": [..度], "scale": [..标量或三分量]}
                        （配合 local / relative 参数; relative=位移加法/旋转加法/缩放乘法）
          MeshRenderer: {"mesh": "Cube"|id, "material": id|名称, "color": [r,g,b(,a)], "visible": bool,
                         "blend": "opaque"|"alpha",
                         "material_name": str, "shader": id|名称, "uniform": {名: 值},
                         "texture": 名称|id (+"texture_slot"), "texture_add": 名称|id, "texture_remove": slot}
          Camera:       {"fov": .., "ortho_size": .., "near_plane": .., "far_plane": .., "projection": "persp"|"ortho"}
          其它注册组件: {dataclass 字段名: 值}（直写）
        """
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

        eid, extras = _resolve_entity(args)
        type_name = _migrate_type_name(str(args.get("type") or ""))
        fields = args.get("fields") or {}
        if not isinstance(fields, dict) or not fields:
            raise ValueError("fields must be a non-empty object")
        applied: list[str] = []

        if type_name == "Transform":
            unknown = set(fields) - {"position", "rotation", "scale"}
            if unknown:
                raise ValueError(f"unknown Transform field(s): {', '.join(sorted(unknown))}")
            applied.extend(_apply_transform_fields(
                eid, fields,
                use_local=bool(args.get("local", False)),
                relative=bool(args.get("relative", False)),
            ))

        elif type_name == "MeshRenderer":
            mr = _get_component_by_name(eid, "MeshRenderer")
            for key, value in fields.items():
                if key == "color":
                    rgba = [float(c) for c in value]
                    if len(rgba) == 3:
                        rgba.append(1.0)
                    if len(rgba) != 4:
                        raise ValueError("color must be [r,g,b] or [r,g,b,a]")
                    SceneBrowserController.set_material_color(eid, *rgba)
                elif key in ("mesh", "mesh_id"):
                    SceneBrowserController.set_entity_mesh(eid, _resource_id_from_value("mesh", value))
                elif key in ("material", "material_id"):
                    SceneBrowserController.set_entity_material(eid, _resource_id_from_value("material", value))
                elif key == "material_name":
                    SceneBrowserController.set_material_name(eid, str(value))
                elif key == "shader":
                    SceneBrowserController.set_material_shader(eid, _resource_id_from_value("shader", value))
                elif key == "blend":
                    SceneBrowserController.set_material_blend(eid, str(value))
                elif key == "uniform":
                    if not isinstance(value, dict) or not value:
                        raise ValueError("uniform must be a non-empty object {name: value}")
                    from Application.Resource.ResourceManager import ResourceManager
                    mat = ResourceManager.GetMaterial(_require_editor_scene().GetEntityMaterial(eid))
                    invalid = [k for k in value if k not in mat.uniforms_data]
                    if invalid:
                        raise ValueError(
                            f"unknown uniform(s): {', '.join(invalid)} "
                            f"(available: {', '.join(sorted(mat.uniforms_data))})"
                        )
                    for u_name, u_value in value.items():
                        SceneBrowserController.set_material_uniform(eid, u_name, u_value)
                elif key == "texture":
                    slot = int(fields.get("texture_slot", 0))
                    _require_editor_scene().SetEntityTexture(
                        eid, _resource_id_from_value("texture", value), slot=slot)
                elif key == "texture_slot":
                    continue   # 与 texture 搭配使用（单独出现无意义）
                elif key == "texture_add":
                    SceneBrowserController.add_material_texture(
                        eid, _resource_id_from_value("texture", value))
                elif key == "texture_remove":
                    SceneBrowserController.remove_material_texture(eid, int(value))
                elif key == "visible":
                    SceneBrowserController.set_entity_render_visible(eid, bool(value))
                else:
                    if not hasattr(mr, key):
                        raise ValueError(f"unknown MeshRenderer field: {key!r}")
                    setattr(mr, key, value)
                applied.append(key)

        elif type_name == "Camera":
            from Application.Core.Scene.BasicComponents import ProjectionType

            cam_kwargs: dict = {}
            for key, value in fields.items():
                if key == "projection":
                    p = str(value).lower()
                    if p in ("persp", "perspective"):
                        cam_kwargs["projection_type"] = ProjectionType.PERSPECTIVE
                    elif p in ("ortho", "orthographic"):
                        cam_kwargs["projection_type"] = ProjectionType.ORTHOGRAPHIC
                    else:
                        raise ValueError(f"unsupported projection: {value!r} (expected 'persp' or 'ortho')")
                elif key in ("fov", "ortho_size", "near_plane", "far_plane", "aspect_ratio"):
                    cam_kwargs[key] = float(value)
                else:
                    raise ValueError(f"unknown Camera field: {key!r}")
                applied.append(key)
            if cam_kwargs:
                _require_editor_scene().SetCameraProperties(eid, **cam_kwargs)

        else:
            import dataclasses
            from Application.Core.Scene.ComponentRegistry import clamp_component_field

            comp = _get_component_by_name(eid, type_name)
            valid = {f.name for f in dataclasses.fields(comp)}
            for key, value in fields.items():
                if key not in valid:
                    raise ValueError(
                        f"unknown {type_name} field: {key!r} (available: {', '.join(sorted(valid))})"
                    )
                setattr(comp, key, clamp_component_field(type_name, key, value))
                applied.append(key)

        result = LiveCommandServer._op_component_get({"id": eid, "type": type_name})
        result["applied"] = applied
        return result

    @staticmethod
    def _op_scene_list(args: dict) -> dict:
        """场景列表 + 当前活跃场景名。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

        return {
            "scenes": SceneBrowserController.get_scene_names(),
            "active": SceneBrowserController.get_active_scene_name(),
        }

    @staticmethod
    def _op_scene_switch(args: dict) -> dict:
        """切换场景（等同 Scene 下拉选择 — 保存当前/加载/视口/节点图同步全流程）。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

        name = str(args.get("name") or "")
        if not name:
            raise ValueError("name is required")
        ok = bool(SceneBrowserController.switch_scene(name))
        return {"switched": ok, "active": SceneBrowserController.get_active_scene_name()}

    @staticmethod
    def _op_scene_create(args: dict) -> dict:
        """新建场景并设为活跃（等同 + 按钮）。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

        name = str(args.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        SceneBrowserController.create_scene(name)
        return {"created": name, "active": SceneBrowserController.get_active_scene_name()}

    @staticmethod
    def _op_scene_save(args: dict) -> dict:
        """保存当前场景到 .scene 文件（等同 💾; 省略 path 时用最近保存路径）。"""
        from Application.Editor.EditorHost import EditorHost

        scene = EditorHost.get_active_scene()
        path = args.get("path") or getattr(scene, "_file_path", None)
        if not path:
            raise ValueError("no path available — pass 'path' (scene was never saved)")
        path = str(path)
        if not path.endswith(".scene"):
            path += ".scene"
        ok = bool(EditorHost.save_active_scene_to_file(path))
        if ok:
            try:
                from Application.Editor.ProjectManager import ProjectManager
                if ProjectManager.is_open():
                    ProjectManager.set_startup_scene(path)
            except Exception:  # noqa: BLE001 — 启动场景联动失败不影响保存结果
                pass
            print(f"[Live] scene saved: {path}")
        return {"saved": ok, "path": path}

    @staticmethod
    def _op_scene_load(args: dict) -> dict:
        """从 .scene 文件加载并设为活跃（等同 📂）。"""
        from Application.Editor.EditorHost import EditorHost

        path = str(args.get("path") or "")
        if not path:
            raise ValueError("path is required")
        scene = EditorHost.load_scene_from_file(path)
        if scene is None:
            raise ValueError(f"failed to load scene: {path}")
        return {"loaded": True, "path": path, "active": getattr(scene, "name", "")}

    @staticmethod
    def _op_resource_list(args: dict) -> dict:
        """资源列表（kind: mesh/shader/texture/material/prefab）。"""
        kind = str(args.get("kind") or "")
        items = _resource_entries(kind)
        return {"kind": kind, "count": len(items), "items": items}

    @staticmethod
    def _op_resource_find(args: dict) -> dict:
        """按名查找资源（线性扫描; 名称不保证唯一 — 返回全部匹配）。"""
        kind = str(args.get("kind") or "")
        name = str(args.get("name") or "")
        if not name:
            raise ValueError("name is required")
        matches = [e for e in _resource_entries(kind) if e.get("name") == name]
        return {"kind": kind, "name": name, "matches": matches, "count": len(matches)}

    @staticmethod
    def _op_resource_material_get(args: dict) -> dict:
        """材质详情（名称/shader/颜色/纹理槽/uniform 键）。"""
        from Application.Resource.ResourceManager import ResourceManager

        ref = args.get("id", args.get("name"))
        if ref is None:
            raise ValueError("either 'id' or 'name' is required")
        if isinstance(ref, int):
            mid = int(ref)
        elif str(ref).isdigit():
            mid = int(str(ref))
        else:
            matches = [e["id"] for e in _resource_entries("material") if e.get("name") == str(ref)]
            if not matches:
                raise ValueError(f"material not found: {ref!r}")
            mid = int(matches[0])
        mat = ResourceManager.GetMaterial(mid)
        result: dict = {
            "id": mid,
            "name": getattr(mat, "name", None),
            "shader_id": int(getattr(mat, "shader_id", 0)),
            "blend": getattr(mat, "blend", "opaque"),
            "texture_ids": list(getattr(mat, "texture_id_list", []) or []),
            "uniform_keys": sorted(getattr(mat, "uniforms_data", {}).keys()),
        }
        try:
            result["shader_name"] = ResourceManager.GetShaderName(result["shader_id"])
        except Exception:  # noqa: BLE001
            pass
        color = ResourceManager.GetMaterialColor(mid)
        if color is not None:
            result["color"] = [float(c) for c in color]
        return result


# ════════════════════════════════════════════════════════════════
# 工具: 目标解析（模块级; 不接触编辑器状态, 只做类/实体查找）
# ════════════════════════════════════════════════════════════════


def _capture_engine_cls(target: str):
    """抓帧目标 → Engine 子类（editor=EditorHost / pie=GameRuntime, 需运行中）。"""
    if target == "editor":
        from Application.Editor.EditorHost import EditorHost
        return EditorHost
    if target == "pie":
        from Application.Runtime.GameRuntime import GameRuntime
        try:
            running = bool(GameRuntime.is_running())
        except Exception:  # noqa: BLE001 — 未初始化/属性缺失均视为未运行
            running = False
        if not running:
            raise ValueError("PIE is not running — start it first (sim.play)")
        return GameRuntime
    raise ValueError(f"unknown target: {target!r} (expected 'editor' or 'pie')")


def _camera_entity_for_role(role: str):
    """摄像机角色 → (编辑器场景 SceneManager, 实体 ID)。"""
    from Application.Editor.EditorHost import EditorHost

    scene = getattr(EditorHost, "scene", None)
    if scene is None:
        raise ValueError("no active scene")
    ids = {
        "3d": getattr(scene, "main_camera_id", None),
        "2d": getattr(scene, "main_camera_2d_id", None),
        "overlay": getattr(scene, "main_camera_overlay_id", None),
    }
    if role not in ids:
        raise ValueError(f"unknown camera role: {role!r} (expected '3d', '2d' or 'overlay')")
    eid = ids[role]
    if eid is None:
        raise ValueError(f"camera role {role!r} has no entity in current scene")
    return scene, int(eid)


def _node_canvas():
    """Node Editor 面板的画布（与 PIE 注入的是同一实例）。"""
    from Application.Editor.UI.UIManager import UIManager

    panel = UIManager.find("Node Editor")
    canvas = getattr(panel, "_canvas", None) if panel is not None else None
    if canvas is None:
        raise ValueError("node editor canvas not available (panel not created yet)")
    return canvas


def _editor_host():
    """EditorHost 类（延迟导入, 避免模块级循环）。"""
    from Application.Editor.EditorHost import EditorHost
    return EditorHost


def _require_editor_scene():
    """编辑器活跃场景（SceneManager 实例; 无则受控错误）。"""
    scene = getattr(_editor_host(), "scene", None)
    if scene is None:
        raise ValueError("no active scene")
    return scene


# 旧组件名迁移表 — MCP/CLI 全链兼容 (DirectionalLight 已改名为 Light)
_COMP_TYPE_MIGRATIONS = {
    "DirectionalLight": "Light",
}


def _migrate_type_name(name: str) -> str:
    """旧组件名 → 当前注册名（无迁移则原样返回）。"""
    return _COMP_TYPE_MIGRATIONS.get(name, name)


def _resolve_entity(args: dict) -> tuple[int, dict]:
    """实体寻址: {"id": N} 或 {"name": "..."} → (eid, extras)。

    名称不强制唯一（引擎不做查重）— 命中多个时返回首个 + duplicate_ids 警告。
    """
    scene = _require_editor_scene()
    raw_id = args.get("id")
    if raw_id is not None:
        eid = int(raw_id)
        if not scene.EntityExists(eid):
            raise ValueError(f"entity id {eid} not found")
        return eid, {}
    name = args.get("name")
    if not name:
        raise ValueError("either 'id' or 'name' is required")
    eid = scene.GetEntityByName(str(name))
    if eid < 0:
        raise ValueError(f"entity not found: {name!r}")
    extras: dict = {}
    duplicates = [
        i["entity_id"]
        for i in scene.GetAllEntityInfos()
        if i["name"] == str(name) and i["entity_id"] != eid
    ]
    if duplicates:
        extras["duplicate_ids"] = duplicates
        extras["warning"] = "name is not unique — first match returned"
    return int(eid), extras


def _entity_id_from_value(value) -> int:
    """父实体引用: int → id; str → name。"""
    if isinstance(value, bool):
        raise ValueError("entity reference must be int id or string name")
    if isinstance(value, int):
        return int(value)
    scene = _require_editor_scene()
    eid = scene.GetEntityByName(str(value))
    if eid < 0:
        raise ValueError(f"entity not found: {value!r}")
    return int(eid)


def _get_component_by_name(entity_id: int, type_name: str):
    """按注册表名取实体组件实例（不存在则受控错误）。"""
    scene = _require_editor_scene()
    registered = scene.GetRegisteredComponents()
    comp_cls = registered.get(type_name)
    if comp_cls is None:
        raise ValueError(
            f"unknown component type: {type_name!r} "
            f"(available: {', '.join(sorted(registered))})"
        )
    if not scene.HasComponent(entity_id, comp_cls):
        raise ValueError(f"entity {entity_id} has no component {type_name!r}")
    return scene.GetComponent(entity_id, comp_cls)


_RESOURCE_KINDS = ("mesh", "shader", "texture", "material", "prefab")


def _resource_entries(kind: str) -> list[dict]:
    """资源列表（id/name/builtin_name/path 概要; 名称不保证唯一）。"""
    from Application.Resource.ResourceManager import ResourceManager

    containers = {
        "mesh": ResourceManager.loaded_mesh,
        "shader": ResourceManager.loaded_shader,
        "texture": ResourceManager.loaded_texture,
        "material": ResourceManager.loaded_material,
        "prefab": ResourceManager.loaded_prefab,
    }
    if kind not in containers:
        raise ValueError(f"unknown resource kind: {kind!r} (expected {'/'.join(_RESOURCE_KINDS)})")
    out: list[dict] = []
    for rid, entry in containers[kind].items():
        item: dict = {"id": int(rid)}
        if isinstance(entry, dict):
            item["name"] = entry.get("name") or entry.get("builtin_name")
            if entry.get("builtin_name"):
                item["builtin_name"] = entry["builtin_name"]
            if entry.get("path"):
                item["path"] = entry["path"]
        else:
            item["name"] = getattr(entry, "name", None)   # Material 等对象容器
        out.append(item)
    return out


def _resource_id_from_value(kind: str, value) -> int:
    """资源引用: int → id; str → 名称精确匹配（首个）。"""
    if isinstance(value, bool):
        raise ValueError(f"{kind} reference must be int id or string name")
    if isinstance(value, int):
        return int(value)
    name = str(value)
    matches = [e["id"] for e in _resource_entries(kind) if e.get("name") == name]
    if not matches:
        raise ValueError(f"{kind} not found: {name!r}")
    return int(matches[0])


def _apply_transform_fields(entity_id: int, spec: dict, *, use_local: bool, relative: bool) -> list[str]:
    """应用 transform 字段（position/rotation(度)/scale）。

    - scale 支持标量（等比）;
    - relative=true: 位移加法 / 旋转加法(度) / 缩放乘法（gizmo 拖拽的结果语义）。
    """
    from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController

    setters = (
        ("position", SceneBrowserController.set_position),
        ("rotation", SceneBrowserController.set_rotation),
        ("scale", SceneBrowserController.set_scale),
    )
    applied: list[str] = []
    current = None
    for key, setter in setters:
        value = spec.get(key)
        if value is None:
            continue
        if key == "scale" and isinstance(value, (int, float)) and not isinstance(value, bool):
            value = [float(value)] * 3
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ValueError(
                f"{key} must be [x, y, z]" + (", or a scalar for scale" if key == "scale" else "")
            )
        if relative:
            if current is None:
                current = SceneBrowserController.get_summary(entity_id, use_local=use_local)
                if current is None:
                    raise ValueError("cannot read current transform")
            base = getattr(current, key)
            if key == "scale":
                value = [float(c) * float(v) for c, v in zip(base, value)]
            else:
                value = [float(c) + float(v) for c, v in zip(base, value)]
        setter(entity_id, tuple(float(v) for v in value), use_local=use_local)
        applied.append(key)
    return applied


def _save_validation_report(report: dict, path: str) -> str:
    """校验报告落盘（.txt → 人类可读; 其它 → JSON）。返回实际写入路径。"""
    saved = path if path.lower().endswith((".json", ".txt")) else path + ".json"
    os.makedirs(os.path.dirname(os.path.abspath(saved)), exist_ok=True)
    if saved.lower().endswith(".txt"):
        lines = [
            "Node Graph Validation Report",
            "=" * 60,
            f"task_id : {report.get('task_id')}",
            f"state   : {report.get('state')}   ok: {report.get('ok')}",
            f"graph   : {report.get('graph', {}).get('nodes')} nodes, "
            f"{report.get('graph', {}).get('links')} links, hash={report.get('graph', {}).get('hash')}",
            f"options : {report.get('options')}",
            f"timing  : {report.get('timing', {}).get('duration_ms')} ms",
            "",
        ]
        static = report.get("static") or {}
        for label, key in (("STATIC ERRORS", "errors"), ("STATIC WARNINGS", "warnings")):
            entries = static.get(key) or []
            lines.append(f"── {label} ({len(entries)}) ──")
            for e in entries:
                nid = e.get("node_id")
                where = f" [node {nid}]" if nid is not None else ""
                lines.append(f"  ✗{where} {e.get('message')}")
            lines.append("")
        runtime = report.get("runtime") or {}
        lines.append(f"── RUNTIME ({runtime.get('frames_simulated', 0)} frames, "
                     f"{runtime.get('total_events', 0)} events) ──")
        for err in runtime.get("errors") or []:
            lines.append(f"  ✗ {err}")
        lines.append("")
        log = report.get("log") or []
        lines.append(f"── EVENT LOG ({len(log)}) ──")
        for ent in log:
            lines.append(
                f"  f{ent.get('frame'):>4}  #{ent.get('node_id')}<{ent.get('node_type')}> "
                f"{ent.get('action')} | {ent.get('detail')}"
            )
        with open(saved, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    else:
        with open(saved, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
    return saved
