"""
Engine Editor Live MCP — 运行中编辑器的热注入工具（v0.4.0: 双档位 + CLI/Skill 混合形态）。

档位（--profile lite|full > env MGE_MCP_PROFILE > 默认 full）:
  lite（推荐, 省 token — 5 个工具）:
    engine_help(op|topic)        → op 目录 / 单 op 详情 / 主题帮助（按需读取, 不常驻）
    engine_call(op, args)        → 执行 1 个 op（兼容旧工具名; 大载荷自动瘦身）
    engine_batch(calls)          → 一次调用顺序执行多个 op
    engine_validate_graph(...)   → 图干跑校验（detail=summary 默认）
    engine_capture(target)       → 抓帧（图像直回; 想省 token 用 CLI capture）
  full（兼容旧用法 — 44 个 editor_* 工具, 见下）:
    editor_run_pie / editor_stop_pie / editor_sim_state  → PIE 启停与状态
    editor_switch_2d / editor_set_scene_type             → 场景类型按钮语义（影响 PIE 摄像机）
    editor_camera_get / editor_camera_set                → 场景摄像机读写（3d / 2d / overlay）
    editor_graph_validate(_report/_cancel)               → 节点图干跑校验（引擎内服务: 静态+模拟）
    editor_graph_export / editor_graph_import            → 节点图 JSON 导入导出（含 _rules 文档）
    editor_project_open                                  → 打开 .myproj 工程（资源+场景全加载）
    editor_capture                                       → 抓帧（editor / pie 窗口）→ PNG + 图片返回
    editor_quit                                          → 请求关闭编辑器引擎
    （含 entity/selection/component/scene/resource 容器级工具）

原理（详见 Doc/Dev/editor_live_protocol.md）:
    MCP(stdio) → 本工具 → 本机回环 TCP 127.0.0.1:8977
    → 编辑器 LiveCommandServer → 主线程 pump 执行（复用编辑器按钮同款 API）。
    帧图像 = NDJSON 回执行 + 二进制尾随帧（binary_bytes=N ⇒ 行后紧跟 N 字节 RGBA8）。
    PNG 编码在本进程完成（不阻塞引擎）; 抓帧文件: <临时目录>/engine_editor_mcp/frames
    （MGE_MCP_FRAMES_DIR 可覆盖; 仅入口进程启动时清空）。
编辑器未运行时工具返回明确错误（先启动 startup.bat）。

独立分发的三种消费形态（同一 wheel, 同一 op 注册表 ops.py）:
    CLI（零常驻上下文成本, 任意终端型 agent 首选）: engine-editor-cli
    MCP lite / full: python -m engine_editor_mcp --profile lite|full
    Skill（渐进披露）: engine-editor-cli setup --workspace <项目目录>

dev 仓库内等价入口: python -m Utils.User.EditorMcp.mcp_server  （薄 shim, 同一源码）
"""

import io
import os
import sys

from mcp.server.fastmcp import FastMCP, Image

from . import ops as op_registry
from .client import (
    DEFAULT_PORT,
    FRAMES_DIR,
    EngineError,
    capture_png,
    editor_port,
    encode_and_save,
    execute_calls,
    send,
    send_raw,
    validate_graph_orchestrate,
    wipe_frames_dir,
)

# 供 dev shim（Utils/User/EditorMcp/mcp_server.py）与外部集成（E2E 脚本）复用的符号
# （v0.4.0: 底层实现移至 client.py — 名称与行为保持不变）
__all__ = [
    "mcp",
    "FRAMES_DIR",
    "DEFAULT_PORT",
    "_send",
    "_send_raw",
    "_port",
    "_capture_png",
    "_encode_and_save",
    "_wipe_frames_dir",
    "apply_profile",
    "main",
]

mcp = FastMCP("Engine Editor Live", version="0.4.0")

# ── 低层函数（v0.4.0 起实现位于 client.py; 此处保留模块级名以兼容 shim / E2E 脚本）──

_send = send
_send_raw = send_raw
_capture_png = capture_png
_encode_and_save = encode_and_save


