"""
Evaluators: Camera 节点 — 摄像机配置与控制。

  CameraSetMain     — 设置主摄像机 (更新 ctx.scene.scene_camera_id)
  CameraConfigure   — 配置摄像机参数 (投影类型 / FOV / 裁剪面)
  GetCameraInfo     — 读取摄像机运行时状态 (纯数据节点)
"""

import numpy as np

from ...evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ...data_model import EntityRef
from ..math import _read_data_input

from Application.Core.Scene.BasicComponents import Camera as CamComponent


# ── 辅助: 从 EntityRef pin 读取 eid ──────────────────────────

def _read_entity_ref(node_id: int, pin_name: str, ctx: ExecutionContext,
                     g: GraphEvaluator) -> int:
    """读取 entity_ref 类型 pin 的实体 ID，若无效返回 -1。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "input":
            inst_pin_id = inst.pin_ids.get(p.name)
            if inst_pin_id is not None:
                val = g._read_input(inst_pin_id, ctx)
                if isinstance(val, EntityRef):
                    return val.eid if val.is_valid else -1
                if isinstance(val, (int, float)):
                    return int(val)
    return -1


# ── 辅助: 写入 EntityRef 到 output pin ───────────────────────

def _write_entity_ref(node_id: int, pin_name: str, eid: int,
                      ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """写入 EntityRef 到指定 data output pin。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "output":
            inst_pin_id = inst.pin_ids.get(p.name)
            if inst_pin_id is not None:
                ctx.set_pin(inst_pin_id, EntityRef(eid=eid))


# ═══════════════════════════════════════════════════════════════
# CameraSetMain — 设置主摄像机
# ═══════════════════════════════════════════════════════════════

def _eval_camera_set_main(node_id: int, ctx: ExecutionContext,
                          g: GraphEvaluator) -> None:
    """将指定 entity 设为当前场景的主渲染摄像机。"""
    eid = _read_entity_ref(node_id, "Entity", ctx, g)
    if eid < 0 or not ctx.scene.EntityExists(eid):
        print("[CameraSetMain] Invalid entity — skipped")
        return

    st = ctx.scene
    st._switch_world()
    st.scene_camera_id = eid
    st.scene_camera = ctx.scene.GetComponent(eid, CamComponent)
    print(f"[CameraSetMain] Entity #{eid} set as main camera")


register_evaluator("CameraSetMain", _eval_camera_set_main)


# ═══════════════════════════════════════════════════════════════
# CameraConfigure — 配置摄像机参数
# ═══════════════════════════════════════════════════════════════

def _eval_camera_configure(node_id: int, ctx: ExecutionContext,
                           g: GraphEvaluator) -> None:
    """配置 entity 上 Camera 组件的投影参数。

    投影类型 (perspective / orthographic) 由节点属性下拉选择，
    FOV / OrthoSize / NearPlane / FarPlane 由 data pin 读入。
    """
    eid = _read_entity_ref(node_id, "Entity", ctx, g)
    if eid < 0 or not ctx.scene.EntityExists(eid):
        print("[CameraConfigure] Invalid entity — skipped")
        return

    from Application.Core.Scene.BasicComponents import ProjectionType

    try:
        cam = ctx.scene.GetComponent(eid, CamComponent)
    except Exception:
        print(f"[CameraConfigure] Entity #{eid} has no Camera component")
        return

    inst = g._canvas.nodes[node_id]

    # ── 投影类型 (节点属性) ──
    proj = inst.props.get("projection", "perspective")
    if proj == "orthographic":
        cam.projection_type = ProjectionType.ORTHOGRAPHIC
    else:
        cam.projection_type = ProjectionType.PERSPECTIVE

    # ── 数值参数 (data pin) ──
    fov = _read_data_input(node_id, "FOV", ctx, g, None)
    if fov is not None:
        cam.fov = float(fov)

    ortho = _read_data_input(node_id, "OrthoSize", ctx, g, None)
    if ortho is not None:
        cam.ortho_size = float(ortho)

    near_p = _read_data_input(node_id, "NearPlane", ctx, g, None)
    if near_p is not None:
        cam.near_plane = float(near_p)

    far_p = _read_data_input(node_id, "FarPlane", ctx, g, None)
    if far_p is not None:
        cam.far_plane = float(far_p)

    print(f"[CameraConfigure] Entity #{eid}: "
          f"proj={proj}, fov={cam.fov}, ortho={cam.ortho_size}, "
          f"near={cam.near_plane}, far={cam.far_plane}")


register_evaluator("CameraConfigure", _eval_camera_configure)


# ═══════════════════════════════════════════════════════════════
# GetCameraInfo — 读取摄像机运行时状态 (纯数据节点)
# ═══════════════════════════════════════════════════════════════

def _eval_get_camera_info(node_id: int, ctx: ExecutionContext,
                          g: GraphEvaluator) -> None:
    """从 Camera + Transform 组件读取运行时数据，写入 output pins。

    纯数据节点 — 由下游消费者触发懒求值，每帧数据自动过期。
    """
    eid = _read_entity_ref(node_id, "Entity", ctx, g)

    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]

    # ── 辅助: 写入 output pin ──
    def _write(pin_name: str, value) -> None:
        for p in nd.pins:
            if p.name == pin_name and p.direction == "output":
                pid = inst.pin_ids.get(p.name)
                if pid is not None:
                    ctx.set_pin(pid, value)

    if eid < 0 or not ctx.scene.EntityExists(eid):
        _write("IsValid", False)
        _write("Position", np.zeros(3, dtype=np.float32))
        _write("Forward", np.array([0.0, 0.0, -1.0], dtype=np.float32))
        _write("FOV", 0.0)
        _write("OrthoSize", 0.0)
        return

    from Application.Core.Scene.BasicComponents import Transform
    from Application.Core.Math.Transform import calculate_entity_model

    try:
        cam = ctx.scene.GetComponent(eid, CamComponent)
        xform = ctx.scene.GetComponent(eid, Transform)
    except Exception:
        _write("IsValid", False)
        return

    # ── 模型矩阵 → 位置 / 前向 ──
    model = calculate_entity_model(
        position=(xform.position_x, xform.position_y, xform.position_z),
        rotation=(xform.rotation_x, xform.rotation_y, xform.rotation_z),
        scale=(xform.scale_x, xform.scale_y, xform.scale_z),
    )
    position = np.array(
        [float(model[3, 0]), float(model[3, 1]), float(model[3, 2])],
        dtype=np.float32,
    )
    forward = np.array(
        [-float(model[2, 0]), -float(model[2, 1]), -float(model[2, 2])],
        dtype=np.float32,
    )
    # 归一化 forward
    f_norm = float(np.linalg.norm(forward))
    if f_norm > 1e-8:
        forward = forward / f_norm

    _write("IsValid", True)
    _write("Position", position)
    _write("Forward", forward)
    _write("FOV", cam.fov)
    _write("OrthoSize", cam.ortho_size)


register_evaluator("GetCameraInfo", _eval_get_camera_info)
