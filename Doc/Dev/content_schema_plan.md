# 内容 schema 基座（prefab / shader / material / GUI 同源） — 设计方案

> 状态：**提案**（未实现）。
> 目标读者：引擎侧 + 工具链侧（MCP / CLI / Inspector）维护者。
> 相关：`shader_protocol.md`（uniform 归属约定）、`runtime_ui_protocol.md`（运行期 UI）、
> `product_todo.md` §10（里程碑）。

---

## 1. 为什么要做（用现行代码说话）

现在"一个可调项"要同时写进 **四个互不相识的地方**，缺一处就出现"agent 看不到 / GUI 不能改 / 校验拦不住"：

| 知识 | 现在存在哪 | 代码位置（实测） |
|---|---|---|
| uniform 有哪些、什么类型 | GLSL 正则解析 → `{name: type}` | `Application/Resource/_resource_utils.py:22` `parse_shader_files` |
| uniform 的默认值 | **shader 里的 `= 0.0` 哨兵 + 文档表格**（`0` 表示"用默认"）；材质初始化按类型给白/0 | `Lighting.frag` 注释、`Material.__init__` |
| 哪些 uniform 归引擎（不可编辑） | **三份硬编码名单**：解析时排除 / 上传时跳过 / 建内置材质时特判 | `_RESERVED_UNIFORMS`、`OpenGLEntities._MATERIAL_SKIP_UNIFORMS`、`ResourceManager:775` 硬写 `uShininess = 32.0` |
| uniform 的 GUI 形态 | **按 shader 名字分支**：`if shader_name == 'Basic': 颜色盘`；其余走"通用列表"，`vec4` 画成 4 个滑条、`vec2`/数组直接显示"不支持"、`mat4` 只读灰字 | `ScenePanel._draw_material_section:896` |
| uniform 的可写范围 / 枚举 | **不存在**（写了就生效，越界靠人肉） | — |
| 组件字段的 GUI + 校验 | `FIELD_CLAMPS` / `FIELD_CHOICES`（部分覆盖） | `Core/Scene/ComponentRegistry.py` |
| MCP 可写参数 | `component.set` 里 **逐特性手写 key**：`color / material / material_name / shader / blend / uniform{...} / texture_add / texture_remove` | `Editor/Services/LiveCommandServer.py:~2109` |
| prefab 结构 | 扁平组件字典，无字段版本、无 schema 校验 | `Resource/Prefabs/Builtin/DefaultLight.prefab` |

**后果**（正好是用户提到的三类）：

1. **工具链线性膨胀**：每加一种"内容维度"（默认材质颜色、SSVEP 相位/频率、漫反射强度、高光模型……）
   就可能要加一个 MCP key + 一段 Inspector 分支 + 一行文档。op 数量已经从 60 涨到 76。
2. **agent 出现工具缺口且难以自检**：`component.set uniform={uShininess: 40}` 能写，但 agent 无法
   发现"这台机器的 Lighting 支持哪些 uniform、范围是多少、哪个是只读" → 只能猜，猜错静默生效。
3. **GUI 多态不可控**：`vec4` 是颜色还是四元向量？`int` 是枚举还是计数？现在只能靠 shader 名字硬编码。

另外顺带暴露一个**真实功能缺口**：`SSVEP.frag` 的 `time` / `freq` / `phase_shift`
**没有任何运行期写入者**（全仓搜索只有材质初始化和编辑器手改）。`time` 永远是 0 →
SSVEP 方块是**静态**的。这不是"再写一个 MCP op"能解决的，而是"谁拥有这个 uniform"没被建模。

---

## 2. 设计目标

一句话：**一份声明式 schema 同时驱动 Inspector、MCP、校验、默认值、prefab 校验与文档**。