def _port() -> int:
    return editor_port()


def _wipe_frames_dir() -> None:
    """清空抓帧目录（server 启动时调用 — 仅入口进程执行；import 不清空）。"""
    wipe_frames_dir()


@mcp.tool()
def editor_run_pie() -> dict:
    """触发编辑器 Play（等同 Run 按钮）：启动 PIE 运行时。

    Returns:
        {"requested": true, "state": "pending_start"} 或 {"requested": false, "state": ...}
        或 {"error": "..."}
    """
    return _send("sim.play")


@mcp.tool()
def editor_stop_pie() -> dict:
    """停止 PIE（等同 Scene 面板 Stop 按钮）。

    Returns:
        {"requested": true, "state": "pending_stop"} 或 {"requested": false, "state": "Stopped"}
        或 {"error": "..."}
    """
    return _send("sim.stop")


@mcp.tool()
def editor_sim_state() -> dict:
    """查询模拟状态（只读）：state = Stopped / Running / Paused; runtime_alive = PIE 线程存活。"""
    return _send("sim.state")


@mcp.tool()
def editor_switch_2d() -> dict:
    """切到 2D（等同 Scene 面板 “2D” 按钮：同时设置 game_type 与编辑器视口）。

    注意: 会同时设置 scene.game_type — 影响 PIE 启动时使用的场景摄像机。

    Returns:
        {"mode": "2d", "label": "2D (Ortho)", "game_type": "2d"} 或 {"error": "..."}
    """
    return _send("view.set_mode", {"mode": "2d"})


@mcp.tool()
def editor_set_scene_type(mode: str) -> dict:
    """设置场景类型（等同 Scene Type 按钮：3D / 2D / Overlay）— 含 game_type + 编辑器视口。

    Args:
        mode: "3d" / "2d" / "overlay"
    """
    return _send("view.set_mode", {"mode": mode})


@mcp.tool()
def editor_camera_get(role: str = "3d") -> dict:
    """读取场景摄像机（role: "3d" / "2d" / "overlay"）的 Transform + Camera 属性。"""
    return _send("camera.get", {"role": role})


@mcp.tool()
def editor_camera_set(
    role: str = "3d",
    position: list[float] | None = None,
    rotation: list[float] | None = None,
    projection: str | None = None,
    ortho_size: float | None = None,
    fov: float | None = None,
) -> dict:
    """修改场景摄像机（仅编辑器场景; 只改传入字段）。

    Args:
        role: "3d" / "2d" / "overlay"
        position / rotation: [x, y, z]（GL 坐标系）
        projection: "persp" / "ortho"
        ortho_size / fov: 可选其它属性
    """
    args: dict = {"role": role}
    if position is not None:
        args["position"] = list(position)
    if rotation is not None:
        args["rotation"] = list(rotation)
    if projection is not None:
        args["projection"] = projection
    if ortho_size is not None:
        args["ortho_size"] = ortho_size
    if fov is not None:
        args["fov"] = fov
    return _send("camera.set", args)


@mcp.tool()
def editor_graph_list() -> dict:
    """读取节点图画布快照（节点: id/type/props/pins; 连线: from_pin/to_pin）。"""
    return _send("graph.list")


@mcp.tool()
def editor_graph_add(node_type: str, props: dict | None = None, position: list[float] | None = None) -> dict:
    """在节点图添加节点（等同 Add 菜单）。

    例: editor_graph_add("EntitySpawn", {"template": "DefaultCube"})
    """
    args: dict = {"type": node_type}
    if props:
        args["props"] = props
    if position is not None:
        args["position"] = list(position)
    return _send("graph.add", args)


@mcp.tool()
def editor_graph_link(from_node: int, from_pin: str, to_node: int, to_pin: str) -> dict:
    """连接两个引脚（等同画布拖线）。例: OnGameStart.exec → EntitySpawn.exec_in。"""
    return _send("graph.link", {
        "from": {"node": from_node, "pin": from_pin},
        "to": {"node": to_node, "pin": to_pin},
    })


