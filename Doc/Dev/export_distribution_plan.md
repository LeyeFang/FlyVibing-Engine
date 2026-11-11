# 议题 — 导出成品的扩展节点可见性与分发策略（2026-11-11 立项，同日落地）

> **性质**: 设计/计划文档（`*_plan`）。实现完成后按 `Doc/Dev/README.md` 约定迁到工具仓
> `docs_content/dev/export_distribution_protocol.md`。
> **触发**: mi-sssep 发现 + 本地采集夹具扩展提报 —— 数据采集节点在 PIE 里正常，在**导出成品里静默不生效**。
> **本文所有"现状"均来自 2026-11-11 代码实测**（含行号）。
>
> **命名约定**: 本文用 **`<fixture>` / 「夹具」** 指代那个本地采集设备扩展
> （`Application/Functions/<目录>/`，不入 git、不在安装包 allowlist 内）。
> 品牌名受 `test_extension_boundary` 品牌探针约束，不出现在 `Doc/**`；
> 真实 id 见该扩展自己的 `extension.json`。

---

## 0. 结论先行

| 问题 | 结论 |
|---|---|
| 是"白名单太僵硬"吗 | **部分是，但不是主因**。真正的杀手是**节点包发现机制**（§3-G4），与版权无关 |
| 症状有多严重 | **静默 no-op**：成品能启动、能渲染、能出画面，只是采集节点永不执行 —— 比崩溃更危险 |
| 版权规避是多余的吗 | **不是**。它保护的是"不要把品牌 SDK 塞进 git / 安装包"。这条要保留 |
| 该改什么 | 把决策来源从「**运行时注册表状态**」换成「**场景 + 清单声明**」；并把"再分发"与"本机部署"拆成两件事 |
| 和 SPD 线程问题有关系吗 | **同一根因**：主线在从错误的来源推导扩展能力（§4） |
| 优先级 | P0（数据采集类扩展的成品完全不能用），见 `product_todo.md §11.8` |

---

## 1. 症状与实测机制

### 1.1 症状

| 环境 | 表现 |
|---|---|
| 编辑器 PIE | 采集节点正常（`ext.<fixture>.GetData` 等有输出）|
| 导出成品（窗口模式） | **能启动、能渲染**，但采集永不开始，数据落盘为空 |
| 导出成品（`--dry-run`）| 12 条 `static error`：`unknown type 'ext.<fixture>.InitDevice'` 等 + 8 条 `pin not found` |

### 1.2 为什么窗口模式不报错

`NodeCanvas.from_dict()`（`canvas.py`）对**未注册类型**的处理是：

```python
unknown.setdefault(str(ntype), []).append(nid)   # 保留节点
print("[NodeCanvas] WARNING: unknown node type(s), kept as-is: ...")
print("  These nodes are NOT evaluated — PIE will refuse to start ...")
```

- **节点保留、连线保留、但永不求值**；
- 主线的硬拦截只发生在 **PIE 预检**（`SimulationController.preflight_problems`）与
  **`PlayerEntry --dry-run`**（`PlayerBootstrap.dry_run`，`PlayerBootstrap.py:250-267`）；
- **窗口模式的 `run()` 完全不跑静态校验** —— 于是「缺扩展」退化成「静默少算」。

> 这是最坏的失败模式：用户看到画面正常、时间轴在走、日志安静，收回来的数据却是空的。

---

## 2. 四道闸门盘点（只有两道真的影响导出）

| # | 闸门 | 位置 | 原始目的 | 影响导出？ |
|---|---|---|---|---|
| **G1** | 品牌探针 | `Test/Application/Extensions/test_extension_boundary.py` | 主线仓库不出现品牌字串（git 卫生）| ❌ **不影响**（夹具目录已整体豁免）|
| **G2** | 安装包 allowlist | `Application/Functions/official_extensions.json`（sigproc / bci / device / virtual）| 控制**安装包**里带哪些扩展（再分发）| ❌ **不直接影响**（只被 `_official_extension_ids` 用来产生 `non_mainline` **警告**）|
| **G3** | `export:false` 一票否决 | `ProjectManager._resolve_export_extensions`（`Export` 判定段）| 「别把我的东西再分发出去」| ✅ **整目录剔除** |
| **G4** | **节点包发现** | `NodePackRegistry.discover_builtin()` → `root.glob("**/node_pack.py")` | 约定式自动发现 | ✅ **连目录都找不到** |

### 2.1 关键实测数据