```
             GLSL 里的 //! 注解               组件 Dataclass + FIELD_CLAMPS/CHOICES
                     │                                      │
                     ▼                                      ▼
              ShaderSchema                            ComponentSchema
                     └──────────────┬───────────────────────┘
                                    ▼
                            FieldSpec 注册表
        ┌───────────────┬───────────┼────────────┬──────────────┐
        ▼               ▼           ▼            ▼              ▼
  Inspector 通用渲染   MCP schema.get  写入校验   .mat/.prefab 默认值   Doc 生成
```

验收口径（可测试）：

- **新增一个 shader 参数 = 只改 1 个 GLSL 文件**（加注解），Inspector/MCP/文档/校验全部自动跟上。
- **新增一个组件字段 = 只改 1 个字段声明**（+ 可选 clamp/choices），同上。
- **任何一个可写项都能被 agent 发现**：`schema.get` 返回 `name/kind/range/choices/group/default/editable`。
- **任何越界/错类型写入被拒**（GUI、`component.set`、`.mat` 加载、`.prefab` 加载同一套规则）。

---

## 3. `FieldSpec`（唯一的数据结构）

```python
@dataclass(frozen=True)
class FieldSpec:
    name: str                 # 唯一名（uniform 名 / 组件字段名）
    kind: str                 # float|int|bool|string|color3|color4|vec2|vec3|vec4|enum|entity|asset|readonly
    label: str = ""           # i18n key（"mat.uShininess"）或缺省用 name
    group: str = ""           # 折叠分组（Surface / Specular / Stimulus / Runtime）
    default: object = None    # 真实默认值（唯一来源；不再用 shader 里的 0 哨兵）
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    choices: tuple = ()        # enum: ((value, label_key), ...)
    unit: str = ""            # "Hz" / "rad" / "deg"
    editable: bool = True     # False = 引擎/运行期驱动，GUI 只读、MCP 拒写
    owner: str = "content"    # content（可编辑）| engine（每帧注入）| runtime（逻辑驱动）
    doc: str = ""             # 一行说明（进 Doc 生成）
```

两个后端都产出 `list[FieldSpec]`，消费方**不认识**来源：

- `ComponentSchema`：从 `ComponentRegistry` 的契约类字段生成，`FIELD_CLAMPS`/`FIELD_CHOICES`
  作为覆盖（现有机制直接复用，不推翻）。
- `ShaderSchema`：GLSL 解析结果 + `//!` 注解；无注解时按类型降级推断（今天的行为）。

---

## 4. Shader 层：注解写在 GLSL 里

### 4.1 语法

```glsl
uniform vec4  uColor           = vec4(1.0);   //! ui: color4 | label=mat.base_color | group=Surface
uniform float uShininess       = 0.0;         //! ui: float  | label=mat.shininess | range=1..256  | step=1   | default=32  | group=Specular
uniform float uDiffuseStrength = 0.0;         //! ui: float  | label=mat.diffuse_kd | range=0..4    | default=1.0 | group=Surface
uniform float uSpecularStrength= 0.0;         //! ui: float  | label=mat.specular_ks| range=0..1    | default=0.25| group=Specular
uniform float uAmbientStrength = 0.0;         //! ui: float  | label=mat.ambient_ka | range=0..1    | default=1.0 | group=Surface
uniform int   uSpecularModel   = 0;           //! ui: enum   | label=mat.specular_model | choices=0:mat.phong,1:mat.blinn | default=0 | group=Specular
uniform float freq             = 0.0;         //! ui: float  | label=ssvep.freq  | unit=Hz  | range=0.5..60 | step=0.1 | group=Stimulus
uniform float phase_shift      = 0.0;         //! ui: float  | label=ssvep.phase | unit=rad | range=0..6.283             | group=Stimulus
uniform float time             = 0.0;         //! ui: readonly | owner=runtime | label=ssvep.time
uniform mat4  model;                          //  (无注解 → owner=engine，自动只读)
```

- 前缀 `//!` 是**机器所有**，普通 `//` 注释保持自由（现有人读注释如 `// 高光指数 → 默认 32` 不动）。
- **`default=` 是唯一默认值来源**。`= 0.0` 的 GLSL 初始化只是着色器语言要求，语义上被 `default=` 覆盖。
  这样现有"0 = 用默认"的哨兵约定可以逐步退役，`shader_protocol.md` 里的表格改为生成物。