@mcp.tool()
def editor_graph_set_props(node_id: int, props: dict) -> dict:
    """更新节点属性（等同内联控件改属性）。"""
    return _send("graph.set_props", {"node": node_id, "props": props})


# ════════════════════════════════════════════════════════════════
# v4: 图校验（引擎内服务） / 图导入导出 / 工程打开
# ════════════════════════════════════════════════════════════════

_LOG_CAP = 500


def _trim_report(report: dict) -> dict:
    """报告瘦身（MCP 回传用）: log 超过 _LOG_CAP 条则截断 + 标记。"""
    if not isinstance(report, dict):
        return report
    log = report.get("log")
    if isinstance(log, list) and len(log) > _LOG_CAP:
        report = dict(report)
        report["log_total"] = len(log)
        report["log_truncated"] = True
        report["log"] = log[:_LOG_CAP]
    return report


def _validate_orchestrate(
    source: str = "canvas",
    graph: dict | None = None,
    frames: int = 360,
    verbose: bool = True,
    seed: int = 0,
    save_path: str | None = None,
    timeout_s: float = 120.0,
) -> dict:
    """校验编排（start→poll→report）— 实现位于 client.py（MCP 工具与 CLI validate 共用）。"""
    return validate_graph_orchestrate(
        source=source,
        graph=graph,
        frames=frames,
        verbose=verbose,
        seed=seed,
        save_path=save_path,
        timeout_s=timeout_s,
    )


@mcp.tool()
def editor_graph_validate(
    source: str = "canvas",
    graph: dict | None = None,
    frames: int = 360,
    verbose: bool = True,
    seed: int = 0,
    save_path: str | None = None,
    timeout_s: float = 120.0,
) -> dict:
    """干跑校验节点图（引擎内服务: 静态检查 + fake-time 模拟, 需要引擎运行中）。

    提示: lite 档的 engine_validate_graph 默认只回摘要（省 token）— 本工具回全量报告。
    Args:
        source: "canvas"（当前编辑器画布快照, 默认）| "graph"（直接传 graph dict, agent 生成图先验）
        graph:  仅 source="graph" 时必填
        frames: 模拟帧数（默认 360 = 6s @60fps）
        seed:   随机种子（确定性干跑, 默认 0）
        save_path: 可选 — 报告落盘路径（.json / .txt）

    Returns:
        {found, report: {ok, state, counts, static, runtime, log: [...], graph}, saved_path?}
        或 {"error": ...}（引擎未运行）
    """
    result = _validate_orchestrate(source, graph, frames, verbose, seed, save_path, timeout_s)
    if "error" in result or not isinstance(result.get("report"), dict):
        return result
    result = dict(result)
    result["report"] = _trim_report(result["report"])
    return result


@mcp.tool()
def editor_graph_validate_report(task_id: int | None = None, save_path: str | None = None) -> dict:
    """取回已完成的校验报告（task_id 省略 → 最新一份; save_path 落盘 .json/.txt）。"""
    args: dict = {}
    if task_id is not None:
        args["task_id"] = task_id
    if save_path:
        args["save_path"] = save_path
    result = _send("graph.validate.report", args)
    if "error" in result:
        return result
    result["report"] = _trim_report(result.get("report") or {})
    return result


@mcp.tool()
def editor_graph_validate_cancel(task_id: int | None = None) -> dict:
    """取消正在运行的校验任务（帧间生效）。"""
    args: dict = {}
    if task_id is not None:
        args["task_id"] = task_id
    return _send("graph.validate.cancel", args)


@mcp.tool()
def editor_graph_export(path: str | None = None, include_rules: bool = True) -> dict:
    """导出当前画布节点图 JSON（含 _rules 规则文档; path 给了同时落盘 .json）。

    Returns: {nodes, links, saved_path, graph: {...}}
    """
    args: dict = {"include_rules": include_rules}
    if path:
        args["path"] = path
    return _send("graph.export", args, timeout=30.0)