```
目录               node_pack.py?
BCIAlgorithm       True
夹具               False     ← 运行时注册
missssep           True
SerialParallelDevice True
SignalProcess      False     ← 运行时注册（或本无节点）
VirtualDevice      True
```

`Functions/<fixture>/extension.py`：

| 行 | 内容 |
|---|---|
| `:434` | `self._register_node_pack(ctx)` —— **在 `enable` 里** |
| `:611` | `def _register_node_pack(self, ctx)` |
| `:619` | `api.register_pack(acq_nodes.build_pack())` |

`Functions/<fixture>/extension.json`：`"export": false`，`provider: "@LeyeFang"`

---

## 3. 真正的根因：**从运行时注册表推导，而不是从清单声明推导**

导出流程（`ProjectManager._resolve_export_extensions`）的第一步是：

```python
required, unresolved = NodePackRegistry.extension_dirs_for_types(scene_types)
```

而 `extension_dirs_for_types` 只看得见**已注册的 pack**：

```python
for pack in cls._packs.values():
    directory = str(pack.get("dir") or "").strip()
    if directory:
        owner_dirs[str(pack.get("owner") or "")] = os.path.abspath(directory)
```

于是 `ext.<fixture>.*` 的命运取决于**这个编辑器会话里 夹具有没有被 enable**：

| 夹具扩展状态 | 导出时发生什么 | 成品结果 |
|---|---|---|
| **已启用** | pack 带着 `dir` 注册 → 解析到目录 → **然后 `export:false` 一票否决** | 目录不打包 → 节点 unknown → 静默 no-op |
| **未启用** | pack 没注册 → 进入 `unresolved` → 目录不打包 | 同上，且警告文案是"没有注册的扩展目录" |

**两条路都失败，失败原因还不一样。** 这就是"不可复现"的来源：同一个工程，
扩展开着导出和关着导出，警告文案不同但结果一样坏。

> 所以：`export:false` 只是**最后一脚**。即使把 `export:false` 改成 `true`，
> 未启用扩展的导出**依然**拿不到目录。这是必须一起修的根本原因。

### 3.1 顺带发现：`missssep` 为什么能跑

`missssep` 有 `node_pack.py` **且** `export:true` → 自动发现 + 自带 `dir` → 打包成功
（只产生一条 `non_mainline` 警告）。这印证了"约定式发现"才是分水岭。

---

## 4. 与 SPD 线程问题的同一根因

| 问题 | 决策来源 | 应该是 |
|---|---|---|
| SPD `spd-io` 无条件启动（`product_todo.md §11.7`）| `GameRuntime` **硬编码** `spd_start("runtime")` | 场景是否用设备节点 + 扩展声明 |
| 夹具节点导出不进去（本文）| **运行时注册表**里恰好有没有这个 pack | `extension.json` 的 `nodes` 声明 |
| 节点包发现 | **文件名约定** `node_pack.py` | 同上 |

三处都是「**主线从错误的来源推导扩展能力**」。这是同一条设计原则的三种表现：

> **扩展能力必须由「声明式数据（清单 + 场景）」决定，而不能由「运行时状态 / 文件名约定 / 硬编码」决定。**

这也解释了为什么 SPD 的节点要"决定线程生命周期"这件事一直谈不拢 ——
一旦节点可见性本身依赖运行时状态，线程是否启动更不可能有稳定依据。

---

## 5. 修复设计（四件，必须成套）

### 5.1 A — 清单声明节点包来源（修 G4）

`extension.json` 新增 `nodes` 块（**可选**，缺省仍走 `node_pack.py` 约定）：

```json
"nodes": {
  "module": "acq_nodes",
  "factory": "build_pack",
  "dir": ".",
  "types": ["ext.<fixture>.*"]
}
```

- 导出器**只读清单**即可解析 `type → 目录`，**不要求扩展已启用、不要求文件名是 `node_pack.py`**；
- 解析顺序以**清单优先**为准（见 §5.3）: 只有未声明的类型才回落到运行时 registry；
  声明与 `node_pack.py` 冲突时以清单为准 —— 导出必须是**确定性**的，
  而 `node_pack.py` 的可见性依赖"本次会话是否导入过"；
- `types` 支持前缀通配，用于**离线推导**（此时模块不导入）。

### 5.2 B — 把「再分发」与「本机部署」拆开（修 G3）

当前 `export: false` 一个布尔值同时表达两件事，语义被压扁了。建议：

| 字段 | 值 | 含义 |
|---|---|---|
| `export` | `true`（默认）/ `false` | `false` = **禁止再分发**（保留强否决，语义收窄） |
| `deploy` | `"any"`（默认）/ `"local"` | `"local"` = **可打进本机产物**，但产物标记 `redistributable: false` |

