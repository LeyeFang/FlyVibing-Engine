# text_protocol.md — 文字显示系统协议

> 改 `Application/Functions/Text/**`、`TextDisplay` 组件、`SetText` 节点、
> 文字光栅化/动态纹理绑定路径前必读。
> 本协议由「文字系统」章建立（2026-10-07）；复用媒体链（动态纹理）+ P1 混合交付。
> 一句话：**文字 = 自动生成的动态纹理 + 普通方块实体**——用户从不接触独立纹理。

---

## 1. 域地图

| 层 | 位置 | 职责 |
|---|---|---|
| 组件（状态载体） | `Application/Core/Scene/BasicComponents.py: TextDisplay` | 文本 + 全部样式字段 |
| 系统（光栅化） | `Application/Functions/Text/TextSystem.py` | Pillow 光栅化 → 动态纹理 → 材质槽绑定 + auto_scale |
| 节点（控制面） | `node_types/text.py` + `evaluators/text.py` + `widgets/text.py`（SetText） | PIE 中改字并立即刷新 |
| 编辑器预热览 | `EditorLayer.OnUpdate` → `TextSystem.tick(EditorHost)` | 编辑即预览（脏扫描，仅本引擎实体） |
| 检查器 | `ScenePanel` 通用组件区（"其它组件"）+ `SceneBrowserController.get/set_component_field` | 全字段直接编辑（含 ColorEdit4） |
| MCP | `component.add/set/get type=TextDisplay`（通用直写路径） | agent 热注入 |

**教义**（与媒体 v2 同构）：组件 = 状态载体；节点 = 控制面；编辑器 = 可预览的模板。
**有意偏差**：媒体"编辑器不播放"（有时钟），文字**编辑器编辑即预览**（无时钟维度，无第二运行时问题）。

---

## 2. 两种形态（核心使用场景）

| 形态 | 配置 | 效果 | 依赖 |
|---|---|---|---|
| **有色画布** | `bg_color` alpha = 1（如 `(0.9,0.55,0.1,1)`） | 文字画在实心背景上（标签/题板/提示条） | 无（opaque 路径） |
| **浮空文字** | `bg_color` alpha = 0（**默认**） | 画布透明，仅字形可见，文字"漂浮"在场景上 | **`Material.blend="alpha"`**（P1 混合交付） |

> `Material.blend` 由渲染器统一处理（`SRC_ALPHA/1-SRC_ALPHA` + painter 排序）；
> TextSystem **不写** blend 字段 — 用户/节点可在需要时切换（默认材质的 blend 为 opaque，
> 浮空文字素材建议显式设 `blend="alpha"`；编辑器/MCP：`component.set fields.blend="alpha"`）。

**验收矩阵**（场景覆盖 — 每格均有测试或实机证据）：

| | 编辑器预览 | PIE 节点驱动 |
|---|---|---|
| 有色画布 | ✅ 截图（蓝底 "SSVEP" / 橙底中文） | ✅ 探针 (840,594)=(200,123,26) 橙底 + 字形暗像素；截图 "PIE文字" 可读 |
| 浮空文字 | ✅ 特写截图 + 探针（字形灰度/alpha 渐变，字间透明） | ✅ 探针 (824,414)=(81,81,81,69) 字形 / (854,414)=(0,0,0,0) 字间 |

证据目录：`Test/_runs/text_demo/`（`editor_preview.png` / `float_closeup.png` / `pie_text.png`）。

---

## 3. TextDisplay 组件字段

| 字段 | 默认 | 说明 |
|---|---|---|
| `text` | `"Text"` | 内容；`\n` 换行；`wrap_width>0` 时自动折行 |
| `font` | `"segoeui"` | `Resource/Fonts` 名称（`<name>.ttf/.ttc`）或**任意字体文件路径**；中文需 CJK 字体（如 `C:/Windows/Fonts/msyh.ttc`，或放入 Resource/Fonts） |
| `size` | 64 | 字号（像素基准） |
| `bold` | False | **合成加粗**：描边扩展（stroke ≈ 4% size）— 无需字体带粗体变体 |
| `italic` | False | **合成斜体**：斜切变换（shear 0.22，顶部右移）— 无需斜体变体文件 |
| `color` | (1,1,1,1) | 文字 RGBA（0..1） |
| `bg_color` | (0,0,0,0) | 画布底色 RGBA — **alpha=0 = 浮空文字**（见 §2） |
| `align` | "center" | left / center / right |
| `line_spacing` | 1.15 | 行高倍数 |
| `padding` | 8 | 画布内边距（像素） |
| `wrap_width` | 0 | >0 = 按像素宽自动折行 |
| `world_height` | 1.0 | auto_scale 时画布的世界高度（引擎单位） |
| `auto_scale` | True | 自动把载体（Square 网格, 2 单位）缩放为画布纵横比：`scale_z = world_height/2`，`scale_x = scale_z × W/H` |

