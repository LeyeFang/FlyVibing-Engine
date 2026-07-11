"""
节点编辑器 — 数据模型（无 imgui 依赖）

定义 PinDef / NodeTypeDef / NodeInstance / LinkInstance。
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════
# ID 生成器
# ═══════════════════════════════════════════════════════════════

_next_id: int = 1


def _gen_id() -> int:
    """生成全局唯一 ID（线程不安全，仅 UI 线程使用）"""
    global _next_id
    n = _next_id
    _next_id += 1
    return n


# ═══════════════════════════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class PinDef:
    """引脚定义（类型模板用）"""
    id: int
    name: str
    kind: str          # "exec" | "data"
    direction: str     # "input" | "output"
    data_type: str = "exec"


@dataclass
class NodeTypeDef:
    """节点类型定义（注册表条目）"""
    type_name: str
    label: str
    category: str
    accent_color: tuple[float, float, float]
    pins: list[PinDef]
    props_text: str = ""


@dataclass
class NodeInstance:
    """画布上的节点实例"""
    id: int
    node_type: str
    pos: tuple[float, float] = (0.0, 0.0)
    props: dict = field(default_factory=dict)
    pin_ids: dict[str, int] = field(default_factory=dict)


@dataclass
class LinkInstance:
    """画布上的连线实例"""
    id: int
    from_pin: int
    to_pin: int


# ═══════════════════════════════════════════════════════════════
# 类型安全引用
# ═══════════════════════════════════════════════════════════════

@dataclass
class EntityRef:
    """类型安全的实体引用 — 替代裸 int EntityID 在节点间传递。

    节点输出 EntityRef，下游节点读取时检查 is_valid，
    避免对已销毁实体的无效操作。
    """
    eid: int = -1

    @property
    def is_valid(self) -> bool:
        """实体是否仍然存在。"""
        if self.eid < 0:
            return False
        try:
                        return ctx.scene.EntityExists(self.eid)
        except Exception:
            return False
