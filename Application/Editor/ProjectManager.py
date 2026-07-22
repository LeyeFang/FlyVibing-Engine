"""
ProjectManager — 项目文件 (.myproj) 管理。

.project 文件格式 (JSON):
  {
    "version": "0.1.0",
    "name": "MyProject",
    "startup_scene": "scenes/main.scene",
    "resources": {
      "materials": ["materials/red.mat", "materials/blue.mat"],
      "shaders":   [],
      "textures":  [],
      "meshes":    []
    }
  }

职责:
  - 记录项目元数据（名称、启动场景）
  - 记录需要自动加载的资源文件路径列表
  - 打开项目时自动加载所有资源 → 再加载场景
"""

from __future__ import annotations
import json
import os
from typing import Optional


class ProjectManager:
    """项目文件管理器 — 纯数据层，不依赖渲染/窗口。"""

    _instance: Optional['ProjectManager'] = None
    _project_path: str = ""           # .myproj 文件路径 (空 = 未保存)
    _project_name: str = ""           # 项目名 (独立于文件路径)
    _data: dict = {}
    _is_saved: bool = False           # ★ 是否已保存到磁盘
    _window_title_base: str = "MyGameEngine"

    # ════════════════════════════════════════════════════════════
    # 单例
    # ════════════════════════════════════════════════════════════

    @classmethod
    def get(cls) -> 'ProjectManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ════════════════════════════════════════════════════════════
    # Project I/O
    # ════════════════════════════════════════════════════════════

    @classmethod
    def create_new(cls, name: str = "Untitled") -> None:
        """创建新项目（仅内存，不写盘）。标记为未保存。

        同时重置编辑器视口到默认 3D 模式。
        """
        cls._project_path = ""
        cls._project_name = name
        cls._is_saved = False
        cls._data = {
            "version": "0.1.0",
            "name": name,
            "startup_scene": "",
            "resources": {
                "materials": [],
                "shaders": [],
                "textures": [],
                "meshes": [],
            },
        }
        # ★ 新项目 → 重置视口为 3D
        try:
            from Application.Editor.UI.controllers.ViewportController import ViewportController
            ViewportController.switch_to_3d()
        except Exception:
            pass
        print(f"[Project] Created (unsaved): {name}")

    @classmethod
    def open_project(cls, path: str) -> bool:
        """打开 .myproj 文件 → 自动加载所有资源。"""
        if not os.path.isfile(path):
            print(f"[Project] File not found: {path}")
            return False
        try:
            with open(path, "r", encoding="utf-8") as fh:
                cls._data = json.load(fh)
            cls._project_path = os.path.abspath(path)
            cls._project_name = cls._data.get("name", os.path.splitext(os.path.basename(path))[0])
            cls._is_saved = True
            cls._update_window_title()

            # ★ 清空旧项目的场景列表，避免跨项目累积
            from Application.Editor.EditorHost import EditorHost
            EditorHost._scenes.clear()
            EditorHost._active_scene = None

            print(f"[Project] Opened: {cls._project_name}  ({len(cls._get_all_resource_paths())} resources)")
            # ★ 自动加载所有资源 → 获取 ID 映射
            id_map = cls._load_all_resources()
            # ★ 自动加载启动场景 → 重映射 material_id
            startup = cls._data.get("startup_scene", "")
            if startup:
                cls._load_startup_scene(startup, id_map)
            return True
        except Exception as e:
            print(f"[Project] Failed to open: {e}")
            return False

    @classmethod
    def save_project(cls) -> bool:
        """保存到当前路径。自动先保存场景。未保存过则返回 False。"""
        if not cls._project_path:
            print("[Project] Save failed: no path (use Save As first)")
            return False
        cls._save_scene_if_needed()
        cls._save()
        cls._is_saved = True
        cls._update_window_title()
        print(f"[Project] Saved: {cls._project_path}")
        return True

    @classmethod
    def save_project_as(cls, path: str) -> bool:
        """另存为 → 更新路径并保存。自动先保存场景。"""
        if not path:
            return False
        if not path.endswith(".myproj"):
            path += ".myproj"
        cls._project_path = os.path.abspath(path)
        cls._project_name = os.path.splitext(os.path.basename(path))[0]
        cls._data["name"] = cls._project_name
        cls._save_scene_if_needed()
        cls._save()
        cls._is_saved = True
        cls._update_window_title()
        print(f"[Project] Saved As: {cls._project_path}")
        return True

    @classmethod
    def is_open(cls) -> bool:
        return bool(cls._data)

    @classmethod
    def is_saved(cls) -> bool:
        return cls._is_saved

    @classmethod
    def get_project_name(cls) -> str:
        """获取当前项目名（供窗口标题等使用）。"""
        return cls._project_name or "Untitled"

    @classmethod
    def get_project_dir(cls) -> str:
        """返回项目根目录（.myproj 所在目录）。"""
        if cls._project_path:
            return os.path.dirname(cls._project_path)
        return ""

    @classmethod
    def _update_window_title(cls) -> None:
        """更新窗口标题：dirty 时加 * 前缀。"""
        try:
            from Application.Editor.EditorHost import EditorHost
            window = EditorHost.get_window()
            if window is None:
                return
            if cls._project_name:
                dirty = "*" if not cls._is_saved else ""
                window.SetTitle(f"Project: {dirty}{cls._project_name}")
            else:
                window.SetTitle(cls._window_title_base)
        except Exception:
            pass  # 窗口未创建时静默失败

    # ════════════════════════════════════════════════════════════
    # Resource 管理
    # ════════════════════════════════════════════════════════════

    @classmethod
    def register_material(cls, file_path: str, material_id: int | None = None) -> None:
        """将 .mat 文件路径及运行时 ID 注册到项目资源列表（自动去重）。"""
        rel = cls._to_relative(file_path)
        if not rel:
            return
        mats: list = cls._data.setdefault("resources", {}).setdefault("materials", [])
        # 检查是否已注册（按路径匹配）
        for entry in mats:
            existing = entry if isinstance(entry, dict) else {"path": entry}
            if existing.get("path") == rel:
                if material_id is not None:
                    if isinstance(entry, str):
                        mats.remove(entry)
                        mats.append({"path": rel, "material_id": material_id})
                    else:
                        entry["material_id"] = material_id
                return
        entry: dict = {"path": rel}
        if material_id is not None:
            entry["material_id"] = material_id
        mats.append(entry)
        cls._mark_dirty()
        print(f"[Project] Registered material: {rel} (id={material_id})")

    @classmethod
    def set_startup_scene(cls, scene_path: str) -> None:
        """设置启动场景路径。"""
        rel = cls._to_relative(scene_path)
        if not rel:
            return
        cls._data["startup_scene"] = rel
        cls._mark_dirty()

    @classmethod
    def get_startup_scene(cls) -> str:
        """获取启动场景的绝对路径。"""
        rel = cls._data.get("startup_scene", "")
        if rel and cls._project_path:
            return os.path.join(os.path.dirname(cls._project_path), rel)
        return ""

    # ════════════════════════════════════════════════════════════
    # 内部
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _save(cls) -> None:
        if not cls._project_path:
            return
        os.makedirs(os.path.dirname(cls._project_path), exist_ok=True)
        with open(cls._project_path, "w", encoding="utf-8") as fh:
            json.dump(cls._data, fh, indent=2, ensure_ascii=False)

    @classmethod
    def _save_scene_if_needed(cls) -> None:
        """保存项目前先保存当前场景（如果有路径）。"""
        scene_rel = cls._data.get("startup_scene", "")
        if not scene_rel:
            return
        scene_path = cls._resolve_path(scene_rel)
        if not scene_path:
            return
        from Application.Editor.EditorHost import EditorHost
        EditorHost.save_active_scene_to_file(scene_path)
        print(f"[Project] Auto-saved scene: {scene_rel}")

    @classmethod
    def _auto_save(cls) -> None:
        """自动保存：仅当已有文件路径时写入（未 Save As 的项目不写盘）。"""
        if cls._project_path:
            cls._save()

    @classmethod
    def _mark_dirty(cls) -> None:
        """标记 project 有未保存的更改。"""
        cls._is_saved = False

    @classmethod
    def _to_relative(cls, abs_path: str) -> str:
        """绝对路径 → 相对于项目根目录的路径。
        若项目尚未 Save As（无 project path），保留绝对路径。
        """
        if not abs_path:
            return ""
        if not cls._project_path:
            return abs_path  # 未保存项目 → 暂存绝对路径
        proj_dir = os.path.dirname(cls._project_path)
        try:
            return os.path.relpath(abs_path, proj_dir)
        except ValueError:
            return abs_path  # 不同盘符，保留绝对路径

    @classmethod
    def _get_all_resource_paths(cls) -> list[str]:
        """获取所有注册的资源路径（相对于项目根目录）。兼容新旧格式。"""
        result = []
        for category in ("materials", "shaders", "textures", "meshes"):
            for entry in cls._data.get("resources", {}).get(category, []):
                path = entry if isinstance(entry, str) else entry.get("path", "")
                if path:
                    result.append(path)
        return result

    @classmethod
    def _resolve_path(cls, rel_path: str) -> str:
        """相对路径 → 绝对路径。"""
        if os.path.isabs(rel_path):
            return rel_path
        proj_dir = os.path.dirname(cls._project_path) if cls._project_path else ""
        return os.path.join(proj_dir, rel_path)

    @classmethod
    def _load_all_resources(cls) -> dict[int, int]:
        """加载项目引用的所有资源文件到 ResourceManager。
        
        Returns:
            {old_material_id: new_material_id} 映射，供场景加载时重映射 entity 引用。
        """
        from Application.Resource.ResourceManager import ResourceManager
        from Application.Resource.Material import Material

        id_map: dict[int, int] = {}
        loaded_count = 0
        for category in ("materials", "shaders", "textures", "meshes"):
            for entry in cls._data.get("resources", {}).get(category, []):
                rel_path, old_id = cls._parse_resource_entry(entry)
                abs_path = cls._resolve_path(rel_path)
                if not os.path.isfile(abs_path):
                    print(f"[Project] WARNING: Resource not found: {abs_path}")
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
                        print(f"[Project] Loaded material '{mat.name}' → #{new_id}")
                except Exception as e:
                    print(f"[Project] Failed to load {abs_path}: {e}")
        if loaded_count:
            print(f"[Project] Loaded {loaded_count} resources, id_map={id_map}")
        return id_map

    @classmethod
    def _parse_resource_entry(cls, entry) -> tuple[str, int | None]:
        """解析资源条目：兼容旧格式 "path" 和新格式 {"path": ..., "material_id": ...}。"""
        if isinstance(entry, dict):
            return entry.get("path", ""), entry.get("material_id")
        return entry, None  # 旧格式：纯路径字符串

    @classmethod
    def _load_startup_scene(cls, rel_path: str, id_map: dict[int, int] | None = None) -> None:
        """加载启动场景，并重映射 entity 的 material_id。"""
        abs_path = cls._resolve_path(rel_path)
        if not os.path.isfile(abs_path):
            print(f"[Project] WARNING: Startup scene not found: {abs_path}")
            return
        from Application.Editor.EditorHost import EditorHost
        EditorHost.load_scene_from_file(abs_path)
        # ★ 重映射 entity material_id：旧 ID → 新 ID
        if id_map:
            cls._remap_entity_materials(id_map)

    @classmethod
    def _remap_entity_materials(cls, id_map: dict[int, int]) -> None:
        """遍历所有 entity 的 MeshRenderer，将 material_id 从旧 ID 映射到新 ID。"""
        import esper
        from Application.Core.Scene.BasicComponents import MeshRenderer
        from Application.Editor.EditorHost import EditorHost

        remapped = 0
        for entity_id, mr in esper.get_component(MeshRenderer):
            if mr.material_id in id_map:
                old = mr.material_id
                mr.material_id = id_map[old]
                remapped += 1
                # ★ 通知渲染器重新注册（新 material 需要新 GPU 资源）
                _renderer = getattr(EditorHost, 'renderer', None)
                if _renderer is not None:
                    from Application.Core.Renderer.RenderCommand import EntityRegistrationCommand
                    _renderer.enqueue(EntityRegistrationCommand(entity_id, register=True))
        if remapped:
            print(f"[Project] Remapped {remapped} entity materials: {id_map}")