@mcp.tool()
def editor_graph_import(graph: dict | None = None, path: str | None = None, validate_first: bool = True) -> dict:
    """导入节点图替换当前画布（先静态检查, 有 error 拒绝; 强制导入传 validate_first=False）。

    Args:
        graph: graph dict（优先） 或 path: .json 文件
    """
    args: dict = {"validate_first": validate_first}
    if graph is not None:
        args["graph"] = graph
    if path:
        args["path"] = path
    return _send("graph.import", args, timeout=30.0)


@mcp.tool()
def editor_project_open(path: str) -> dict:
    """打开 .myproj 工程（等同 File ▸ Open Project — 资源+场景全加载, 启动场景激活）。

    Returns: {opened, name, path, scenes, active}
    """
    return _send("project.open", {"path": path}, timeout=60.0)


# ════════════════════════════════════════════════════════════════
# v3: 实体 / 选中 / 组件 / 场景 / 资源（编辑器的容器级操作）
# ════════════════════════════════════════════════════════════════


def _entity_args(entity_id: int | None, name: str | None) -> dict:
    """实体寻址参数: id / name 二选一（id 优先）。"""
    args: dict = {}
    if entity_id is not None:
        args["id"] = entity_id
    if name is not None:
        args["name"] = name
    return args


@mcp.tool()
def editor_entity_list(roots_only: bool = False) -> dict:
    """列出场景中的实体（roots_only=true 仅根实体）。"""
    return _send("entity.list", {"roots_only": roots_only})


@mcp.tool()
def editor_entity_get(entity_id: int | None = None, name: str | None = None) -> dict:
    """读取实体快照（名称/组件/层级/可见性/transform — 编辑器坐标、角度制）。"""
    return _send("entity.get", _entity_args(entity_id, name))


@mcp.tool()
def editor_entity_add(name: str = "", parent: int | str | None = None) -> dict:
    """新建实体（仅 Transform; 与面板 +New 一致 — 有选中时成为其子级）。

    parent: 显式指定父实体（id 或名称）; 传 "none" 强制作为根实体。
    """
    args: dict = {"name": name}
    if parent is not None:
        args["parent"] = parent
    return _send("entity.add", args)


@mcp.tool()
def editor_entity_rename(new_name: str, entity_id: int | None = None, name: str | None = None) -> dict:
    """重命名实体（名称不强制唯一 — 返回重名警告）。"""
    args = _entity_args(entity_id, name)
    args["new_name"] = new_name
    return _send("entity.rename", args)


@mcp.tool()
def editor_entity_delete(entity_id: int | None = None, name: str | None = None) -> dict:
    """删除实体及其子实体。"""
    return _send("entity.delete", _entity_args(entity_id, name))


@mcp.tool()
def editor_entity_transform(
    entity_id: int | None = None,
    name: str | None = None,
    position: list[float] | None = None,
    rotation: list[float] | None = None,
    scale: list[float] | None = None,
    local: bool = False,
    relative: bool = False,
) -> dict:
    """设置实体 transform（编辑器坐标系、旋转用角度; local=true 写本地坐标）。

    relative=true: 相对调整（位移加法 / 旋转加法 / 缩放乘法 — 等同 gizmo 拖拽语义）;
    scale 可传标量做等比缩放（如 scale=2 → 2,2,2）。
    """
    args = _entity_args(entity_id, name)
    if position is not None:
        args["position"] = list(position)
    if rotation is not None:
        args["rotation"] = list(rotation)
    if scale is not None:
        args["scale"] = list(scale)
    if local:
        args["local"] = True
    if relative:
        args["relative"] = True
    return _send("entity.transform", args)


@mcp.tool()
def editor_entity_visible(
    entity_id: int | None = None,
    name: str | None = None,
    editor: bool | None = None,
    render: bool | None = None,
) -> dict:
    """设置编辑器视口可见性（editor）与渲染可见性（render）。"""
    args = _entity_args(entity_id, name)
    if editor is not None:
        args["editor"] = editor
    if render is not None:
        args["render"] = render
    return _send("entity.visible", args)