- `owner=runtime`（`time`）表示"引擎每帧注入、材质不得持有" → 自动进 `_MATERIAL_SKIP_UNIFORMS`
  的等价集合，并在材质里**不预留 key**（今天是预留了 `time` 但没人写 → 恒 0）。
- `owner=engine` 缺省用于 `mat4` 与 `_RESERVED_UNIFORMS` 名单，**名单变成生成物**。

### 4.2 解析与降级

`parse_shader_files` 增加返回值 `uniforms[i] = {"type": t, "spec": FieldSpec|None}`：

- 有 `//!` → 严格按注解；
- 无 `//!` → `kind` 由类型推断（`vec4 → color4? 否，默认 vec4`），`editable=True`、无范围
  （**与今天行为等价**，老 shader 一行不改也能跑）。

### 4.3 消费方

| 消费方 | 变化 |
|---|---|
| Inspector | 一个通用渲染器：`kind` → widget（color4 → 拾色器；float → DragFloat + 范围 + "复位"按钮；enum → Combo；readonly → 灰字+来源说明）。**删除 `if shader_name == 'Basic'` 分支** |
| MCP | `schema.get {target: "shader:SSVEP"}` 返回 `FieldSpec` 列表 → agent 不用猜；`component.set uniform={...}` 按 spec 校验类型/范围/可写 |
| 默认值 | 材质创建时用 `default` 而不是"按类型给白/0"；`GetBuiltinMaterial` 里硬写的 `uShininess=32` 删除 |
| 文档 | `shader_protocol.md` 的 uniform 表改为由 schema 生成（`Utils/Dev` 里加一个 renderer，像 `test_map.py render` 那样） |

---

## 5. Material 层：默认值 ⊕ 稀疏覆盖

```python
class Material:
    shader_id: int
    overrides: dict[str, np.ndarray]      # 只存"用户改过的"
    blend: str

    def values(self, schema) -> dict[str, np.ndarray]:   # 有效值（上传用）
        return {s.name: self.overrides.get(s.name, s.to_array()) for s in schema if s.editable}
```

- `.mat` 文件加 `"format_version": 2`，写 `overrides`；
  读旧文件（v1 全量 `uniforms`）→ 视为"全部是覆盖"，行为不变，不丢数据。
- 好处①：改 shader 默认值，**所有未覆盖的材质自动跟随**（今天必须逐个改 + 手改文档）。
- 好处②："复位"= `del overrides[name]`，不需要知道旧默认是多少。
- 好处③：`.mat` 文件从"几十行全量"变成"几行差异"，diff 可读。
- 渲染器兼容：`OpenGLEntities` 侧仍拿到 `values()` 的 dict 上传，改动局限在 `Material` 内部。

---

## 6. Prefab 层：同源校验 + 版本 + 资产按路径引用

现状：

```json
{ "format_version": 1, "prefab_name": "DefaultLight",
  "root": {"name": "Sun", "components": {"Light": {"light_type": "area", "intensity": 0.75}}},
  "children": {} }
```

改进（保持向后兼容，只加不改）：

1. **组件级版本**：`"components": {"Light": {"__version": 2, "intensity": 0.75}}` ——
   字段增删时可写迁移函数，而不是"老 prefab 静默丢字段"。
2. **字段校验**：加载时逐字段过 `ComponentSchema`（类型/范围/枚举），未知字段 **warn 而不是崩**
   （现在是 `_COMP_MAP` 白名单 + 直接 `setattr`，拼错名就静默丢弃）。
3. **材质按路径引用**：`"material": "Materials/Red.mat"` 或 `"@builtin:Lighting"`，
   加载时走 `ResourceManager.MaterialRef/ResolveMaterialRef`；`material_id` 仅作运行期缓存。
   理由：`material_id` 是**会话内自增**，跨工程/跨会话的 prefab 里存 id 必然错位。
