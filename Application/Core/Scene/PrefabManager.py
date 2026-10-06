"""
PrefabManager — Prefab 文件业务逻辑（保存/加载 entity tree）。

格式: .prefab (JSON)
  {
    "format_version": 1,
    "prefab_name": "MyPrefab",
    "root": { ... EntityData (递归含 children) ... }
  }

与 Scene 的关系:
  - Prefab 是轻量 entity tree 快照, Scene 保持不变
  - 加载 prefab → 返回临时 EntityData dict (含层级), 由调用方决定如何实例化
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from Application.Core.Scene.Scene import EntityData


# ═══════════════════════════════════════════════════════════════
# Prefab 数据容器
# ═══════════════════════════════════════════════════════════════

@dataclass
class PrefabData:
    """一个 Prefab 的反序列化结果 — 纯数据, 不含 ECS ID。"""

    prefab_name: str
    format_version: int = 1

    # root: 根实体数据
    root: EntityData = field(default_factory=EntityData)

    # children: { local_child_index → EntityData }, 含递归嵌套
    children: dict[int, EntityData] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# PrefabManager — 静态方法集
# ═══════════════════════════════════════════════════════════════

class PrefabManager:
    """Prefab 文件 I/O + 序列化 / 反序列化。"""

    FORMAT_VERSION = 1
    EXTENSION = ".prefab"

    # ── 保存 ──────────────────────────────────────────────────

    @staticmethod
    def save_entity_tree(
        filepath: str,
        root_entity_id: int,
        scene,  # SceneManager instance
        prefab_name: Optional[str] = None,
    ) -> bool:
        """将指定实体及其全部子实体保存为 .prefab 文件。

        父实体 ID 被重新映射为 prefab 内部索引 (0=root, 1..N=children),
        确保加载后层级关系正确恢复。
        """
        if prefab_name is None:
            prefab_name = os.path.splitext(os.path.basename(filepath))[0]

        # ── 递归收集实体树 ──
        entity_map: dict[int, EntityData] = {}
        _collect_tree(root_entity_id, scene, entity_map)

        if not entity_map:
            print(f"[Prefab] WARNING: entity #{root_entity_id} not found")
            return False

        # ── 建立旧 esper ID → 新 prefab-local 索引映射 ──
        old_to_new: dict[int, int] = {root_entity_id: 0}
        child_ids = sorted(eid for eid in entity_map if eid != root_entity_id)
        for i, eid in enumerate(child_ids, start=1):
            old_to_new[eid] = i

        # ── 序列化: parent_id 使用 prefab-local 索引 ──
        def _ed_to_dict_with_remap(ed: EntityData) -> dict:
            d = _entity_to_dict(ed)
            if ed.parent_id is not None and ed.parent_id in old_to_new:
                d["parent_id"] = old_to_new[ed.parent_id]
            elif "parent_id" in d:
                del d["parent_id"]
            return d

        root_data = _ed_to_dict_with_remap(entity_map[root_entity_id])
        children_dict: dict[str, dict] = {}
        for eid in child_ids:
            children_dict[str(old_to_new[eid])] = _ed_to_dict_with_remap(entity_map[eid])

        prefab_dict: dict = {
            "format_version": PrefabManager.FORMAT_VERSION,
            "prefab_name": prefab_name,
            "root": root_data,
            "children": children_dict,
        }

        # ── 写入文件 ──
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(prefab_dict, f, indent=2, ensure_ascii=False)

        print(f"[Prefab] Saved '{prefab_name}' → {filepath} "
              f"({len(entity_map)} entities)")
        return True

    # ── 加载 ──────────────────────────────────────────────────

    @staticmethod
    def load(filepath: str) -> Optional[PrefabData]:
        """从 .prefab 文件加载 PrefabData。

        Returns:
            PrefabData 或 None (文件不存在 / 格式错误)
        """
        if not os.path.exists(filepath):
            print(f"[Prefab] File not found: {filepath}")
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[Prefab] Failed to parse: {filepath} — {e}")
            return None

        fmt_ver = data.get("format_version", 1)
        prefab_name = data.get("prefab_name", "Unnamed")

        # ── 反序列化 root ──
        root_data = data.get("root", {})
        root_ed = _dict_to_entity(root_data)

        # ── 反序列化 children ──
        children: dict[int, EntityData] = {}
        for eid_str, ed_dict in data.get("children", {}).items():
            children[int(eid_str)] = _dict_to_entity(ed_dict)

        return PrefabData(
            prefab_name=prefab_name,
            format_version=fmt_ver,
            root=root_ed,
            children=children,
        )

    # ── 实例化到场景 ──────────────────────────────────────────

    @staticmethod
    def instantiate_to_scene(
        prefab_data: PrefabData,
        scene,  # SceneManager instance
    ) -> list[int]:
        """将 PrefabData 实例化到指定 SceneManager 的 esper 世界。

        创建实体 + 组件 + Transform, 保留层级关系。

        Args:
            prefab_data: 加载后的 PrefabData
            scene: 目标 SceneManager 实例

        Returns:
            新创建的实体 ID 列表 (root 在最前)
        """
        from Application.Core.Scene.BasicComponents import Transform, Camera, MeshRenderer, DirectionalLight
        import esper

        # 组件类型映射 (名称 → esper component class)
        _COMP_MAP = {
            "Transform": Transform,
            "Camera": Camera,
            "MeshRenderer": MeshRenderer,
            "DirectionalLight": DirectionalLight,
        }

        # 旧 ID → 新 ID 映射
        id_map: dict[int, int] = {}

        # ── 创建 root ──
        root_id = _instantiate_entity(prefab_data.root, scene, _COMP_MAP)
        id_map[0] = root_id  # root 在 prefab 中约定使用 eid=0
        created = [root_id]

        # ── 创建 children ──
        for old_eid, ed in sorted(prefab_data.children.items()):
            new_eid = _instantiate_entity(ed, scene, _COMP_MAP)
            id_map[old_eid] = new_eid
            created.append(new_eid)

            # ── 恢复父子关系 ──
            if ed.parent_id is not None and ed.parent_id in id_map:
                parent_new_eid = id_map[ed.parent_id]
                scene._entity_parent[new_eid] = parent_new_eid

        print(f"[Prefab] Instantiated '{prefab_data.prefab_name}' → "
              f"{len(created)} entities")
        return created


# ═══════════════════════════════════════════════════════════════
# 内部辅助
# ═══════════════════════════════════════════════════════════════

def _collect_tree(
    entity_id: int,
    scene,  # SceneManager
    out_map: dict[int, EntityData],
) -> None:
    """递归收集实体及其子实体到 out_map。"""
    from Application.Core.Scene.Scene import EntityData as ED
    if entity_id in out_map:
        return

    try:
        t = scene.GetEntityTransform(entity_id)
        pos = (t.position_x, t.position_y, t.position_z)
        rot = (t.rotation_x, t.rotation_y, t.rotation_z)
        scl = (t.scale_x, t.scale_y, t.scale_z)
    except Exception:
        pos, rot, scl = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)

    name = scene._entity_names.get(entity_id, f"Entity#{entity_id}")

    # 收集组件 (通过 esper)
    comp_dict: dict[str, object] = {}
    try:
        import esper
        from Application.Core.Scene.BasicComponents import Camera, MeshRenderer
        if esper.entity_exists(entity_id):
            # Transform (总是有)
            from Application.Core.Scene.BasicComponents import Transform
            comp_dict["Transform"] = Transform(
                position_x=pos[0], position_y=pos[1], position_z=pos[2],
                rotation_x=rot[0], rotation_y=rot[1], rotation_z=rot[2],
                scale_x=scl[0], scale_y=scl[1], scale_z=scl[2],
            )
            # 其他组件
            for comp_cls in (Camera, MeshRenderer):
                try:
                    comp = esper.component_for_entity(entity_id, comp_cls)
                    comp_dict[comp_cls.__name__] = comp
                except KeyError:
                    pass
    except Exception:
        pass

    parent_id = scene._entity_parent.get(entity_id)
    ed = ED(name=name, components=comp_dict, parent_id=parent_id)
    out_map[entity_id] = ed

    # 递归子实体
    for child_id in scene._entity_parent.keys():
        if scene._entity_parent.get(child_id) == entity_id:
            _collect_tree(child_id, scene, out_map)


def _entity_to_dict(ed: EntityData) -> dict:
    """EntityData → JSON-safe dict。"""
    import dataclasses
    from enum import Enum

    def _json_safe(obj):
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, tuple):
            return list(obj)
        if isinstance(obj, dict):
            return {k: _json_safe(v) for k, v in obj.items()}
        if isinstance(obj, (list, set)):
            return [_json_safe(v) for v in obj]
        return obj

    comps: dict[str, dict] = {}
    for type_name, comp in ed.components.items():
        if hasattr(comp, '__dataclass_fields__'):
            comps[type_name] = _json_safe(dataclasses.asdict(comp))
        elif isinstance(comp, dict):
            comps[type_name] = _json_safe(comp)

    result: dict = {
        "name": ed.name,
        "components": comps,
    }
    if ed.parent_id is not None:
        result["parent_id"] = ed.parent_id
    return result


def _dict_to_entity(d: dict) -> EntityData:
    """JSON dict → EntityData。"""
    return EntityData(
        name=d.get("name", "Entity"),
        components=d.get("components", {}),
        parent_id=d.get("parent_id"),
    )


def _instantiate_entity(
    ed: EntityData,
    scene,  # SceneManager
    comp_map: dict[str, type],
) -> int:
    """将 EntityData 实例化为 esper entity。

    自动处理 JSON 反序列化问题:
      - list → tuple (local_forward, up_vector 等)
      - str  → Enum (projection_type 等)
    """
    import esper
    from enum import Enum

    comps = []
    for type_name, comp_data in ed.components.items():
        comp_cls = comp_map.get(type_name)
        if comp_cls is not None and hasattr(comp_cls, '__dataclass_fields__'):
            # ── 类型适配: JSON 中 list → tuple, str → Enum ──
            fixed_data: dict = {}
            for field_name, field_value in comp_data.items():
                field_info = comp_cls.__dataclass_fields__.get(field_name)
                if field_info is not None:
                    target_type = field_info.type
                    # tuple 字段 (JSON 中是 list)
                    if target_type is tuple or hasattr(target_type, '__origin__') and target_type.__origin__ is tuple:
                        if isinstance(field_value, list):
                            field_value = tuple(field_value)
                    # Enum 字段 (JSON 中是 string)
                    elif isinstance(target_type, type) and issubclass(target_type, Enum):
                        if isinstance(field_value, str):
                            field_value = target_type(field_value)
                fixed_data[field_name] = field_value
            comps.append(comp_cls(**fixed_data))

    eid = esper.create_entity(*comps) if comps else esper.create_entity()

    scene.entities[str(eid)] = 1
    scene._entity_names[eid] = ed.name
    scene._editor_visible.add(eid)

    return eid
