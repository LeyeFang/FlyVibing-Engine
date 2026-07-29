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
    _engine_root: str = ""            # ★ 引擎根目录 (懒加载)

    # ════════════════════════════════════════════════════════════
    # 引擎根目录 & 内置资源判断
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _get_engine_root(cls) -> str:
        """返回引擎根目录（懒加载）。
        
        ProjectManager.py 位于 Application/Editor/，
        引擎根目录为其上两级。
        """
        if not cls._engine_root:
            cls._engine_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..")
            )
        return cls._engine_root

    @classmethod
    def _is_builtin_resource(cls, abs_path: str) -> bool:
        """判断一个绝对路径是否落在引擎内置 Resource 目录内。"""
        if not abs_path:
            return False
        engine_resource_dir = os.path.join(cls._get_engine_root(), "Resource")
        try:
            return os.path.commonpath([
                os.path.normpath(abs_path),
                os.path.normpath(engine_resource_dir),
            ]) == os.path.normpath(engine_resource_dir)
        except ValueError:
            return False  # 不同盘符

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
            "scenes": [],
            "resources": {
                "materials": [],
                "shaders": [],
                "textures": [],
                "meshes": [],
                "prefabs": [],
            },
        }
        # ★ 新项目 → 重置视口为 3D
        try:
            from Application.Editor.UI.controllers.ViewportController import ViewportController
            ViewportController.switch_to_3d()
        except Exception:
            pass
        # ★ 新项目 → 清空旧场景 + 创建默认场景 + 重置节点编辑器画布
        try:
            from Application.Editor.EditorHost import EditorHost
            EditorHost._scenes.clear()
            EditorHost._active_scene = None
            # ★ 创建默认场景（放入 _scenes，后续 _ensure_default_scene 会同步 ECS 实体）
            EditorHost.create_scene("Default")
            from Application.Editor.UI.UIManager import UIManager
            panel = UIManager.find("Node Editor")
            if panel is not None:
                from Application.Editor.UI.controllers.node_editor.canvas import NodeCanvas
                panel._canvas = NodeCanvas()
                panel._canvas.create_default_nodes()
                panel._canvas_initialized = True
        except Exception as e:
            print(f"[Project] create_new cleanup failed: {e}")
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
            # ★ 加载所有 scene 文件到 _scenes 字典
            cls._load_all_scenes(id_map)
            # ★ 设置启动场景为活跃
            startup = cls._data.get("startup_scene", "")
            if startup:
                cls._activate_scene(startup)
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

    @classmethod
    def register_prefab(cls, file_path: str, prefab_id: int | None = None) -> None:
        """将 .prefab 文件路径及运行时 ID 注册到项目资源列表（自动去重）。"""
        rel = cls._to_relative(file_path)
        if not rel:
            return
        prefabs: list = cls._data.setdefault("resources", {}).setdefault("prefabs", [])
        for entry in prefabs:
            if entry.get("path") == rel:
                if prefab_id is not None:
                    entry["prefab_id"] = prefab_id
                return
        entry: dict = {"path": rel}
        if prefab_id is not None:
            entry["prefab_id"] = prefab_id
        prefabs.append(entry)
        cls._mark_dirty()

    @classmethod
    def register_scene(cls, scene_name: str) -> None:
        """注册场景名称（用于项目文件 scenes 列表）。"""
        scenes: list = cls._data.setdefault("scenes", [])
        if scene_name not in scenes:
            scenes.append(scene_name)
            cls._mark_dirty()
            print(f"[Project] Registered scene: {scene_name}")

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
        """保存项目文件 — 同步活跃场景后再保存所有场景到各自文件。

        关键: 不再对非活跃场景调用 SyncToScene，避免将活跃场景的 esper 数据
        写入其他 Scene 对象造成跨场景数据污染。
        """
        if not cls._project_path:
            return

        from Application.Editor.EditorHost import EditorHost
        scene_list: list[str] = []
        proj_dir = os.path.dirname(cls._project_path)

        # ★ 1. 先同步活跃场景 (捕获 esper 中最新的编辑 → Scene.entities)
        #    同时同步节点图 → Scene.node_graph
        active = EditorHost._active_scene
        if active is not None:
            try:
                EditorHost.scene.SyncToScene(active)
                EditorHost._sync_node_graph_to_scene()
            except Exception as e:
                print(f"[Project] Failed to sync active scene: {e}")

        # ★ 2. 保存所有场景到各自文件
        #    直接使用 Scene.entities 中已有的数据 (非活跃场景在切换时已同步)
        for sname, scene_obj in EditorHost._scenes.items():
            scene_path = getattr(scene_obj, '_file_path', None)
            if scene_path:
                # 已有路径 → 保存到原路径 (确保目录存在)
                try:
                    os.makedirs(os.path.dirname(scene_path), exist_ok=True)
                    scene_obj.save_to_file(scene_path)
                    rel = cls._to_relative(scene_path)
                    if rel:
                        scene_list.append(rel)
                    continue
                except Exception as e:
                    print(f"[Project] Failed to save scene '{sname}' to {scene_path}: {e}")
                    # 回退: 清除错误路径, 走 auto-save
                    scene_obj._file_path = None

            # 无路径或保存失败 → 自动保存到项目目录
            safe_name = sname.replace(" ", "_").replace("/", "_").replace("\\", "_")
            auto_path = os.path.join(proj_dir, "scenes", f"{safe_name}.scene")
            try:
                os.makedirs(os.path.dirname(auto_path), exist_ok=True)
                scene_obj.save_to_file(auto_path)
                scene_obj._file_path = auto_path
                rel = cls._to_relative(auto_path)
                if rel:
                    scene_list.append(rel)
                print(f"[Project] Auto-saved scene '{sname}' → {rel}")
            except Exception as e:
                print(f"[Project] Failed to auto-save scene '{sname}': {e}")

        cls._data["scenes"] = scene_list

        # ★ 3. 维护 startup_scene 的有效性
        startup = cls._data.get("startup_scene", "")
        if not startup and scene_list:
            cls._data["startup_scene"] = scene_list[0]
        elif startup and startup not in scene_list and scene_list:
            print(f"[Project] startup_scene '{startup}' no longer exists, using '{scene_list[0]}'")
            cls._data["startup_scene"] = scene_list[0]

        # ── 收集用户 prefab ──
        cls._sync_prefabs_to_data()

        os.makedirs(os.path.dirname(cls._project_path), exist_ok=True)
        with open(cls._project_path, "w", encoding="utf-8") as fh:
            json.dump(cls._data, fh, indent=2, ensure_ascii=False)

    @classmethod
    def _sync_prefabs_to_data(cls) -> None:
        """将 ResourceManager 中已注册的 prefab 同步到 _data['resources']['prefabs']。"""
        from Application.Resource.ResourceManager import ResourceManager
        prefabs: list[dict] = []
        for pid_str, pdata in ResourceManager.loaded_prefab.items():
            path = pdata.get('path', '')
            if not path:
                continue
            rel = cls._to_relative(path)
            if rel:
                prefabs.append({"path": rel, "prefab_id": int(pid_str)})
        cls._data.setdefault("resources", {})["prefabs"] = prefabs

    @classmethod
    def _save_scene_if_needed(cls) -> None:
        """保存项目前先同步活跃场景 (将 esper 变更写入 Scene.entities)。

        实际的 .scene 文件写入由 _save() 统一处理，避免重复写入或路径错误。
        """
        from Application.Editor.EditorHost import EditorHost
        active = EditorHost._active_scene
        if active is None:
            return
        try:
            EditorHost.scene.SyncToScene(active)
            EditorHost._sync_node_graph_to_scene()
        except Exception as e:
            print(f"[Project] Failed to sync active scene: {e}")

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
        """绝对路径 → 项目相对路径 或 builtin:// URI。

        - 内置资源（引擎 Resource/ 目录下）→ "builtin://资源名"
        - 用户资源 → 相对于项目根目录的路径
        - 项目尚未 Save As（无 project path）→ 保留绝对路径
        """
        if not abs_path:
            return ""

        # ★ 优先判断是否为引擎内置资源
        if cls._is_builtin_resource(abs_path):
            return cls._path_to_builtin_uri(abs_path)

        if not cls._project_path:
            return abs_path  # 未保存项目 → 暂存绝对路径
        proj_dir = os.path.dirname(cls._project_path)
        try:
            return os.path.relpath(abs_path, proj_dir)
        except ValueError:
            return abs_path  # 不同盘符，保留绝对路径

    @classmethod
    def _path_to_builtin_uri(cls, abs_path: str) -> str:
        """将引擎内置资源的绝对路径转为 builtin://Name URI。

        例如: D:\\Engine\\Resource\\Meshes\\Builtin\\3D\\Cube.obj → builtin://Cube
        """
        from Application.Resource.ResourceManager import ResourceManager

        # 遍历已加载资源，找匹配路径的内置资源名
        for loaded_dict in [
            ResourceManager.loaded_mesh,
            ResourceManager.loaded_shader,
            ResourceManager.loaded_texture,
            ResourceManager.loaded_material,
            ResourceManager.loaded_prefab,
        ]:
            for rid, info in loaded_dict.items():
                # Material 是对象，其他资源是 dict，兼容两种存储格式
                if isinstance(info, dict):
                    if info.get('path') == abs_path and 'builtin_name' in info:
                        return f"builtin://{info['builtin_name']}"
                elif hasattr(info, 'builtin_name'):
                    info_path = getattr(info, '_file_path', '') or getattr(info, 'path', '')
                    if info_path == abs_path:
                        return f"builtin://{info.builtin_name}"

        # fallback: 用文件名 stem 作为名称
        return f"builtin://{os.path.splitext(os.path.basename(abs_path))[0]}"

    @classmethod
    def _get_all_resource_paths(cls) -> list[str]:
        """获取所有注册的资源路径（相对于项目根目录）。兼容新旧格式。"""
        result = []
        for category in ("materials", "shaders", "textures", "meshes", "prefabs"):
            for entry in cls._data.get("resources", {}).get(category, []):
                path = entry if isinstance(entry, str) else entry.get("path", "")
                if path:
                    result.append(path)
        return result

    @classmethod
    def _resolve_path(cls, rel_path: str) -> str:
        """相对路径 或 builtin:// URI → 绝对路径。

        - "builtin://Name" → 从引擎 Resource 目录解析
        - 绝对路径 → 直接返回
        - 相对路径 → 相对于项目根目录拼接
        """
        if not rel_path:
            return ""

        # ★ 识别 builtin:// 协议
        if rel_path.startswith("builtin://"):
            return cls._resolve_builtin_uri(rel_path)

        if os.path.isabs(rel_path):
            return rel_path
        proj_dir = os.path.dirname(cls._project_path) if cls._project_path else ""
        return os.path.join(proj_dir, rel_path)

    @classmethod
    def _resolve_builtin_uri(cls, uri: str) -> str:
        """将 builtin://Name 解析为引擎内的绝对路径。

        例如: builtin://Cube → D:\\Engine\\Resource\\Meshes\\Builtin\\3D\\Cube.obj
        """
        from Application.Resource.ResourceManager import ResourceManager

        name = uri[len("builtin://"):]
        path = ResourceManager.ResolveBuiltinPath(name)
        if path:
            return path

        # fallback: 在引擎 Resource 目录下搜索同名文件
        engine_resource = os.path.join(cls._get_engine_root(), "Resource")
        for root, dirs, files in os.walk(engine_resource):
            for f in files:
                stem = os.path.splitext(f)[0]
                if stem == name:
                    return os.path.join(root, f)

        print(f"[Project] WARNING: Cannot resolve builtin URI: {uri}")
        return ""

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
        for category in ("materials", "shaders", "textures", "meshes", "prefabs"):
            for entry in cls._data.get("resources", {}).get(category, []):
                rel_path, old_id = cls._parse_resource_entry(entry)

                # ★ 跳过内置资源 — ResourceManager.Init() 已经加载过了
                if rel_path.startswith("builtin://"):
                    continue

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
                    elif category == "prefabs":
                        from Application.Core.Scene.PrefabManager import PrefabManager
                        # 跳过已加载的同名 prefab (如 builtin)
                        pdata = PrefabManager.load(abs_path)
                        if pdata is None:
                            continue
                        already_loaded = any(
                            pd.get('name') == pdata.prefab_name
                            for pd in ResourceManager.loaded_prefab.values()
                        )
                        if not already_loaded:
                            pid = ResourceManager.LoadPrefab(abs_path)
                            if pid is not None:
                                loaded_count += 1
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
    def _load_all_scenes(cls, id_map: dict[int, int] | None = None) -> None:
        """加载项目文件中 scenes 列表里的所有场景到 EditorHost._scenes。"""
        from Application.Core.Scene.Scene import Scene
        from Application.Editor.EditorHost import EditorHost

        for rel_path in cls._data.get("scenes", []):
            abs_path = cls._resolve_path(rel_path)
            if not os.path.isfile(abs_path):
                print(f"[Project] WARNING: Scene not found: {abs_path}")
                continue
            try:
                scene = Scene.load_from_file(abs_path)
                # ★ 重映射 material_id
                if id_map:
                    cls._remap_scene_materials(scene, id_map)
                EditorHost._scenes[scene.name] = scene
                print(f"[Project] Loaded scene: {scene.name} ({len(scene.entities)} entities)")
            except Exception as e:
                print(f"[Project] Failed to load scene {abs_path}: {e}")

    @classmethod
    def _activate_scene(cls, rel_path: str) -> None:
        """激活指定路径的场景 (设为当前编辑场景)。"""
        from Application.Editor.EditorHost import EditorHost
        abs_path = cls._resolve_path(rel_path)
        for sname, scene in EditorHost._scenes.items():
            if getattr(scene, '_file_path', '') == abs_path:
                EditorHost.switch_scene(sname)
                return
        # 场景不在 _scenes 中 → 直接加载
        cls._load_startup_scene(rel_path, None)

    @classmethod
    def _load_startup_scene(cls, rel_path: str, id_map: dict[int, int] | None = None) -> None:
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
    def _remap_scene_materials(cls, scene, id_map: dict[int, int]) -> None:
        """遍历 Scene 对象的 EntityData，将 material_id 从旧 ID 映射到新 ID。"""
        for eid, ed in scene.entities.items():
            mr = ed.components.get("MeshRenderer")
            if mr is None:
                continue
            if isinstance(mr, dict):
                old = mr.get("material_id", 0)
                if old in id_map:
                    mr["material_id"] = id_map[old]
            elif hasattr(mr, 'material_id') and mr.material_id in id_map:
                mr.material_id = id_map[mr.material_id]

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