4. **prefab 可以只存"差异"**（可选，后置）：`"overrides": {...}` 之于默认组件值，
   与材质稀疏覆盖同一套心智。

---

## 7. 工具链：把"逐特性 op"换成"schema + 一次泛化写"

- 新增 **2 个只读 op**（不是每个特性一个）：
  - `schema.list {kind: component|shader|prefab}` → 名字清单；
  - `schema.get {target: "shader:Lighting" | "component:UISlider"}` → `FieldSpec` JSON。
- `component.set` 保留今天的 `fields` 字典形态（已被大量脚本使用），但：
  - 校验全部下沉到 schema（`color`/`uniform`/`blend` 等 key 逐步标为**语法糖别名**）；
  - 新增字段**零 op 改动**（`fields` 里带字段名即可）。
- **工具缺口自检**（这是用户最关心的"agent 经常出现 mcp-cli 工具缺口且难以检查"）：
  加一个守卫测试 `test_schema_coverage.py`：
  1. 每个 `FieldSpec(editable=True)` 能被 Inspector 通用渲染器渲染（kind 全部有 widget）；
  2. 每个 `FieldSpec` 能通过 `component.set` 写入并被 schema 校验；
  3. 每个 GLSL `uniform` 都有 spec（或 `owner=engine`）；
  4. 每个 `.prefab` / `.mat` 资产都能通过 schema 校验（示例工程全覆盖）；
  5. `schema.get` 的输出与 Inspector 用的 spec **同一对象**（防两套漂移）。

---

## 8. 迁移路线（每步独立可验收，不要求一次做完）

| 步 | 内容 | 验收 |
|---|---|---|
| S1 | `FieldSpec` + `ShaderSchema`（`//!` 解析 + 类型降级）+ `Lighting`/`SSVEP`/`Basic` 注解 | 单测：注解 → spec；无注解 → 老行为；`time` 识别为 `owner=runtime` |
| S2 | Inspector 通用 uniform 渲染器（删 `shader_name == 'Basic'` 分支）+ 默认值来自 spec | 编辑器截图：Lighting 五个参数带范围/分组；SSVEP 频率带 Hz 单位；`time` 灰显 |
| S3 | `Material` 稀疏覆盖 + `format_version: 2`（读 v1 兼容） | 单测：改 shader 默认 → 未覆盖材质跟随；旧 `.mat` 读入不丢值 |
| S4 | `schema.get` op + `component.set` 校验下沉 + `test_schema_coverage` | 全家桶：core 全绿；`docs/references/ops.md` 重新生成；prefab 校验全通过 |
| S5 | prefab 校验/版本/材质按路径 | 旧 prefab 加载无警告；故意写错字段 → warn 且保留其他字段 |

**S1+S2 就能解决用户点名的三件事**（颜色怎么选、漫反射值怎么选、SSVEP 相位/频率/time），
且不碰 op 契约；S3 之后才涉及文件格式。

---

## 9. 明确不做

- **不做"任意 GUI 脚本"**（内嵌 Python/表达式驱动 Inspector）：那会把"可校验"变成"不可校验"。
- **不做 shader 热重载**（属于渲染管线课题，和 schema 正交）。
- **不改节点图 schema**：节点已有 `PropertyDescriptor`（`Core/NodeGraph/component_registry.py`），
  后续只需让它读同一份 `FieldSpec`，本期不动。
- **不引入 `ui_theme.json`**（用户已明确暂缓）。

---

## 10. 与 SSVEP 功能缺口的衔接

`time` 定为 `owner=runtime` 后，需要补一个**唯一的**每帧注入点（建议放在
`OpenGLEntities` 的 per-program 帧注入段，与 `_inject_lighting` 并列，由
`Engine` 的累计时间驱动）。这属于 S1 的附带产物，工作量小、收益明确
（SSVEP 方块才会真的闪）。`freq`/`phase_shift` 则变成材质可编辑项，
可由节点图的 `SetMaterialParam`（待建）在试次开始时改 —— 这才是"实验范式参数化"的正路。