@mcp.tool()
def editor_entity_reparent(parent: int | str, entity_id: int | None = None, name: str | None = None) -> dict:
    """设置父实体（parent: id/名称; "none" 解除父级）。"""
    args = _entity_args(entity_id, name)
    args["parent"] = parent
    return _send("entity.reparent", args)


@mcp.tool()
def editor_selection_get() -> dict:
    """当前选中的实体（无选中 → entity_id=null）。"""
    return _send("selection.get")


@mcp.tool()
def editor_selection_set(entity_id: int | None = None, name: str | None = None, gizmo: bool = True) -> dict:
    """选中实体（gizmo=true 同时显示变换 gizmo — 等同视口点选）。"""
    args = _entity_args(entity_id, name)
    args["gizmo"] = gizmo
    return _send("selection.set", args)


@mcp.tool()
def editor_selection_clear() -> dict:
    """清除选中。"""
    return _send("selection.clear")


@mcp.tool()
def editor_component_types() -> dict:
    """已注册的组件类型（可用名称表）。"""
    return _send("component.types")


@mcp.tool()
def editor_component_list(entity_id: int | None = None, name: str | None = None) -> dict:
    """实体的组件名列表。"""
    return _send("component.list", _entity_args(entity_id, name))


@mcp.tool()
def editor_component_add(type: str, entity_id: int | None = None, name: str | None = None) -> dict:
    """给实体添加组件（MeshRenderer 自动绑定默认 Cube 网格）。"""
    args = _entity_args(entity_id, name)
    args["type"] = type
    return _send("component.add", args)


@mcp.tool()
def editor_component_remove(type: str, entity_id: int | None = None, name: str | None = None) -> dict:
    """移除组件（Transform 不可移除）。"""
    args = _entity_args(entity_id, name)
    args["type"] = type
    return _send("component.remove", args)


@mcp.tool()
def editor_component_get(type: str, entity_id: int | None = None, name: str | None = None) -> dict:
    """读取组件字段快照。"""
    args = _entity_args(entity_id, name)
    args["type"] = type
    return _send("component.get", args)


@mcp.tool()
def editor_component_set(
    type: str,
    fields: dict,
    entity_id: int | None = None,
    name: str | None = None,
    local: bool = False,
    relative: bool = False,
) -> dict:
    """修改组件字段（fields 为部分更新）。

    type="Transform" 例: fields={"position": [3, 0, 0], "scale": 2}
      （relative=true 相对调整: 位移加法 / 旋转加法 / 缩放乘法）;
    type="MeshRenderer" 可用字段:
      color [r,g,b(,a)] / mesh (名称或 id) / material (名称或 id) /
      visible / material_name / shader (名称或 id) / uniform ({名: 值}) /
      texture (+"texture_slot") / texture_add / texture_remove (slot号);
    type="Camera" 例: fields={"fov": 60, "projection": "ortho"}。
    """
    args = _entity_args(entity_id, name)
    args["type"] = type
    args["fields"] = fields
    if local:
        args["local"] = True
    if relative:
        args["relative"] = True
    return _send("component.set", args)


@mcp.tool()
def editor_scene_list() -> dict:
    """场景列表 + 当前活跃场景。"""
    return _send("scene.list")


@mcp.tool()
def editor_scene_switch(name: str) -> dict:
    """切换场景（含保存当前/加载/视口/节点图同步全流程）。"""
    return _send("scene.switch", {"name": name})


@mcp.tool()
def editor_scene_create(name: str) -> dict:
    """新建场景并设为活跃。"""
    return _send("scene.create", {"name": name})


@mcp.tool()
def editor_scene_save(path: str | None = None) -> dict:
    """保存当前场景为 .scene 文件（省略 path 时用最近保存路径）。"""
    args = {"path": path} if path else {}
    return _send("scene.save", args)


@mcp.tool()
def editor_scene_load(path: str) -> dict:
    """从 .scene 文件加载并设为活跃。"""
    return _send("scene.load", {"path": path})


@mcp.tool()
def editor_resource_list(kind: str) -> dict:
    """资源列表 — kind: "mesh" / "shader" / "texture" / "material" / "prefab"。"""
    return _send("resource.list", {"kind": kind})


