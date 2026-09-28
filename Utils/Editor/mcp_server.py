"""
Engine Editor Live MCP — 运行中编辑器的热注入工具（v2: 模拟控制 + 帧图像 + 摄像机）。

Tools:
  - editor_run_pie / editor_stop_pie / editor_sim_state  → PIE 启停与状态
  - editor_switch_2d / editor_set_scene_type             → 场景类型按钮语义（影响 PIE 摄像机）
  - editor_camera_get / editor_camera_set                → 场景摄像机读写（3d / 2d / overlay）
  - editor_capture                                       → 抓帧（editor / pie 窗口）→ PNG + 图片返回
  - editor_quit                                          → 请求关闭编辑器引擎

原理（详见 Doc/Dev/editor_live_protocol.md）:
    MCP(stdio) → 本工具 → 本机回环 TCP 127.0.0.1:8977
    → 编辑器 LiveCommandServer → 主线程 pump 执行（复用编辑器按钮同款 API）。
    帧图像 = NDJSON 回执行 + 二进制尾随帧（binary_bytes=N ⇒ 行后紧跟 N 字节 RGBA8）。
    PNG 编码在本进程完成（不阻塞引擎）; 抓帧文件: Utils/Editor/tmp/frames/（启动时清空）。
编辑器未运行时工具返回明确错误（先启动 startup.bat）。

启动方式:
    python -m Utils.Editor.mcp_server     （由 .vscode/mcp.json 配置自动拉起）
"""

import io
import json
import os
import shutil
import socket
import sys
import time

# ── 确保项目根在 sys.path ──
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from mcp.server.fastmcp import FastMCP, Image  # noqa: E402

mcp = FastMCP("Engine Editor Live", version="0.2.0")

DEFAULT_PORT = 8977
_ENV_PORT = "MGE_EDITOR_MCP_PORT"
_next_id = [0]

# ── 抓帧临时目录（策略: 每次 MCP server 启动清空, 防累积 — 用户 2026-09-28 指定）──
_EDITOR_DIR = os.path.dirname(os.path.abspath(__file__))
FRAMES_DIR = os.path.join(_EDITOR_DIR, "tmp", "frames")


def _wipe_frames_dir() -> None:
    """清空抓帧临时目录（server 启动时调用 — 仅 `python -m` 入口执行）。

    注意: 不在 import 时清空 — 避免开发/E2E 脚本 import 本模块时误删已有帧文件;
    只有 VS Code 拉起 server 的入口进程（__main__）才执行清空。
    """
    shutil.rmtree(os.path.join(_EDITOR_DIR, "tmp"), ignore_errors=True)
    os.makedirs(FRAMES_DIR, exist_ok=True)


def _port() -> int:
    try:
        return int(os.environ.get(_ENV_PORT, "") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def _send_raw(op: str, args: dict | None = None, timeout: float = 15.0) -> tuple[dict, bytes | None]:
    """向编辑器发送一条命令并等待回执; 就绪帧随二进制尾随负载返回。

    Returns:
        (result_or_error, payload) — 失败时 result 含 "error" 键、payload 为 None。
    """
    _next_id[0] += 1
    req = {"id": _next_id[0], "op": op, "args": args or {}}
    port = _port()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as conn:
            conn.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
            reader = conn.makefile("rb")
            line = reader.readline()
            if not line:
                return {"error": "编辑器连接被关闭（可能正在退出）"}, None
            resp = json.loads(line.decode("utf-8"))
            if not resp.get("ok"):
                return {"error": resp.get("error") or "unknown editor error"}, None
            result = resp.get("result") or {"ok": True}
            payload = None
            if isinstance(result, dict) and result.get("binary_bytes"):
                n = int(result["binary_bytes"])
                payload = reader.read(n)
                if payload is None or len(payload) != n:
                    return {"error": f"二进制负载不完整（{len(payload or b'')}/{n} bytes）"}, None
            return result, payload
    except ConnectionRefusedError:
        return {"error": f"编辑器未运行（127.0.0.1:{port} 无监听）— 请先启动 startup.bat。"}, None
    except (socket.timeout, TimeoutError):
        return {"error": f"等待编辑器响应超时（{timeout}s）— 编辑器可能未在处理帧。"}, None
    except ValueError as e:
        return {"error": f"无法解析编辑器回执: {e}"}, None
    except OSError as e:
        return {"error": f"连接失败: {e}"}, None


def _send(op: str, args: dict | None = None, timeout: float = 15.0) -> dict:
    """薄包装（非图像场景）— 保持 v1 工具的 dict 返回契约。"""
    result, _payload = _send_raw(op, args, timeout)
    return result


# ── 抓帧: request → 轮询 fetch → 翻转 → PNG（本进程编码, 不阻塞引擎）──


def _encode_and_save(target: str, result: dict, payload: bytes) -> tuple[str, bytes]:
    """RGBA8 裸帧（bottom-up）→ top-down → PNG → 落盘。返回 (path, png_bytes)。"""
    import numpy as np
    from PIL import Image as PILImage

    width = int(result["width"])
    height = int(result["height"])
    arr = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)[::-1]
    png_buf = io.BytesIO()
    PILImage.frombytes("RGBA", (width, height), np.ascontiguousarray(arr).tobytes()).save(png_buf, "PNG")
    png_bytes = png_buf.getvalue()
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(FRAMES_DIR, f"frame_{target}_{ts}_g{result.get('generation')}.png")
    with open(path, "wb") as fp:
        fp.write(png_bytes)
    return path, png_bytes


def _capture_png(target: str = "editor", timeout_s: float = 6.0) -> tuple[str, bytes]:
    """完整抓帧流程: frame.request → 轮询 frame.fetch → PNG 落盘。返回 (path, png_bytes)。"""
    result, _ = _send_raw("frame.request", {"target": target})
    if "error" in result:
        raise RuntimeError(result["error"])
    generation = result.get("generation")

    deadline = time.monotonic() + float(timeout_s)
    while time.monotonic() < deadline:
        info, payload = _send_raw("frame.fetch", {"target": target, "generation": generation})
        if "error" in info:
            raise RuntimeError(info["error"])
        if info.get("ready"):
            if payload is None:
                raise RuntimeError("ready frame without payload")
            return _encode_and_save(target, info, payload)
        state = info.get("state")
        if state == "error":
            raise RuntimeError(info.get("error") or "engine-side capture failed")
        if state == "superseded":
            raise RuntimeError(f"capture superseded (latest_generation={info.get('latest_generation')})")
        time.sleep(0.03)
    raise RuntimeError(f"capture timeout after {timeout_s}s (generation={generation})")


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
    """抓取窗口帧图像 → PNG 存 Utils/Editor/tmp/frames/ 并返回画面。

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


if __name__ == "__main__":
    _wipe_frames_dir()
    mcp.run()
