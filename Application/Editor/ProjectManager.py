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
                from Application.Core.NodeGraph.canvas import NodeCanvas
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
        # ★ 换根前先把存量相对路径固化为绝对路径 —
        #   相对路径的语义是"相对于当前 .myproj 目录", 换根后会指向错误位置
        cls._denormalize_paths_to_absolute()
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
    def get_project_path(cls) -> str:
        """返回当前 .myproj 绝对路径（未保存时为空串）。"""
        return cls._project_path

    # ════════════════════════════════════════════════════════════
    # 自包含导出 (Export Project Bundle)
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _sanitize_name(name: str, fallback: str = "Untitled") -> str:
        """文件名/目录名安全化（保留中英文与常见符号，替换路径分隔符等）。"""
        safe = "".join(
            c if (c.isalnum() or c in "._- ") else "_" for c in (name or "")
        ).strip()
        return safe or fallback

    @staticmethod
    def _unique_name(name: str, used: set) -> str:
        """批内同名去重: a.mat → a.mat, a_2.mat, ..."""
        if name not in used:
            used.add(name)
            return name
        stem, ext = os.path.splitext(name)
        i = 2
        while f"{stem}_{i}{ext}" in used:
            i += 1
        unique = f"{stem}_{i}{ext}"
        used.add(unique)
        return unique

    @classmethod
    def export_project_bundle(cls, target_parent_dir: str, include_player: bool = True) -> dict | None:
        """导出自包含工程包 — 项目文件 + 全部场景 + 用户资源，路径全部相对化。

        include_player=True（默认, File ▸ Export 使用）时额外附游戏层:
          game.json + Application/ 引擎副本 + Resource/ 内置资源
          + runtime/ 预装 Python 环境 + wheelhouse/ 离线重建材料 + run_game.cmd 启动器
          → 双击即玩（详见 Doc/Dev/runtime_packaging_protocol.md）。

        输出结构::

            <target_parent>/<ProjectName>/
                <ProjectName>.myproj        # scenes/resources/startup 全部相对路径
                scenes/<Name>.scene          # 全部场景（活跃场景先同步，节点图随场景）
                assets/<category>/<file>     # materials / prefabs / ...（builtin:// 不复制）
                export_manifest.json         # 导出清单（来源 / 时间 / 文件 / 告警）

        行为约定:
          - 不修改当前工程的任何状态与磁盘文件（纯快照）
          - 未保存过的工程不可导出（先 Save Project As）
          - 目标目录已存在且非空时：仅当它是本工具的旧导出（含 manifest）才允许覆盖，
            否则拒绝，防止误写用户目录；不会写入当前工程目录本身
          - 工程目录外的资源会被复制进导出包 → 导出物可整体拷贝/迁移

        Returns: 摘要 dict {dir, project, scenes, assets, bytes, warnings} | None
        """
        import copy as _copy
        import shutil as _shutil
        from datetime import datetime as _dt

        from Application.Editor.EditorHost import EditorHost

        if not cls._project_path:
            print("[Export] Project is not saved yet — use File ▸ Save Project As... first")
            return None
        if not target_parent_dir or not os.path.isdir(target_parent_dir):
            print(f"[Export] Parent folder not found: {target_parent_dir}")
            return None

        # ★ 只做内存同步（最新编辑 → Scene / 节点图），不写盘
        cls._save_scene_if_needed()

        name = cls.get_project_name()
        safe = cls._sanitize_name(name)
        out_dir = os.path.abspath(os.path.join(target_parent_dir, safe))
        cur_dir = os.path.dirname(os.path.abspath(cls._project_path))
        if os.path.normcase(out_dir) == os.path.normcase(cur_dir):
            print("[Export] Target equals the current project folder — choose another location")
            return None

        manifest_path = os.path.join(out_dir, "export_manifest.json")
        if os.path.isdir(out_dir) and os.listdir(out_dir) and not os.path.isfile(manifest_path):
            print(f"[Export] Target folder is not empty (not a previous export): {out_dir}")
            return None

        # ★ 覆盖行为: 目标是旧导出（manifest 有效）→ 干净重建，
        #    防止上次导出的残留（改名场景 / 旧轮子 / 旧引擎文件）混入新包。
        #    例外: 保留 output/（实验数据）不动。
        if os.path.isdir(out_dir) and os.path.isfile(manifest_path):
            for entry in os.listdir(out_dir):
                if entry == "output":
                    print("[Export]   preserving output/ (experiment data)")
                    continue
                p = os.path.join(out_dir, entry)
                try:
                    if os.path.isdir(p):
                        _shutil.rmtree(p)
                    else:
                        os.remove(p)
                except OSError as e:
                    print(f"[Export]   WARNING: stale cleanup failed: {p} ({e})")

        os.makedirs(out_dir, exist_ok=True)
        # 先写占位清单：作为覆盖保护标记，同时保证中断后重试不被拒绝
        cls._write_json(manifest_path, {
            "type": "project_bundle",
            "version": "0.1.0",
            "name": name,
            "status": "in_progress",
            "created_iso": _dt.now().isoformat(timespec="seconds"),
        })

        warnings: list[str] = []
        files: list[str] = []
        total_bytes = 0

        # ── 1. 场景 ──
        scenes_rel: list[str] = []
        scene_keys: list[tuple[str, str]] = []   # (源 scene._file_path 键, 导出相对路径)
        used_scene_names: set = set()
        for sname, scene_obj in EditorHost._scenes.items():
            fname = cls._unique_name(cls._sanitize_name(sname) + ".scene", used_scene_names)
            dst = os.path.join(out_dir, "scenes", fname)
            try:
                scene_obj.save_to_file(dst)
            except Exception as e:
                warnings.append(f"scene '{sname}' save failed: {e}")
                continue
            rel = f"scenes/{fname}"
            scenes_rel.append(rel)
            files.append(rel)
            total_bytes += os.path.getsize(dst) if os.path.isfile(dst) else 0
            src = getattr(scene_obj, "_file_path", "") or ""
            scene_keys.append((cls._path_key(src), rel))

        # ── 2. 资源（全部类别；builtin:// 保留不复制） ──
        res_out: dict[str, list] = {}
        res = cls._data.get("resources", {})
        id_keys = {"materials": "material_id", "prefabs": "prefab_id"}
        copied = 0
        for category in ("materials", "shaders", "textures", "meshes", "prefabs"):
            res_out[category] = []
            used_asset_names: set = set()
            for entry in res.get(category, []):
                rel_path, rid = cls._parse_resource_entry(entry)
                if not rel_path:
                    continue
                item: dict = {"path": rel_path}
                id_key = id_keys.get(category)
                if id_key and rid is not None:
                    item[id_key] = rid
                if rel_path.startswith("builtin://"):
                    res_out[category].append(item)
                    continue
                abs_path = cls._resolve_path(rel_path)
                if not (abs_path and os.path.isfile(abs_path)):
                    warnings.append(f"{category}: file missing, dropped from bundle: {rel_path}")
                    continue
                fname = cls._unique_name(os.path.basename(abs_path), used_asset_names)
                dst_rel = f"assets/{category}/{fname}"
                dst = os.path.join(out_dir, dst_rel)
                try:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    _shutil.copy2(abs_path, dst)
                except OSError as e:
                    warnings.append(f"{category}: copy failed ({e}): {abs_path}")
                    continue
                item["path"] = dst_rel
                res_out[category].append(item)
                files.append(dst_rel)
                total_bytes += os.path.getsize(dst)
                copied += 1

        # ── 3. 启动场景映射（按真实文件路径 → 导出相对路径） ──
        startup = cls._data.get("startup_scene", "")
        startup_key = cls._path_key(cls._resolve_path(startup)) if startup else ""
        startup_rel = ""
        for src_key, rel in scene_keys:
            if startup_key and src_key and src_key == startup_key:
                startup_rel = rel
                break
        if not startup_rel and scenes_rel:
            startup_rel = scenes_rel[0]
            if startup:
                warnings.append(
                    f"startup scene '{startup}' not found among project scenes → using '{startup_rel}'"
                )

        # ── 4. 项目文件（路径重写副本，不改动当前工程数据） ──
        data = _copy.deepcopy(cls._data)
        data["name"] = name
        data["scenes"] = scenes_rel
        data["startup_scene"] = startup_rel
        data.setdefault("resources", {})
        for category, items in res_out.items():
            data["resources"][category] = items
        proj_file = f"{safe}.myproj"
        cls._write_json(os.path.join(out_dir, proj_file), data)
        total_bytes += os.path.getsize(os.path.join(out_dir, proj_file))

        # ── 5. 游戏层（include_player）: 清单 + 冻结引擎 + Python 环境 + 启动器 ──
        game_info: dict | None = None
        if include_player:
            engine_root = cls._get_engine_root()

            # 5a. game.json（播放器清单）
            cls._write_json(os.path.join(out_dir, "game.json"), {
                "format": "mge.game/1",
                "title": name,
                "project": proj_file,
                "startup_scene": startup_rel,
                "window": {"mode": "auto"},
                "output_dir": "output",
                "engine": {
                    "version": data.get("version", ""),
                    "exported_iso": _dt.now().isoformat(timespec="seconds"),
                },
            })

            # 5b. 冻结引擎副本（Resource 不含 wheels/ 与 runtime/ — 另放顶层）
            app_files, app_bytes = cls._copy_tree_for_export(
                os.path.join(engine_root, "Application"),
                os.path.join(out_dir, "Application"), warnings,
            )
            res_files, res_bytes = cls._copy_tree_for_export(
                os.path.join(engine_root, "Resource"),
                os.path.join(out_dir, "Resource"), warnings,
                exclude_dirs={"wheels", "runtime"},
            )

            # 5b-2. Utils 工具（仅 User 层 — Dev 工具链不进游戏包）
            utils_files, utils_bytes = cls._copy_tree_for_export(
                os.path.join(engine_root, "Utils", "User"),
                os.path.join(out_dir, "Utils", "User"), warnings,
            )
            _utils_init = os.path.join(engine_root, "Utils", "__init__.py")
            if os.path.isfile(_utils_init):
                _dst_init = os.path.join(out_dir, "Utils", "__init__.py")
                os.makedirs(os.path.dirname(_dst_init), exist_ok=True)
                _shutil.copy2(_utils_init, _dst_init)
                utils_files += 1

            # 5c. Python 运行时镜像（预装环境, 双轨制主轨）
            runtime_info = {"included": False, "files": 0, "bytes": 0}
            runtime_src = os.path.join(engine_root, "Resource", "runtime")
            if os.path.isdir(runtime_src):
                rf, rb = cls._copy_tree_for_export(
                    runtime_src, os.path.join(out_dir, "runtime"), warnings)
                runtime_info = {"included": True, "files": rf, "bytes": rb}
            else:
                warnings.append(
                    "runtime image missing (Resource/runtime) — run "
                    "Utils/Dev/prepare_runtime.py first; exported game "
                    "will not be standalone"
                )

            # 5d. wheelhouse（离线重建材料, 双轨制备轨）
            wh_files, wh_bytes = 0, 0
            wheels_src = os.path.join(engine_root, "Resource", "wheels")
            if os.path.isdir(wheels_src):
                wh_files, wh_bytes = cls._copy_tree_for_export(
                    wheels_src, os.path.join(out_dir, "wheelhouse"), warnings)

            # 5e. 启动器（ASCII only — 避免代码页问题）
            launcher = "\r\n".join([
                "@echo off",
                "setlocal",
                'cd /d "%~dp0"',
                'set "PYTHONNOUSERSITE=1"',
                'set "PYTHONDONTWRITEBYTECODE=1"',
                'set "PYTHON_GIL=0"',
                'set "PYEXE=runtime\\python3.14t.exe"',
                'if not exist "%PYEXE%" set "PYEXE=runtime\\python.exe"',
                'if not exist "%PYEXE%" (',
                "    echo [ERROR] runtime interpreter missing - re-export after preparing the runtime image",
                "    pause",
                "    exit /b 1",
                ")",
                '"%PYEXE%" -Xgil=0 "Application\\PlayerEntry.py" "game.json" %*',
                "if errorlevel 1 pause",
                "endlocal",
            ]) + "\r\n"
            with open(os.path.join(out_dir, "run_game.cmd"), "w",
                      encoding="ascii", newline="") as fh:
                fh.write(launcher)

            game_info = {
                "game_json": "game.json",
                "launcher": "run_game.cmd",
                "runtime": runtime_info,
                "application_files": app_files,
                "resource_files": res_files,
                "utils_files": utils_files,
                "wheelhouse_files": wh_files,
                "engine_bytes": app_bytes + res_bytes + utils_bytes,
                "wheelhouse_bytes": wh_bytes,
            }
            print(
                f"[Export]   game layer: App {app_files}f / Resource {res_files}f / "
                f"Utils {utils_files}f / "
                f"runtime {'yes' if runtime_info['included'] else 'MISSING'} / "
                f"wheelhouse {wh_files}f"
            )

        # ── 6. 清单（覆盖占位版本） ──
        cls._write_json(manifest_path, {
            "type": "project_bundle",
            "version": "0.1.0",
            "name": name,
            "created_iso": _dt.now().isoformat(timespec="seconds"),
            "source_project": cls._project_path,
            "engine_root": cls._get_engine_root(),
            "project_file": proj_file,
            "scenes": scenes_rel,
            "assets_copied": copied,
            "files": ["export_manifest.json", proj_file] + files,
            "game": game_info,
            "warnings": warnings,
        })

        summary = {
            "dir": out_dir,
            "project": proj_file,
            "scenes": len(scenes_rel),
            "assets": copied,
            "bytes": total_bytes,
            "game": game_info,
            "warnings": warnings,
        }
        print(f"[Export] Bundle exported → {out_dir}")
        print(f"[Export]   project: {proj_file} | scenes: {len(scenes_rel)} | "
              f"assets: {copied} | {total_bytes / 1024:.1f} KB")
        for w in warnings:
            print(f"[Export]   WARNING: {w}")
        return summary

    @staticmethod
    def _copy_tree_for_export(src: str, dst: str, warnings: list[str],
                              exclude_dirs: set | None = None) -> tuple[int, int]:
        """复制目录树用于游戏层（排除 __pycache__ 与指定目录名）。

        Returns:
            (文件数, 字节数) — 复制失败时报 warning 并返回 (0, 0)
        """
        import shutil as _shutil

        skip = {"__pycache__"} | (set(exclude_dirs) if exclude_dirs else set())

        def _ignore(_dir, names):
            return [n for n in names if n in skip]

        try:
            _shutil.copytree(src, dst, ignore=_ignore, dirs_exist_ok=True)
        except OSError as e:
            warnings.append(f"copy failed: {src} → {e}")
            return 0, 0
        files = 0
        total = 0
        for dp, _dn, fn in os.walk(dst):
            for f in fn:
                files += 1
                try:
                    total += os.path.getsize(os.path.join(dp, f))
                except OSError:
                    pass
        return files, total

    @staticmethod
    def _write_json(path: str, data: dict) -> None:
        """写 JSON 文件（自动建目录）。"""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)

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
        """将 .mat 文件路径及运行时 ID 注册到项目资源列表（按真实路径去重）。"""
        cls._register_resource("materials", file_path, "material_id", material_id)

    @classmethod
    def register_prefab(cls, file_path: str, prefab_id: int | None = None) -> None:
        """将 .prefab 文件路径及运行时 ID 注册到项目资源列表（按真实路径去重）。"""
        cls._register_resource("prefabs", file_path, "prefab_id", prefab_id)

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
        saved_entries: list[tuple[object, str]] = []   # (scene_obj, rel_path)
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
                        saved_entries.append((scene_obj, rel))
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
                    saved_entries.append((scene_obj, rel))
                print(f"[Project] Auto-saved scene '{sname}' → {rel}")
            except Exception as e:
                print(f"[Project] Failed to auto-save scene '{sname}': {e}")

        cls._data["scenes"] = scene_list

        # ★ 3. 维护 startup_scene 的有效性 (先按真实文件路径重映射, 再回退首个场景)
        startup = cls._data.get("startup_scene", "")
        if startup:
            startup_key = cls._path_key(cls._resolve_path(startup))
            for scene_obj, rel in saved_entries:
                sp = getattr(scene_obj, '_file_path', '') or ''
                if startup_key and cls._path_key(sp) == startup_key and rel != startup:
                    print(f"[Project] startup_scene remapped: '{startup}' → '{rel}'")
                    startup = rel
                    break
        if not startup and scene_list:
            startup = scene_list[0]
        elif startup and startup not in scene_list and scene_list:
            print(f"[Project] startup_scene '{startup}' no longer exists, using '{scene_list[0]}'")
            startup = scene_list[0]
        cls._data["startup_scene"] = startup

        # ── 收集用户 prefab ──
        cls._sync_prefabs_to_data()
        # ── 资源路径规范化: 旧绝对路径/旧相对写法 → 相对当前项目目录 ──
        cls._canonicalize_resources()

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

    # ════════════════════════════════════════════════════════════
    # Resource 路径规范化 (注册 / 换根 / 保存)
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _path_key(path: str) -> str:
        """路径比较键 — 统一大小写/分隔符, 用于跨写法去重。"""
        return os.path.normcase(os.path.normpath(path)) if path else ""

    @classmethod
    def _register_resource(
        cls,
        category: str,
        file_path: str,
        id_key: str,
        resource_id: int | None,
    ) -> None:
        """注册一条资源记录。

        - 相对路径先绝对化 → 再规范化为 builtin:// 或相对当前项目目录
        - 按"真实绝对路径"去重：旧条目（绝对路径 / 旧相对路径写法）就地更新而非重复追加
        """
        if not file_path:
            return
        abs_path = file_path if os.path.isabs(file_path) else os.path.abspath(file_path)
        rel = cls._to_relative(abs_path)
        if not rel:
            return

        entries: list = cls._data.setdefault("resources", {}).setdefault(category, [])
        key = cls._path_key(abs_path)
        for idx, entry in enumerate(entries):
            existing = entry if isinstance(entry, dict) else {"path": entry}
            old_path = existing.get("path", "")
            old_abs = cls._resolve_path(old_path) if old_path else ""
            if (old_abs and cls._path_key(old_abs) == key) or old_path == rel:
                merged: dict = {"path": rel}
                rid = resource_id if resource_id is not None else existing.get(id_key)
                if rid is not None:
                    merged[id_key] = rid
                entries[idx] = merged
                cls._mark_dirty()
                return

        new_entry: dict = {"path": rel}
        if resource_id is not None:
            new_entry[id_key] = resource_id
        entries.append(new_entry)
        cls._mark_dirty()

    @classmethod
    def _denormalize_paths_to_absolute(cls) -> None:
        """将存量路径固化为绝对路径 — 必须在切换项目根 (Save As) 之前调用。

        存储中的相对路径语义是"相对于当前 .myproj 所在目录"；项目根一旦切换，
        旧相对路径将指向错误位置，因此先解析为绝对路径再换根。
        """
        if not cls._project_path:
            return
        res = cls._data.get("resources", {})
        for category in ("materials", "shaders", "textures", "meshes", "prefabs"):
            entries = res.get(category, [])
            for i, entry in enumerate(entries):
                if isinstance(entry, dict):
                    p = entry.get("path", "")
                    if p and not p.startswith("builtin://") and not os.path.isabs(p):
                        entry["path"] = cls._resolve_path(p)
                elif isinstance(entry, str) and entry and not entry.startswith("builtin://") \
                        and not os.path.isabs(entry):
                    entries[i] = cls._resolve_path(entry)
        scenes = cls._data.get("scenes", [])
        for i, sp in enumerate(scenes):
            if sp and not os.path.isabs(sp):
                scenes[i] = cls._resolve_path(sp)
        startup = cls._data.get("startup_scene", "")
        if startup and not os.path.isabs(startup):
            cls._data["startup_scene"] = cls._resolve_path(startup)

    @classmethod
    def _canonicalize_resources(cls) -> None:
        """保存前重建 resources 路径 — 真实文件统一为 builtin:// 或相对当前项目目录。

        - 旧条目里的绝对路径 / 旧项目根的相对路径 → 按当前项目根重算
        - 同一真实文件的多条记录 (abs 与 rel 混写) 合并为一条, 保留 id
        - 找不到的文件保留原写法 (不静默丢弃), builtin:// 原样保留
        """
        if not cls._project_path:
            return
        res = cls._data.setdefault("resources", {})
        id_keys = {"materials": "material_id", "prefabs": "prefab_id"}
        for category in ("materials", "shaders", "textures", "meshes", "prefabs"):
            merged: list = []
            seen: dict[str, int] = {}
            for entry in res.get(category, []):
                rel_path, rid = cls._parse_resource_entry(entry)
                if not rel_path:
                    continue
                if rel_path.startswith("builtin://"):
                    new_rel, key = rel_path, rel_path.lower()
                else:
                    abs_path = cls._resolve_path(rel_path)
                    if abs_path and os.path.isfile(abs_path):
                        new_rel = cls._to_relative(abs_path)
                        key = cls._path_key(abs_path)
                    else:
                        new_rel = rel_path
                        key = cls._path_key(abs_path or rel_path)
                id_key = id_keys.get(category)
                if key in seen:
                    idx = seen[key]
                    if id_key and rid is not None:
                        merged[idx][id_key] = rid
                    continue
                seen[key] = len(merged)
                item: dict = {"path": new_rel}
                if id_key and rid is not None:
                    item[id_key] = rid
                merged.append(item)
            res[category] = merged

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
                # ★ 记住来源文件 — 后续 Project 保存/另存不会重复落盘到 scenes/ 自动目录
                scene._file_path = abs_path
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