@mcp.tool()
def editor_resource_find(kind: str, name: str) -> dict:
    """按名查找资源（返回全部匹配; 名称不保证唯一）。"""
    return _send("resource.find", {"kind": kind, "name": name})


@mcp.tool()
def editor_resource_material_get(material_id: int | None = None, name: str | None = None) -> dict:
    """材质详情（名称/shader/颜色/纹理槽/uniform 键）。"""
    args: dict = {}
    if material_id is not None:
        args["id"] = material_id
    if name is not None:
        args["name"] = name
    return _send("resource.material.get", args)


@mcp.tool()
def editor_capture(target: str = "editor", timeout_s: float = 6.0):
    """抓取窗口帧图像 → PNG 存 <临时目录>/engine_editor_mcp/frames/ 并返回画面。

    引擎侧只做 glReadPixels（渲染线程帧末）; PNG 编码在本进程（不阻塞引擎）。

    Args:
        target: "editor"（编辑器窗口）或 "pie"（运行时窗口, 需 PIE 运行中）
        timeout_s: 等待渲染线程完成抓帧的上限（秒）
    Returns:
        [图像内容块, 说明文本（含文件路径/尺寸）] — agent 可直接查看画面。
    """
    try:
        path, png_bytes = _capture_png(target, timeout_s)
    except RuntimeError as e:
        raise ValueError(f"capture failed: {e}") from e
    return [Image(data=png_bytes, format="png"), f"saved: {path}"]


@mcp.tool()
def editor_quit() -> dict:
    """请求关闭编辑器引擎（等同点击窗口关闭按钮，下一帧开始正常退出流程）。

    Returns:
        {"closing": true, "via": "window_close_request" | "run_state"} 或 {"error": "..."}
    """
    return _send("editor.quit")


# ════════════════════════════════════════════════════════════════
# v0.4.0: 档位（profile）— lite 精简工具集 / full 兼容旧工具集
#   选择: 启动参数 --profile lite|full > env MGE_MCP_PROFILE > 默认 full
#   lite 目标: 44×schema（约 17.8k 字符常驻）→ 5×schema（约 1.2k 字符）;
#   完整 op 参考按需获取（engine_help / CLI / Skill），不再常驻上下文。
# ════════════════════════════════════════════════════════════════

_ENV_PROFILE = "MGE_MCP_PROFILE"
LITE_TOOL_NAMES = (
    "engine_help",
    "engine_call",
    "engine_batch",
    "engine_validate_graph",
    "engine_capture",
)

_HELP_TOPICS = op_registry.TOPIC_HELP  # 主题帮助的单一事实源位于 ops.py（CLI 同用）


def _requested_profile(argv: list[str] | None = None) -> str:
    """档位解析: --profile[-=] 参数 > env > 默认 full。"""
    args = list(sys.argv[1:] if argv is None else argv)
    value = ""
    for i, a in enumerate(args):
        if a == "--profile" and i + 1 < len(args):
            value = args[i + 1]
            break
        if a.startswith("--profile="):
            value = a.split("=", 1)[1]
            break
    if not value:
        value = os.environ.get(_ENV_PROFILE, "")
    return "lite" if value.strip().lower() == "lite" else "full"


def apply_profile(profile: str) -> str:
    """按档位裁剪工具集（幂等 — 可在任意当前档切到另一档; 返回实际档位）。

    lite → 仅保留 LITE_TOOL_NAMES; full → 移除 lite 工具（恢复旧 44 工具集）。
    内部结构不可用时 fail-open（保留全部并告警）。
    """
    profile = "lite" if str(profile).strip().lower() == "lite" else "full"
    try:
        tools = mcp._tool_manager._tools  # mcp>=1.10 FastMCP 内部注册表
    except AttributeError:
        print(
            f"[engine-editor-mcp] WARNING: tool filter unavailable — profile {profile!r} not applied",
            file=sys.stderr,
        )
        return profile
    if not _ALL_TOOL_OBJECTS:
        print(
            f"[engine-editor-mcp] WARNING: tool master table empty — profile {profile!r} not applied",
            file=sys.stderr,
        )
        return profile
    tools.clear()
    if profile == "lite":
        tools.update({n: t for n, t in _ALL_TOOL_OBJECTS.items() if n in LITE_TOOL_NAMES})
    else:
        tools.update({n: t for n, t in _ALL_TOOL_OBJECTS.items() if n not in LITE_TOOL_NAMES})
    return profile


