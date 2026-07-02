"""
Scene — 场景数据容器。

Scene 是纯数据类，不依赖 esper、Renderer、Window 等运行时模块。
可被序列化/反序列化，可在 Editor 和 Runtime 之间传递。

一个 Scene 包含:
  - 场景元数据 (name)
  - 实体定义列表 (EntityData)
  - 节点图 (NodeCanvas, 定义运行时行为)
  - 场景设置 (主相机等)

与 esper 的关系:
  Scene 不直接使用 esper。当 Scene 被 Editor 打开或 Runtime 运行时，
  通过 instantiate_into_world() 将实体数据注入到 esper World 中。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# EntityData — 单个实体的可序列化定义
# ═══════════════════════════════════════════════════════════════

@dataclass
class EntityData:
    """可序列化的实体定义。

    不直接持有 esper Entity ID — 实体 ID 在加载到 World 时才分配。
    components 是 {类型名: 组件实例} 的字典，组件实例为 @dataclass。

    示例:
        EntityData(
            name="MainCamera",
            components={
                "Transform": Transform(px=0, py=5, pz=10),
                "Camera": Camera(is_primary=True),
            }
        )
    """

    name: str = "Entity"
    components: dict[str, object] = field(default_factory=dict)
    # 未来扩展:
    #   parent_id: Optional[int] = None    # 父实体 (层级)
    #   tag: str = ""                      # 标签
    #   active: bool = True                # 激活状态


# ═══════════════════════════════════════════════════════════════
# Scene — 场景数据容器
# ═══════════════════════════════════════════════════════════════

@dataclass
class Scene:
    """场景 — 纯数据容器，引擎无关。

    生命周期:
      1. Editor 中创建 Scene → 编辑 entity/node_graph
      2. 保存为 .scene 文件
      3. ▶ Play 时: runtime_scene = editor_scene.copy()
      4. Runtime 将 runtime_scene 注入到独立的 esper World
      5. ■ Stop 时: 丢弃 runtime_scene (编辑器原数据不受影响)

    使用方式:
      # 编辑器
      scene = Scene("MyScene")
      eid = scene.add_entity("Player",
          Transform=Transform(px=0, py=0, pz=0),
          MeshRenderer=MeshRenderer(mesh_id=1),
      )

      # 序列化
      data = scene.to_dict()

      # PIE 深拷贝
      runtime_scene = scene.copy()
    """

    name: str = "Untitled"

    # {entity_id: EntityData}
    entities: dict[int, EntityData] = field(default_factory=dict)

    # 节点图 — 定义此场景的运行时行为
    # 类型为 Optional[NodeCanvas] — 延迟引用以避免循环导入
    node_graph: Optional[object] = None

    # 场景级设置
    main_camera_entity_id: Optional[int] = None

    # 内部: 实体 ID 自增计数器
    _next_eid: int = field(default=1, repr=False)

    # ════════════════════════════════════════════════════════════
    # 实体 CRUD (纯数据操作, 不涉及 esper)
    # ════════════════════════════════════════════════════════════

    def add_entity(
        self,
        name: str = "Entity",
        **components: object,
    ) -> int:
        """添加实体定义，返回本地实体 ID。

        Args:
            name: 实体名称 (编辑器 Outliner 中显示)
            **components: 组件实例, 如 Transform=Transform(), MeshRenderer=MeshRenderer()

        Returns:
            新实体的本地 ID

        Example:
            eid = scene.add_entity("Cube",
                Transform=Transform(px=-3, py=0, pz=0),
                MeshRenderer=MeshRenderer(mesh_id=cube_mesh_id),
            )
        """
        eid = self._next_eid
        self._next_eid += 1

        comp_dict: dict[str, object] = {}
        for comp_type_name, comp_instance in components.items():
            comp_dict[comp_type_name] = comp_instance

        self.entities[eid] = EntityData(name=name, components=comp_dict)
        return eid

    def remove_entity(self, entity_id: int) -> None:
        """移除实体定义。"""
        self.entities.pop(entity_id, None)
        if self.main_camera_entity_id == entity_id:
            self.main_camera_entity_id = None

    def get_entity(self, entity_id: int) -> Optional[EntityData]:
        """获取实体定义。"""
        return self.entities.get(entity_id)

    def get_component(
        self,
        entity_id: int,
        component_type: type,
    ) -> Optional[object]:
        """获取实体的指定类型组件。

        Args:
            entity_id: 实体 ID
            component_type: 组件类型 (如 Transform, MeshRenderer)

        Returns:
            组件实例, 不存在则返回 None
        """
        ed = self.entities.get(entity_id)
        if ed is None:
            return None
        return ed.components.get(component_type.__name__)

    def set_component(
        self,
        entity_id: int,
        component_instance: object,
    ) -> None:
        """设置/覆盖实体的组件。

        Args:
            entity_id: 实体 ID
            component_instance: 组件实例
        """
        ed = self.entities.get(entity_id)
        if ed is None:
            return
        ed.components[type(component_instance).__name__] = component_instance

    def remove_component(
        self,
        entity_id: int,
        component_type: type,
    ) -> None:
        """移除实体的指定类型组件。"""
        ed = self.entities.get(entity_id)
        if ed is None:
            return
        ed.components.pop(component_type.__name__, None)

    def get_entities_with_component(
        self,
        component_type: type,
    ) -> list[tuple[int, EntityData]]:
        """获取所有拥有指定组件的实体。

        Returns:
            [(entity_id, EntityData), ...]
        """
        type_name = component_type.__name__
        result: list[tuple[int, EntityData]] = []
        for eid, ed in self.entities.items():
            if type_name in ed.components:
                result.append((eid, ed))
        return result

    # ════════════════════════════════════════════════════════════
    # 拷贝 & 序列化
    # ════════════════════════════════════════════════════════════

    def copy(self) -> 'Scene':
        """深拷贝场景 — PIE 时从编辑器场景创建运行时副本。

        ⚠️ node_graph 也会被深拷贝，确保 Runtime 不修改编辑器的节点图。
        """
        return copy.deepcopy(self)

    def to_dict(self) -> dict:
        """转为可序列化的 dict。

        组件实例通过 dataclasses.asdict() 递归转换。
        自定义类型 (如 NodeCanvas) 需要实现自己的 to_dict()。
        """
        import dataclasses

        entities_dict: dict[str, dict] = {}
        for eid, ed in self.entities.items():
            comps: dict[str, dict] = {}
            for type_name, comp in ed.components.items():
                if hasattr(comp, '__dataclass_fields__'):
                    comps[type_name] = dataclasses.asdict(comp)
                else:
                    # 非 dataclass 组件 — 尝试 to_dict 否则跳过
                    if hasattr(comp, 'to_dict'):
                        comps[type_name] = comp.to_dict()
            entities_dict[str(eid)] = {
                "name": ed.name,
                "components": comps,
            }

        result: dict = {
            "name": self.name,
            "entities": entities_dict,
            "main_camera_entity_id": self.main_camera_entity_id,
            "next_eid": self._next_eid,
        }

        # 节点图序列化 (如果实现了 to_dict)
        if self.node_graph is not None and hasattr(self.node_graph, 'to_dict'):
            result["node_graph"] = self.node_graph.to_dict()

        return result

    @classmethod
    def from_dict(
        cls,
        data: dict,
        component_factories: Optional[dict[str, type]] = None,
    ) -> 'Scene':
        """从 dict 恢复 Scene。

        Args:
            data: to_dict() 的输出
            component_factories: {类型名: 组件类} 用于重建组件实例。
                                 不提供则组件以 dict 形式保留。

        Returns:
            Scene 实例
        """
        scene = cls(name=data.get("name", "Untitled"))
        scene._next_eid = data.get("next_eid", 1)
        scene.main_camera_entity_id = data.get("main_camera_entity_id")

        for eid_str, ed_data in data.get("entities", {}).items():
            eid = int(eid_str)
            comps: dict[str, object] = {}
            for type_name, comp_dict in ed_data.get("components", {}).items():
                factory = (component_factories or {}).get(type_name)
                if factory is not None and hasattr(factory, '__dataclass_fields__'):
                    # 使用工厂函数重建 dataclass 组件
                    comps[type_name] = factory(**comp_dict)
                else:
                    # 保留为 dict (调用方后续处理)
                    comps[type_name] = comp_dict

            scene.entities[eid] = EntityData(
                name=ed_data.get("name", "Entity"),
                components=comps,
            )

        return scene

    # ════════════════════════════════════════════════════════════
    # 调试
    # ════════════════════════════════════════════════════════════

    def __repr__(self) -> str:
        return (
            f"Scene(name='{self.name}', "
            f"entities={len(self.entities)}, "
            f"main_camera={self.main_camera_entity_id})"
        )

    def summary(self) -> str:
        """多行摘要，用于调试输出。"""
        lines = [f"Scene: {self.name}"]
        lines.append(f"  Entities: {len(self.entities)}")
        lines.append(f"  Main Camera: {self.main_camera_entity_id}")
        lines.append(f"  Node Graph: {'present' if self.node_graph else 'none'}")
        for eid, ed in self.entities.items():
            comp_names = list(ed.components.keys())
            lines.append(f"    [{eid}] {ed.name}: {comp_names}")
        return "\n".join(lines)