`<fixture>` 改成：

```json
"export": false,
"deploy": "local"
```

- 本机导出 → 目录被复制、节点可用、`export_manifest.json` 写
  `"redistributable": false` + 一条 `WARN ... local-only, do not redistribute`；
- 走**分发**路径（安装包 / `package_release`）→ 仍按 `export:false` **剔除**。

> 这一条直接解决"本来不会污染的部分反倒用不了"：**污染只发生在分发，不发生在部署。**

### 5.3 C — 导出决策改为离线可复现（修确定性）

`extension_dirs_for_types` 增加**离线解析**前置步骤：

```
1. 扫 Application/Functions/*/extension.json → {types 前缀 → dir}  (不导入模块)
2. 先按清单解析；剩余类型再查运行时 registry（兜底）
3. 仍未解析 → unresolved
```

验收：**headless 导出结果 == 编辑器导出结果**（同一工程，扩展开/关各导一次，产物应字节级一致）。

### 5.4 D — 缺扩展时必须「显式降级」，不能「静默 no-op」

现状：PIE 预检硬拦（好），`--dry-run` 报 error（好），**窗口模式什么都不做（坏）**。

建议分级：

| 场景 | 现在 | 改成 |
|---|---|---|
| PIE 预检 | error，拒绝启动 | 不变 |
| `--dry-run` | error | 不变 |
| **窗口模式启动** | **静默跳过** | 启动时打 `WARNING: N node(s) from missing extension(s): <types>`（一行），并在成品内加**可见标记**（标题栏 `[degraded]` 或在 `PerfStats`/日志首帧写入），至少让用户知道"这次数据不可信" |
| 图内渲染 | 节点照常显示 | 可选：节点卡片画红框 / 标 `[missing]`（编辑器侧已有 `unknown_node_types`，成品侧无 UI，先不做）|

不建议在窗口模式**阻断**：成品可能只是展示用，硬崩比降级更糟。但**必须显式**。

---

## 6. 与 G1/G2 的关系（明确不动）

| 闸门 | 处理 |
|---|---|
| G1 品牌探针 | **不动**。它保护的是主线仓库卫生，与功能可用性无关；夹具目录已豁免 |
| G2 安装包 allowlist | **不动**。它决定"安装包里带什么"，与"导出的产物带什么"是两件事。`official_extensions.json` 的 `description` 已经写明这一点，但现在的代码**只把它用于警告**，语义是对的 |
| `.gitignore` 白名单 | 不动 |

---

## 7. 兼容性与迁移

| 项 | 影响 |
|---|---|
| 现有 4 个有 `node_pack.py` 的扩展 | **零改动**（`nodes` 块可选，优先级低于约定）|
| `<fixture>` / `SignalProcess` | 加 `nodes` 块 + `<fixture>` 加 `deploy:"local"` |
| 已分发的旧产物 | 不受影响（manifest 缺 `deploy` 视为 `"any"`）|
| `.scene` 格式 | 不变 |
| `missssep` | 可选加 `nodes` 块（更稳，不依赖文件名）|

---

## 8. 验收

| 项 | 门槛 |
|---|---|
| 夹具扩展本机导出 | `MI-SSSEP-AllConditions` 导出后成品**能采集**（`ext.<fixture>.GetData` 有输出；`output/` 有数据落盘）|
| 分发路径不受影响 | `package_release` / installer **仍不含** 夹具目录（`test_export_extension_scope` / `test_release_layout` 保持绿）|
| 离线可复现 | 同一工程，夹具扩展开/关各导一次 → `required_dirs` 相同 |
| 缺扩展显式降级 | 故意删掉某扩展目录后启动窗口模式 → 日志出现 `WARNING: N node(s) from missing extension(s)` |
| 不误伤 | 7 个 MI-SSSEP 示例 PIE 行为不变；`test_export_extension_scope`（13）/ `test_export_game_bundle`（39）全绿 |
| 品牌探针 | `test_extension_boundary` 仍绿（夹具目录豁免不变）|

---

## 9. 不做

| 项 | 理由 |
|---|---|
| 取消 `export:false` 的一票否决 | 那是**再分发**的法律边界，必须保留 |
| 让 `official_extensions.json` 决定导出 | 那会把"分发许可"和"部署需求"再次混在一起 |
| 在窗口模式**阻断**缺扩展 | 展示型产物应当能跑；要求是"显式"，不是"更严" |
| 把第三方扩展塞进主线 `Examples/` | 与扩展边界无关，保持现状 |
| 自动下载/安装缺失扩展 | 需要网络与信任模型，另一个议题 |

