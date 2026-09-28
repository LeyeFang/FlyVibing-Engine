"""
RuntimeProjectLoader — 运行时工程加载器（编辑器零依赖）。

职责（.myproj → 可运行场景）:
  1. 读 .myproj（version / name / startup_scene / scenes / resources）
  2. 加载资源文件到 ResourceManager（materials / prefabs 已实现；
     shaders / textures / meshes 与编辑器同缺口 → 记 warnings 并跳过）
  3. 产出 id_map（旧 material_id → 新 id），场景加载时重映射 entity 引用

语义与 Application.Editor.ProjectManager.open_project / _load_all_resources
保持一致 — 编辑器侧为真源，本模块为运行时子集：
  - 不 import Editor / UI / imgui（播放器链路边界）
  - 路径规则与编辑器一致: builtin:// | 绝对路径 | 相对 .myproj 目录

⚠️ 调用顺序要求: load_resources() 必须在 ResourceManager.Init() **之后**执行
   （内置资源已注册，material_count 基准与编辑器一致，场景内 id 才对得上）。

典型用法（Player 入口）:
    proj = load_project(".../MI-SSSEP.myproj")
    load_resources(proj)                      # 需要 ResourceManager 已 Init
    scene = load_scene(proj, proj.startup_scene)
    # scene.node_graph → RuntimeNodeLayer.set_canvas()
    # scene           → RuntimeNodeLayer.set_scene()
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

# 资源类别顺序与编辑器 _load_all_resources 一致
_RESOURCE_CATEGORIES = ("materials", "shaders", "textures", "meshes", "prefabs")

# 目前实现了加载的类别（与 Application.Editor.ProjectManager 同步；
# shaders / textures / meshes 为两侧共同缺口 — 见 Doc/Dev/project_export_protocol.md §7.5）
_SUPPORTED_CATEGORIES = frozenset({"materials", "prefabs"})


def engine_root() -> str:
    """引擎根目录（本文件位于 Application/Core/Project/ → 上三级）。"""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


@dataclass
class RuntimeProject:
    """已解析的 .myproj 工程（运行时视角的最小投影）。"""

    path: str                                  # .myproj 绝对路径
    name: str
    data: dict
    id_map: dict[int, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def dir(self) -> str:
        """工程根目录（= .myproj 所在目录）。"""
        return os.path.dirname(self.path)

    @property
    def startup_scene(self) -> str:
        """启动场景（相对路径; 未配置时回退首个场景, 无场景时空串）。"""
        scenes = self.data.get("scenes", [])
        return self.data.get("startup_scene") or (scenes[0] if scenes else "")

    @property
    def scene_list(self) -> list[str]:
        """工程内全部场景（相对路径列表）。"""
        return list(self.data.get("scenes", []))


# ════════════════════════════════════════════════════════════════
# 工程读取
# ════════════════════════════════════════════════════════════════

def load_project(project_path: str) -> RuntimeProject:
    """读取 .myproj 文件为 RuntimeProject（不做资源/场景加载）。

    Raises:
        FileNotFoundError / ValueError: 文件不存在或格式不正确
    """
    abs_path = os.path.abspath(project_path)
    with open(abs_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or "scenes" not in data:
        raise ValueError(
            f"'{project_path}' 不是有效的 .myproj — 缺少 'scenes' 键"
        )
    name = data.get("name") or os.path.splitext(os.path.basename(abs_path))[0]
    print(f"[RuntimeProject] Opened: {name} ({abs_path})")
    return RuntimeProject(path=abs_path, name=name, data=data)


# ════════════════════════════════════════════════════════════════
# 路径解析（与 ProjectManager._resolve_path 语义一致）
# ════════════════════════════════════════════════════════════════

def resolve_path(project: RuntimeProject, rel_path: str) -> str:
    """相对路径 或 builtin:// URI → 绝对路径。

    - "builtin://Name" → 从引擎 Resource 目录解析
    - 绝对路径 → 直接返回
    - 相对路径 → 相对于 .myproj 所在目录拼接
    """
    if not rel_path:
        return ""

    if rel_path.startswith("builtin://"):
        from Application.Resource.ResourceManager import ResourceManager

        name = rel_path[len("builtin://"):]
        path = ResourceManager.ResolveBuiltinPath(name)
        if path:
            return path
        # fallback: 在引擎 Resource 目录下按文件名 stem 搜索
        engine_resource = os.path.join(engine_root(), "Resource")
        for cur_root, _dirs, files in os.walk(engine_resource):
            for f in files:
                if os.path.splitext(f)[0] == name:
                    return os.path.join(cur_root, f)
        project.warnings.append(f"builtin 资源无法解析: {rel_path}")
        print(f"[RuntimeProject] WARNING: Cannot resolve builtin URI: {rel_path}")
        return ""

    if os.path.isabs(rel_path):
        return rel_path
    return os.path.join(project.dir, rel_path)


def parse_resource_entry(entry: Any) -> tuple[str, Optional[int]]:
    """解析资源条目：兼容 "path" 字符串与 {"path": ..., "material_id": ...} 两种格式。"""
    if isinstance(entry, dict):
        return entry.get("path", ""), entry.get("material_id")
    return entry, None


# ════════════════════════════════════════════════════════════════
# 资源加载
# ════════════════════════════════════════════════════════════════

def load_resources(project: RuntimeProject) -> dict[int, int]:
    """加载工程引用的资源文件到 ResourceManager（镜像编辑器实现）。

    Returns:
        {旧 material_id: 新 material_id} — 供场景加载时重映射 entity 引用。
    """
    from Application.Resource.ResourceManager import ResourceManager
    from Application.Resource.Material import Material

    resources = project.data.get("resources", {})
    id_map: dict[int, int] = {}
    loaded_count = 0

    for category in _RESOURCE_CATEGORIES:
        entries = resources.get(category, [])
        if category not in _SUPPORTED_CATEGORIES:
            if entries:
                project.warnings.append(
                    f"resources.{category}: {len(entries)} 项 — 运行时加载器尚未实现"
                    f"（与编辑器同缺口），已跳过"
                )
            continue

        for entry in entries:
            rel_path, old_id = parse_resource_entry(entry)

            # 内置资源 — ResourceManager.Init() 已加载
            if not rel_path or rel_path.startswith("builtin://"):
                continue

            abs_path = resolve_path(project, rel_path)
            if not abs_path or not os.path.isfile(abs_path):
                msg = f"资源缺失: {rel_path} (解析为 {abs_path})"
                project.warnings.append(msg)
                print(f"[RuntimeProject] WARNING: {msg}")
                continue

            try:
                if category == "materials":
                    mat = Material.load_from_file(abs_path)
                    ResourceManager.material_count += 1
                    new_id = ResourceManager.material_count
                    ResourceManager.loaded_material[str(new_id)] = mat
                    loaded_count += 1
                    if old_id is not None:
                        id_map[old_id] = new_id
                    print(f"[RuntimeProject] Loaded material '{mat.name}' → #{new_id}")
                elif category == "prefabs":
                    from Application.Core.Scene.PrefabManager import PrefabManager

                    pdata = PrefabManager.load(abs_path)
                    if pdata is None:
                        continue
                    already_loaded = any(
                        pd.get("name") == pdata.prefab_name
                        for pd in ResourceManager.loaded_prefab.values()
                    )
                    if not already_loaded:
                        pid = ResourceManager.LoadPrefab(abs_path)
                        if pid is not None:
                            loaded_count += 1
            except Exception as e:
                project.warnings.append(f"资源加载失败 {abs_path}: {e}")
                print(f"[RuntimeProject] Failed to load {abs_path}: {e}")

    project.id_map = id_map
    print(f"[RuntimeProject] {project.name}: loaded {loaded_count} resource(s), id_map={id_map}")
    return id_map


# ════════════════════════════════════════════════════════════════
# 场景加载
# ════════════════════════════════════════════════════════════════

def remap_scene_materials(scene, id_map: dict[int, int]) -> int:
    """遍历 Scene 的 EntityData，把 MeshRenderer.material_id 从旧 id 映射到新 id。

    与 ProjectManager._remap_scene_materials 语义一致；
    兼容 dict / 组件对象 两种组件存储形态。

    Returns:
        被重映射的实体数量
    """
    if not id_map:
        return 0
    remapped = 0
    for _eid, ed in scene.entities.items():
        mr = ed.components.get("MeshRenderer")
        if mr is None:
            continue
        if isinstance(mr, dict):
            old = mr.get("material_id", 0)
            if old in id_map:
                mr["material_id"] = id_map[old]
                remapped += 1
        elif hasattr(mr, "material_id") and mr.material_id in id_map:
            mr.material_id = id_map[mr.material_id]
            remapped += 1
    return remapped


def load_scene(project: RuntimeProject, scene_rel_path: str):
    """加载场景（相对/绝对/builtin 路径），应用 material id 重映射。

    Returns:
        Scene 实例（node_graph 已水合为 NodeCanvas — 契约注册保证）
    """
    from Application.Core.Scene.Scene import Scene

    # ★ 注册 "NodeCanvas" 反序列化契约 — 否则 from_dict 无法水合 node_graph
    from Application.Core.NodeGraph import canvas as _canvas_module  # noqa: F401

    abs_path = resolve_path(project, scene_rel_path)
    if not abs_path or not os.path.isfile(abs_path):
        raise FileNotFoundError(f"场景不存在: {scene_rel_path} (解析为 {abs_path})")

    scene = Scene.load_from_file(abs_path)
    scene._file_path = abs_path
    n = remap_scene_materials(scene, project.id_map)
    print(
        f"[RuntimeProject] Loaded scene: {scene.name} "
        f"({len(scene.entities)} entities"
        f"{f', remapped {n} material refs' if n else ''})"
    )
    return scene
