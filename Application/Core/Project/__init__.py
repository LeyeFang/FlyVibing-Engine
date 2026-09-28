"""
Project（Core）— 运行时工程加载。

RuntimeProjectLoader：.myproj → 资源加载（materials/prefabs）→ id_map → 场景加载+重映射。
编辑器零依赖（不含 UI / imgui）；语义与 Application.Editor.ProjectManager 保持一致
（编辑器侧为真源，本模块为运行时子集 — 供 Player 入口使用）。
"""

from Application.Core.Project.RuntimeProjectLoader import (
    RuntimeProject,
    engine_root,
    load_project,
    load_resources,
    load_scene,
    remap_scene_materials,
    resolve_path,
)

__all__ = [
    "RuntimeProject",
    "engine_root",
    "load_project",
    "load_resources",
    "load_scene",
    "remap_scene_materials",
    "resolve_path",
]
