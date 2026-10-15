# 项目 / 导出开发协议（Project & Export）

> 适用：`ProjectManager`（.myproj）、`EditorHost` 场景 I/O、主菜单 File 项（`UIManager`）、
> `FileDialog` 目录选择、资源路径规则与自包含导出。
> 节点/设备相关见 `node_editor_protocol.md` / `device_io_protocol.md`；UI 通用约定见 `ui_protocol.md`。

---

## 1. 职责与文件地图

| 文件 | 职责 |
|---|---|
| `Application/Editor/ProjectManager.py` | .myproj 读写；resources/scenes/startup 记录；Save / Save As；`export_project_bundle()` 自包含导出 |
| `Application/Editor/EditorHost.py` | 场景 CRUD；场景文件落点跟踪（`scene._file_path`）；node_graph ↔ Scene 同步 |
| `Application/Editor/UI/UIManager.py` | 主菜单（File: New / Open / Save / Save As / **Export** / Exit）；对话框回调 |
| `Application/Editor/UI/FileDialog.py` | 非阻塞 OS 对话框 + 目录记忆（`export` 类型独立记忆键） |
| `Application/Core/Scene/Scene.py` | `.scene` JSON（实体 + `node_graph`）；`save_to_file` / `load_from_file` |
| `Application/Editor/UI/panels/ScenePanel.py` | 手动 Save/Load Scene；材质保存/加载后注册进工程 |

---

## 2. 路径规则（核心）

工程文件里路径有三种写法，语义固定：

| 写法 | 语义 | 加载行为 |
|---|---|---|
| `builtin://Name` | 引擎内置资源（`Resource/` 下） | 由 ResourceManager 解析；**跨机器可用**（引擎同版本） |
| 相对路径 | **相对 .myproj 所在目录** | Save As 换根 / 移动工程时语义随之移动 |
| 绝对路径 | 兜底（未保存工程注册 / 跨盘无法相对化） | 换机器/移动即断链 |

硬性规则：

1. **换根前固化**：`save_project_as()` 必须先调 `_denormalize_paths_to_absolute()`
   （相对路径的语义是"相对当前 .myproj"，换根后会指向错误位置）。
2. **保存时归一化**：`_save()` 内 `_canonicalize_resources()` 把旧写法统一为
   `builtin://` 或相对当前工程目录，并按真实绝对路径**去重合并**（保留 id）。
3. **注册去重**：`register_material/register_prefab` → `_register_resource()`，先绝对化再去重；
   未保存工程的注册会暂存绝对路径，首次 Save As 后由 §2.2 自愈。
4. 业务代码**不得手拼**这些路径：统一走 `ProjectManager._to_relative` / `_resolve_path`。
5. 场景文件本身**自包含**（组件只存运行时 int id：`material_id` / `mesh_id` / shader ids）；
   打开工程时 `material_id` 经 `id_map` 重映射。**id 依赖加载顺序**，跨引擎版本可能错配。
   对齐不变量（**记录 id == 场景引用 id == 运行时活 id**）由 §3 步骤 6 在保存时强制维护。

---

## 3. Save Project / Save As 行为契约

`ProjectManager._save()` 的执行序列（Save 与 Save As 共用）：

1. 同步活跃场景（esper → Scene）与节点图（panel → Scene.node_graph）；
2. 逐场景写盘：有 `_file_path` → 写回原文件；无 → `<proj>/scenes/<name>.scene` 并记录落点；
   （工程目录**之外**的场景跳过 — 提交点会先将它们重指入列，见下）
3. 收集 `scenes` 列表（相对当前工程根）→ **startup_scene 按真实文件路径重映射**，失败回退首个场景；
4. `_sync_prefabs_to_data()` 从 ResourceManager 重建 prefab 列表；
5. **`_persist_referenced_materials()`**：场景引用但**无文件落点**的材质（编辑器内编辑
   产生的克隆）落盘 `<proj>/assets/materials/<名>.mat` 并登记（活 id）；
6. **`_sync_material_records_to_live()`**：材质记录的 `material_id` 刷新为**当前活 id**
   （镜像 prefab 同步语义）——对齐不变量：**记录 id == 场景引用 id == 运行时活 id**；
   从而下次加载 `id_map` 重映射**必然命中**（串扰根修，2026-10-15）；