---

## 10. 复现命令

```powershell
# 现状：成品缺扩展节点（静默 no-op）
.venv-py314t\Scripts\python.exe Application\PlayerEntry.py `
    Application\Functions\missssep\Examples\MISSSEP-AllConditions\MISSSEP-AllConditions.myproj `
    --seconds 5

# 干跑才看得见问题
... --dry-run --frames 0     # → 12 static error(s)

# 导出并检查 required_dirs
engine-editor-cli call project.open path=<proj>
engine-editor-cli call project.export target_parent=<tmp> include_player=false
# 看 export_manifest.json 的 extensions.required_dirs / unresolved_types
```

---

## 11. 落地状态（2026-11-11）

### 11.1 代码改动

| 件 | 文件 | 内容 |
|---|---|---|
| A | `Application/Core/NodeGraph/node_packs.py` | 新增 `_manifest_roots` / `manifest_node_index` / `_pattern_matches` / `_manifest_lookup`；`extension_dirs_for_types` 改为**清单优先**（离线、只读 JSON、不导入模块），registry 兜底 |
| B | `Application/Editor/ProjectManager.py` | `_resolve_export_extensions` 读 `export` + `deploy`；细节新增 `local_only` / `redistributable` / `deploy`，随 `export_manifest.json` 的 `extensions` 落盘 |
| B′ | `Application/Editor/ProjectManager.py` | `_export_excluded_paths`: 传了 `required_dirs` 时**不再二次否决** `export:false` —— 否则 B 会被这一层静默吃掉（**实现期实测缺陷**，见 §11.2） |
| D | `Application/Runtime/PlayerBootstrap.py` | 新增 `_report_missing_node_types` + 模块级 `_MISSING_NODE_TYPES`（可供宿主/日志查询）；窗口模式启动时打横幅与类型清单 |

### 11.2 实现期发现的新缺陷（已修）

第一版只改了 `_resolve_export_extensions`，`export_dirs` 已经收下夹具目录，
但**紧随其后的** `_export_excluded_paths(engine_root, required_ext_dirs)`
仍按"`export:false` 无条件排除"再剔一次 —— 现象是清单写着
`local_only: ["<fixture>"]` 而目录并不在产物里（**自相矛盾的产物**）。

> 教训: **许可决策只能有一个裁判**。上层已经判过"可以进包"，
> 下层就只该做目录筛选，不能拿同一个字段再判一次。

守卫: `test_export_manifest_nodes.py` 的「excluded-path filter keeps deploy:local extension」。

### 11.3 验收结果

| 项 | 结果 |
|---|---|
| 离线解析（夹具从未 enable）| ✅ `ext.<fixture>.*` → 目录，`unresolved` 为空 |
| 真实工程解析 | ✅ `MI-SSSEP-NoFeedback-20Hz-Block`（31 类型，3 个夹具类型）→ `required_dirs` 含夹具 + 串口；`local_only=["<fixture>"]`；`redistributable=false` |
| 复制过滤 | ✅ 同一 `required_dirs` 走 `_copy_tree_for_export` → 夹具目录与其 `nodes.py` 均在 |
| 分发路径不受影响 | ✅ `required_dirs=None`（整树）仍无条件排除；`test_release_layout` / `test_export_extension_scope` 绿 |
| 显式降级 | ✅ 缺类型画布 → `_report_missing_node_types` 返回 `{type: [nid...]}` 并打横幅；健康图清空状态 |
| 回归 | ✅ `--tier core` **108/108**（新增 `editor.export_manifest_nodes` 30 项断言）|

### 11.4 未做 / 待办

| 项 | 说明 |
|---|---|
| 完整成品实机采集验证 | 需要编辑器 GUI 打开工程才能走完整 `export_project_bundle`（headless `open_project` 依赖 `SyncFromScene`）；本轮用"决策 + 复制过滤"同路径验证，**仍需一次编辑器导出 + 运行**确认 |
| 用户目录扩展（`%APPDATA%/**/extensions`）| 仍被 `_resolve_export_extensions` 以"outside `Application/Functions`"拒绝 —— 与实际需求冲突，单独立项 |
| 成品内可见降级标记 | 仅日志横幅；标题栏 `[degraded]` 未做（§5.4 已列为可选）|
| 夹具 `LOCAL_COMPAT.md` | 其中"已验证 `_export_excluded_paths` 包含本目录"的旧结论已过时，需夹具方同步 |