---

## 4. 数据流与更新策略（auto 画布）

```
字段签名变化 (text/font/size/bold/italic/color/bg/align/spacing/padding/wrap/wh/auto)
   └─ rasterize (Pillow): 测宽 → 自动画布 → 画字形 → 斜切(可选)
        ├─ 尺寸相同 → 原纹理就地热更: TextureUpdateCommand (GPU) + CPU 副本替换
        └─ 尺寸变化 → 新纹理 id (name "text:<eid>") + SetEntityTexture (无感换纹理)
   └─ auto_scale → SetEntityTransform (GL 缩放)
```

- 签名未变 → 零开销（编辑器 tick 逐帧脏检查；PIE 由 SetText 显式 refresh）。
- 纹理为运行期派生物：**不序列化**、不进资源面板；随场景删除实体后不回收（与媒体一致，量级可忽略）。
- 同尺寸约束来自动态纹理链（media_protocol 同款）：`TextureUpdateCommand` 不得跨尺寸。

---

## 5. 驱动通道

| 通道 | 路径 | 备注 |
|---|---|---|
| 编辑器预览 | `TextSystem.tick(EditorHost)`（每帧脏扫描, **仅本引擎注册表实体** — 不干扰 PIE 实例） | 编辑/拖参即刷新 |
| 检查器 | ScenePanel "其它组件" 通用区（str/bool/int/float/tuple 自动控件; `*color*` 用 ColorEdit4） | 无专属 UI 也能全字段编辑 |
| MCP | `component.set id/name=X type=TextDisplay fields={"text":"你好","size":72,"bold":true}` | 通用 dataclass 直写路径 |
| 节点 | `SetText`（exec + Entity ref + Text 字符串）；样式用 `SetComponent` 节点 | PIE；干跑仅记日志 `set_text` |

`SetText` 语义：写组件 → `TextSystem.refresh`（同帧纹理刷新；帧级原子拍覆盖批内一致性）；
目标实体需持有 `TextDisplay`（否则记日志 `skip`，不报错）。

---

## 6. 注册点清单（新增/排查时对照）

1. `BasicComponents.py`: `TextDisplay` 定义 + `register_contract`
2. `ComponentRegistry.ensure_defaults()`（PIE/场景反序列化可用）
3. `SimulationController._sync_ecs_to_scene` 白名单（**EntitySpawn 模板携带**）
4. `PrefabManager._COMP_MAP`（prefab 实例化）
5. `NodeGraph/component_registry.py` `_COMPONENT_PROPERTIES["TextDisplay"]`（SetComponent 节点）
6. 节点五注册点：`node_types/text.py`（+ `__init__` 导入+颜色）/ `evaluators/text.py`（+ `NodeGraph.__init__` 列表）/ `widgets/text.py`（+ `widgets/__init__`）/ `styling.py` 菜单 / `panel._WIDGET_NODES`
7. 文档三处：本文件 / `rules.md` / `graph_rules.py`

---

## 7. 测试与验收

| 层 | 位置 | 内容 |
|---|---|---|
| core 无头 | `Test/Application/Text/test_text_system.py`（24/24） | 注册链 / 浮空角落透明 / 有色角落=底色 / auto 画布增长 / 同尺寸热更 (id 不变 + TextureUpdateCommand) / 合成粗体像素增长 / 合成斜体画布加宽 / auto_scale 纵横比 / SetText 注册+dry-run+驱动 / reset |
| PIE e2e | `Test/_runs/text_demo/` | 双形态同屏（模板+节点加词"PIE文字"）；探针数值见 §2 矩阵 |

全量回归基线：core **31/31**（run_20261007_164659）。

---

## 8. 已知限制 / 后续

| 限制 | 说明 | 解除条件 |
|---|---|---|
| 逐字动画 / 打字机效果 | 每次改字 = 全画布重光栅化 | 需求出现时做字符级缓存 |
| SDF / 高清矢量字 | 位图光栅 1:1 | 大字号场景按需 |
| 纹理回收 | 换尺寸产生的旧 `text:*` 纹理不销毁 | 与媒体同步统一治理 |
| 发行字体许可 | segoeui 随仓已有；对外分发建议附 OFL 字体（Noto/DejaVu） | 打包章 |
| 检查器无中文字体下拉 | font 为文本输入（支持路径） | UI 增强时加下拉 |

---

## 9. 交叉引用

- `media_protocol.md` — 动态纹理链同源（CreateTextureFromArray / TextureUpdateCommand / 模板语义）
- `rendering_protocol.md` — 混合 (§2.5) / 原子拍 (§2.2) / 验证体系
- `shader_protocol.md` — 材质/纹理绑定契约
- `node_editor_protocol.md` — 节点五注册点流程