7. **`_report_missing_assets("save")`**：扫描“记录在案但磁盘缺失”的资产并集中报告；
8. `_canonicalize_resources()` 归一化资源路径；
9. 写 `.myproj`。

**Save As 的定位（2026-10-15 升级：工程文件夹提交点）**：

`save_project_as()` 在换根（`_denormalize_paths_to_absolute()`）之后执行
`_consolidate_into_project_dir()` —— 把**当前编辑器已加载内容**凝固进新工程目录：

- **场景**：工程目录**之外**的场景（含无落点场景）→ 重指 `<new>/scenes/<basename>`
  （内容由 `_save` 从当前内存态写入；原文件不动 = fork 语义）；`startup_scene` 跟随重指；
- **资源**：目录外且已有文件的 materials / shaders / textures / meshes / prefabs →
  拷入 `<new>/assets/<类别>/`（同名自动 `_2/_3` 后缀）；材料从内存态重存（含未落盘编辑）；
- **记录**：`_point_record_at()` 同步改指新文件（id 保留，随后由步骤 6 刷新为活 id）；
- `builtin://` 与已在工程目录内的文件不动；重复另存为**幂等**。

保存之后的持续维护语义：

- **场景自包含（数据隔离，2026-10-15 起）**：保存时目录**之外**的场景不重写原文件
  （由提交点重指入列代替）；加载时拒绝 `scenes` 中指向工程目录外的条目
  （旧污染自愈，记 WARNING）。需要在多工程间携带场景 → 另存为提交点自动拷入，
  或手动把 .scene 复制进工程目录 / 用 Export。
- **编辑器内更改**：材质克隆/改色在每次保存时自动落盘 + 登记（步骤 5-6），无需手动 Save Material。
- **缺失识别**：`open_project` 与每次保存都扫描并集中报告缺失资产
  （`collect_missing_assets()` / `get_missing_assets()`；记录保持不删，供用户修复或重定位）。

**落点跟踪约定**：`EditorHost.save_active_scene_to_file / save_scene_to_file /
load_scene_from_file` 以及 `ProjectManager._load_all_scenes` 都必须维护 `scene._file_path`
（否则 Project 保存会重复落盘到 `scenes/` 自动目录）。

---

## 4. Export Project Bundle（自包含导出，已实现）

入口：**File ▸ Export...** → `FileDialog.open_export_dir`（非阻塞，父目录选择器）
→ `UIManager._do_export_project` → `ProjectManager.export_project_bundle(target_parent)`。

输出结构（选择 `<target_parent>` 后自动创建 `<target_parent>/<项目名>/`）：

```
<Target>/<Name>/
    <Name>.myproj          # scenes / resources / startup 全部相对路径, builtin:// 保留
    scenes/<场景>.scene     # 全部场景（活跃场景先做内存同步, 节点图随场景保存）
    assets/<类别>/<文件>    # materials / prefabs / ... 工程目录外的资源一并复制进包
    export_manifest.json   # 清单: 来源工程 / 时间 / 文件列表 / warnings
```

行为契约（改动时必须保持）：

- **纯快照**：不修改 live 工程的状态与磁盘文件；
- 未保存过的工程拒绝导出（先 Save Project As）；
- 目标目录已有内容时：**仅当含本工具 manifest（旧导出）才允许覆盖**，否则拒绝；
- **重复导出 = 干净重建**（2026-09-28）：目标为旧导出时先清空其内容再重建（防止旧场景名/旧轮子/旧引擎文件残留）；仅**保留 `output/`**（实验数据）；
- 目标路径与当前工程目录**完全相等**时拒绝（防止覆盖 live .myproj）；
- 缺失资源 → 记 warnings 并**从包中剔除**（引用它的场景保留旧 id，打开时同现状告警）；
- 同名文件批内去重（`_2` 后缀）；返回摘要 dict（dir/project/scenes/assets/bytes/warnings）。

---

## 5. 开发清单（新增/修改工程与导出行为时）