# 共享辅助（prepare_args / call_timeout / unknown_args / trim_result / summarize_report）
# 位于 ops.py（CLI 与 lite MCP 共用单一实现）。


@mcp.tool()
def engine_help(op: str = "") -> str:
    """Op 目录（无参）/ 单 op 详情 / 主题（mcp, cli, skill, capture）。按需读取，不常驻上下文。"""
    topic = (op or "").strip()
    if not topic or topic in ("ops", "all"):
        return op_registry.format_ops_list()
    if topic in _HELP_TOPICS:
        return _HELP_TOPICS[topic]
    return op_registry.format_op_help(topic)


@mcp.tool()
def engine_call(op: str, args: dict | None = None, detail: str = "auto") -> dict:
    """执行一个编辑器 op（名字见 engine_help()）; 兼容旧工具名（editor_run_pie 等）。detail='full' 关闭自动瘦身。"""
    name, defaults = op_registry.resolve(op)
    if not name:
        return {"error": f"unknown op: {op!r}", "hint": "engine_help() 获取 op 目录"}
    call_args = dict(defaults)
    call_args.update(args or {})
    call_args = op_registry.prepare_args(name, call_args)
    result = _send(name, call_args, timeout=op_registry.call_timeout(name))
    unknown = op_registry.unknown_args(name, call_args)
    if unknown and isinstance(result, dict) and "error" not in result:
        result = dict(result)
        result["_unknown_args"] = unknown
    return op_registry.trim_result(name, result, detail)


@mcp.tool()
def engine_batch(calls: list[dict], continue_on_error: bool = False) -> dict:
    """一次调用顺序执行多个 op（省往返）: calls=[{"op": "entity.add", "args": {...}}, ...]。出错默认中断。"""
    results = execute_calls(calls, continue_on_error)
    return {"count": len(results), "results": results}


@mcp.tool()
def engine_validate_graph(
    source: str = "canvas",
    graph: dict | None = None,
    frames: int = 360,
    verbose: bool = False,
    seed: int = 0,
    save_path: str | None = None,
    detail: str = "summary",
    timeout_s: float = 120.0,
) -> dict:
    """干跑校验节点图（静态 + fake-time 模拟; 需引擎运行中）。detail='summary'（默认）省 token; 'full' 完整报告。"""
    result = _validate_orchestrate(source, graph, frames, verbose, seed, save_path, timeout_s)
    if "error" in result:
        return result
    report = result.get("report")
    if isinstance(report, dict):
        result = dict(result)
        if detail == "full":
            result["report"] = _trim_report(report)
        else:
            result["report"] = op_registry.summarize_report(report)
    return result


@mcp.tool()
def engine_capture(target: str = "editor", timeout_s: float = 6.0):
    """抓取窗口帧图像 → PNG 落盘 + 图像直回（agent 可直接看到画面）。target: "editor" / "pie"。"""
    try:
        path, png_bytes = _capture_png(target, timeout_s)
    except EngineError as e:
        raise ValueError(f"capture failed: {e}") from e
    return [Image(data=png_bytes, format="png"), f"saved: {path}"]


# 全量工具主表（apply_profile 的单一数据源 — 在所有 @mcp.tool() 定义之后固化）
try:
    _ALL_TOOL_OBJECTS: dict = dict(mcp._tool_manager._tools)
except AttributeError:
    _ALL_TOOL_OBJECTS = {}


def main() -> None:
    """入口: 解析档位 → 裁剪工具集 → 清空抓帧目录 → 启动 stdio 服务器。"""
    apply_profile(_requested_profile())
    _wipe_frames_dir()
    mcp.run()


if __name__ == "__main__":
    main()
