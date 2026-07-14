"""
Evaluators: Camera 节点 — 摄像机配置与控制。

  CameraSetMain     — 设置主摄像机 (更新 ctx.scene.scene_camera_id)

注: CameraConfigure / GetCameraInfo 已移除，
    未来由 Component 分类的 SetProperty / GetProperty 接管。
"""

from ...evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ...data_model import EntityRef

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
    st.scene_camera_id = eid
    st.scene_camera = ctx.scene.GetComponent(eid, CamComponent)
    print(f"[CameraSetMain] Entity #{eid} set as main camera")


register_evaluator("CameraSetMain", _eval_camera_set_main)