- [ ] 对话框一律走 `FileDialog`（非阻塞 + `render()` 轮询），新类型用独立记忆键；
- [ ] 路径解析只经 ProjectManager（`_to_relative` / `_resolve_path`）；
- [ ] 导出类功能：纯快照、幂等重写（manifest 保护）、逐条 warning；
- [ ] 改 `_save()` / `save_project_as()` 后，用无头 temp 目录回环验证：
      `register → save_as#1 → save_as#2 → export → 重新解析所有路径存在`；
      专项行为测试：`Test/Application/Editor/test_project_asset_commit.py`
      （提交点拷入 / 克隆持久化 / 缺失识别 / 重开绑定）；
- [ ] 概率回归（heavy）：`Test/Application/stress/test_material_cycle_stress.py`
      —— 预期 stable/edit/shift 0 失败 0 漂移；legacy 为已知脏数据不复原；
- [ ] 回归：`FlyVibing-User-And-Developer-Utils/packages/node-editor/test_smoke.py`、`Test/Application/Functions/test_gtec_device.py` 不回归。

---

## 6. Game Export（已实现 v1 — 打包细节见 `runtime_packaging_protocol.md`）

**状态（2026-09-28）**：v1 已落地 — 播放器入口 `Application/PlayerEntry.py`（`--dry-run` /
`--frames`）；Export 按钮 `export_project_bundle(include_player=True)` 附带游戏层：
`game.json` + 冻结引擎副本（Application/ + Resource/）+ `runtime/` 预装 Python 环境 +
`wheelhouse/` + `run_game.cmd`。
⚠️ 历史设计稿（下述第 4 条 PyInstaller 路线已否 —— 改为 python-build-standalone 预制环境）：

与工程导出的差异：**运行时子集 + 播放器入口 + 不依赖编辑器**。

建议结构（v1）：

```
<游戏导出>/
    game.json            # 清单: 引擎版本 / 启动场景 / 入口资源
    scenes/ assets/      # 仅含启动场景可达的资源（节点图随场景）
    run_game.bat         # 调用引擎 player 入口（本机引擎 venv）
```

落地要点（实现者参考）：

1. 播放器入口需要新的无编辑器启动路径（当前 `EntryPoint.py` 固定进编辑器；
   `GameRuntime.run()` 已是 export 阻塞模式，但无人给它装配场景/节点图）。
2. 运行链路：`Scene.load_from_file` → `NodeCanvas.from_dict(scene.node_graph)` →
   `RuntimeNodeLayer.set_canvas / set_scene` → `GameRuntime.run()`。
3. 工作目录必须等于引擎根（builtin 资源用相对路径 `Resource/...` 定位），
   或显式改为绝对挂载；player 不依赖 `ProjectManager`（编辑器组件）。
4. 真正"脱离本机"还需打包引擎运行时（复制 `.venv` 不可移植；建议 PyInstaller
   onedir 或嵌入 Python + 引擎目录）——作为第二阶段；第三阶段再做压缩包 + 版本校验。

---

## 7. 已知坑（实战教训）

1. **未保存工程的资源注册存绝对路径**；Save As 提交点会拷入并改指（§3），
   并由 `_canonicalize_resources()` 相对化；导出前务必已保存过工程。
2. **`_file_path` 断跟踪** 曾导致：手动 Save Scene → 项目保存时再复制一份到 `scenes/`；
   startup 指向被覆盖 → 已修复（保存/加载均记录落点）。
3. **startup_scene 只存路径**：场景文件被移出工程目录时无法自愈（相对引用断链）→
   提交点重指 / 缺失扫描会报告；迁移用 Export。
4. **VFS 项目根机制未启用**（`VFS.init` 从未被调用，场景/材质读写走直接路径 + fallback）：
   不要依赖 VFS 的相对语义，路径一律用 ProjectManager 解析。
5. **资源类别不完整**：打开工程时仅 materials / prefabs 有加载实现；shaders / textures / meshes
   写入资源表也不会被载入（缺口）。
6. **导入不持久化**：`ImportService.load_mesh / load_texture / load_shader` 不注册进工程
   （只有材质与 prefab 注册）→ 场景引用用户网格会在重启后丢失。新增导入类型时**必须**补
   `register_*` + 打开时加载 + id 重映射三件套。
7. 主菜单快捷键（Ctrl+S / Ctrl+Shift+S）目前**仅展示未绑定**；`ProjectManager._auto_save` 是
   死代码 — 启用前先补 dirty 标记覆盖面（部分编辑路径不触发 `_mark_dirty`）。
