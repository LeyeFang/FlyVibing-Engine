# rendering_protocol.md — 渲染器开发协议（验证体系 + 开发规范）

> 改 `Application/Core/Renderer/**`、`Resource/Shaders/**`、渲染命令/材质/纹理上传路径前必读。
> 本协议由「渲染验证体系」章建立（2026-10-06）；能力差距与优先级见 `roadmap_next.md` 章 G。
> 规则来源：全部经 **core 测试 + GL 像素测试 + 实机 e2e** 验证（本文件 §4/§5）。

---

## 1. 后端现状（一等公民声明）

| 后端 | 状态 | 说明 |
|---|---|---|
| **OpenGL** (`Renderer/OpenGL/`) | **一等公民 / 唯一生产路径** | 编辑器强制（`EntryPoint: renderer_type='OpenGL'`，GL 4.4 core）；PIE 默认；本协议所有规范针对它 |
| ZenGL (`Renderer/ZenGL/`) | 实验（mixin 架构保留） | 依赖 `zengl` 包；**无任何回归覆盖** —— 改公共层（Renderer 基类/命令/VertexLayout）时以 OpenGL 行为为准，ZenGL 不保证同步 |
| Vulkan (`Renderer/Vulkan/`) | 实验 | `*.spv` 旁路存在；无回归覆盖 |
| `Test/RHI/` | **遗留** | 旧 RHI 架构验证台（自带渲染器拷贝），不在 runner 范围 —— 参考价值有限，勿从此处拷贝代码 |

> 新增后端 = 实现 `Renderer` + `RenderResourceManger` 抽象，并提供 `_get_renderer_class` 分支；
> 在此之前，公共层改动**只需保证 OpenGL 路径**。

## 2. 架构

### 2.1 分层

```
Engine._render_loop (渲染线程)
  └─ Renderer.StartFrame()            ← 消费 CommandQueue → _do_start_frame()
       └─ OpenGLRenderer._do_start_frame 管线:
          1. resize 处理 (pending → viewport + pick FBO 重建)
          2. clear (OpenGLCore, 清屏色可 SetClearColorCommand)
          3. pick pass (OpenGLPickSystem: 独立 FBO + 专职 shader + glReadPixels)
          4. pre-overlay callbacks (FBO 重定向/模板预设; _scene_fbo_override)
          5. render_entities (OpenGLEntities: 排序→逐实体 uniform→draw)
          6. post-process (OpenGLPostProcess: Highlight 轮廓 = MRT FBO + 边缘检测)
          7. overlays (OpenGLOverlays: Grid/Gizmo 等, 逐 drawable 状态标志)
  └─ Engine._render_one_frame: StartFrame → 层 OnRender → EndFrame
       → _maybe_capture (glReadPixels 后缓冲) → SwapBuffer → FrameProfiler.tick
```

组合模式（非 MRO）：`OpenGLRenderer` = `Renderer` + `RenderResourceManger`，子模块
`_core/_resources/_pick/_entity/_overlay/_post` 通过回引用访问。**桥接方法必须齐全** ——
命令调用的每个 `renderer.*` 方法都要在 OpenGLRenderer 上有桥接（历史缺陷：`update_highlight_config`
缺失，已由本协议配套测试抓出并修复）。

### 2.2 线程纪律

- **GL 调用只允许在渲染线程**（该线程持有上下文；`render:` 已注册 ThreadRegistry）。
- 跨线程唯一通道 = `renderer.enqueue(cmd)`（`CommandQueue` 带锁；任意线程可入队）+
  `FrameCaptureSlot`（单槽信箱：请求/发布/取回）。
- 渲染器上的只读信息（如 `gl_info`）**在渲染线程采集一次**，其他线程只读消费。
- 资源注册表（`registered_*`）与 `_visible_entities` 是渲染线程私有状态。

### 2.3 资源模型

- CPU 侧真理源：`ResourceManager.loaded_{mesh,shader,texture,material,prefab}`（全局、跨上下文）。
- GPU 侧：**每渲染器实例各自一份**（编辑器与 PIE 是两个 GL 上下文 → 两套 gl_handle，各自注册）。
  引用计数 `ref_count`：register +1 / unregister −1 / 归零释放。**重复 register 会新建 VAO 并抬
  引用计数**（引擎既有语义：材质/纹理变更后靠重发 `EntityRegistrationCommand` 刷新）。
- Mesh：VBO 交错 `[pos3, uv2, normal3]`（32B/顶点）+ EBO；布局来自 `VertexLayout`（`STD_LAYOUT`，
  唯一真理源）。**shader 属性声明必须与所用 layout 一致**（`check_shader_consistency` 在
  `register_entity` 时告警；已知现状见 §6）。
- Texture：支持 1/3/4 通道（R8/RGB8/RGBA8）+ mipmap。**动态纹理**（媒体）：CPU 注册一次 →
  逐帧 `TextureUpdateCommand` 同尺寸重传（不得跨尺寸；协议 `media_protocol.md`）。
- Material：`uniforms_data`（含 `uColor`）逐实体上传；材质共享 → 修改前必须
  `SceneManager._ensure_unique_material`。**内置材质（builtin_name 非空）永远视为共享模板**
  —— 即使当前只有 1 个引用者也先克隆再改（live 演示逮到的污染 bug，修复 + `test_material_isolation` 锁定）。
  `Material.blend`（opaque/alpha）为材质混合开关，见 §6。

### 2.4 坐标与矩阵约定（实测锁定）

- 网格数据存 **GL 坐标**（`Square.obj` 头注: X-Z 平面, `Ed_X=GL_X, Ed_Y=-GL_Z, Ed_Z=GL_Y`）。
- Transform 组件存 **GL 坐标**；编辑器坐标系转换统一走 `Math/CoordinateSystem.py`（唯一来源，
  `SetEntityTransformEditor` 自动转换）。
- 矩阵 = **row-vector 数学 + GL_FALSE 上传**（`Math/Transform.calculate_entity_model`；
  shader 里 `projection*view*model*vec4` 与其等价）。
- 相机 = `SetViewProjectionCommand(view, proj, ...)`（view 由调用方算好；`RuntimeNodeLayer` PIE
  与 `EditorCamera` 各负其责）。
- 抓帧 = 裸 RGBA8 **bottom-up**（GL 原生行序）——翻转/编码只允许发生在消费端（MCP/CLI）。

### 2.5 Fragment 约定

`Basic.frag = texture(uTexture, TexCoord) * uColor`。uniform 名约定：`model/view/projection/uTexture/uColor`。
着色器侧的完整 uniform/属性/光照契约见 **`shader_protocol.md`**（新增 shader 必读）。

- 实体渲染分**两段**：不透明（按 shader_id→material_id 排序）→ 透明（`Material.blend=='alpha'`，
  按视图空间深度**由远到近**画家排序）；透明段 `glEnable(GL_BLEND)` +
  `BlendFunc(SRC_ALPHA, ONE_MINUS_SRC_ALPHA)` + `DepthMask FALSE`，帧尾恢复。
- 光照帧状态（`uAmbient/uCameraPos/uLightCount/uLightDir/uLightColor`）在 program 首次出现时
  注入一次/帧；未声明这些 uniform 的 shader 自动 no-op（Basic/SSVEP 不受影响）。
实体绘制**仅启用深度测试**；混合/剔除目前只在 overlay/pick 各自启用（实体透明=不支持，见 §6）。

## 3. 开发规范（Checklist）

### 3.1 新增 RenderCommand（4 步）

1. `RenderCommand.py`：dataclass + `execute(renderer)` 只调用渲染器已有语义的方法（不写 GL）。
2. `Renderer` 子类补桥接（OpenGL 必须；ZenGL 可选）。
3. `Test/Application/Renderer/test_render_commands.py`：加 dispatch 断言 + 更新命令计数（现 16）。
4. 若命令来自 Editor/Gizmo：调用方按「主线程 enqueue」。

### 3.2 新增/修改 Shader

完整检查单（6 步含测试/文档）见 `shader_protocol.md` §11；要点：

1. 属性 `layout(location=N)` 必须与 `STD_LAYOUT` 对应布局一致；改 shader 属性 = 同步
   `test_vertex_layout.py` 快照表。
2. uniform 归属必须明确（矩阵/材质/渲染器注入）；帧级注入项需同步保留黑名单两处。
3. `ResourceManager.DEFAULT_SHADER_NAME/FILE` 注册（新增内置 shader；**顺序即 id**）。
4. 至少一个像素级测试用例 + runner 全绿。

### 3.3 新增 Overlay 可绘制对象

Editor 侧只产纯数据 `overlay_drawable_struct`（含 layout/blend/cull/depth 标志）→
`renderer.enqueue(OverlayRegistrationCommand(...))`；渲染端实现见 `OpenGLOverlays`。
注销必须对称（`unregister_from`）；双注销安全（pop(key,None)）。

### 3.4 禁止事项（现状 + 纪律）

- 禁止在 `OpenGL/` 目录之外 import `OpenGL.GL`（探针/测试除外）。
- 禁止在渲染线程做文件 IO / 解码 / 阻塞等待（解码放主线程/预解码，见媒体协议）。
- 禁止绕过命令队列从其他线程触碰 `registered_*`。
- 禁止重复 register 同一实体当"刷新参数"以外用途（会产生 VAO 垃圾 + refcount 抬升）。

## 4. 验证体系（本章建立）

### 4.1 测试地图

| 测试 | 档位 | 内容 |
|---|---|---|
| `Test/Application/Renderer/test_render_commands.py` | core | 16 命令 dispatch 契约（方法名/参数钉死）+ CommandQueue（FIFO/排空/并发入队/生产-消费）+ 命令注册表计数 |
| `Test/Application/Renderer/test_vertex_layout.py` | core | STD_LAYOUT 不变式 + 后端适配器 + **shader 一致性警告快照**（改 shader/layout 必须同步该表） |
| `Test/Application/Renderer/test_gl_pixels.py` | core (GL) | 隐藏窗口真 GL：世界→像素金标准 / uColor / 深度 / 可见性命令 / Checkerboard / **动态纹理重传（媒体链回归）** / 清屏色 / Highlight 注册-注销 / Resize / **材质混合（alpha 叠加 + 透明排序 + 状态恢复）** |
| `Test/Application/Renderer/test_gl_lighting.py` | core (GL) | **光照数值锁定**：环境光单独 / 垂直 & 斜射 / 侧背向 / 强度 / 双灯叠加 / 保留 uniform 不进材质 |
| `Test/Application/Renderer/test_gl_render_targets.py` | core (GL) | **RT 生命周期**：创建/注册（rt_id=纹理 id）/ 场景目标重定向 / 翻转钉死 / 采样 / 销毁回退 / with_depth=False / 重建语义 |
| `Test/Application/Core/test_material_isolation.py` | core | **内置材质模板保护**：独占也克隆 / 克隆体除名 builtin / 模板不污染 / 后建实体洁净 |
| `Test/Application/Editor/test_live_command_server.py` §3e | core | `renderer.snapshot` 无头路径（available=false + reason） |
| `Test/Application/Editor/e2e_renderer_check.py` | live | 实机：snapshot 真值（GL 4.4/NVIDIA/计数/overlays/统计）+ 裸帧采样 + capture |

运行：

```powershell
.venv-py314t\Scripts\python.exe Utils/Dev/test_runner.py --only Renderer   # 渲染五项测试
.venv-py314t\Scripts\python.exe Utils/Dev/test_runner.py --tier core       # 全量（含渲染五项）
.venv-py314t\Scripts\python.exe Test/Application/Editor/e2e_renderer_check.py   # 需引擎运行中
```

### 4.2 GL 像素探针（`Test/Application/Renderer/_gl_probe.py`）

- 隐藏 GLFW 窗口 (4.4 core) + 真实 OpenGLRenderer + 内置资源；一个测试文件进程内一个探针。
- 相机：`set_topdown(half_h=10)`（复刻 DefaultCamera2D：GL 位姿 (0,10,0)+Rx=90°，
  `view=inv(model)` 与 `RuntimeNodeLayer` 同路径）。
- **世界→像素金标准**（320×240，half_h=10 ⇒ 12px/单位）：
  `x_px = 160 + 12·GLx`，`y_px = 120 + 12·GLz`（GL −Z = 屏幕上方 = 编辑器 +Y 北向）。
  改相机/矩阵约定前，先看 `test_gl_pixels.py` 的锁定用例。
- 实体注册走**引擎命令路径**（`EntityManager.add` 自动入队 register 命令 → `render()` 时执行）——
  不要手动重复注册。
- 像素断言容差默认 ±6（无 MSAA，纯色精确；纹理受 mipmap/线性过滤影响时放宽或改相对断言）。

### 4.3 已验证的验收数据（回归基线）

- core **29/29**（渲染六项：render_commands 26 + vertex_layout 28 + gl_pixels 25 + gl_lighting 11 +
  gl_render_targets 18 + material_isolation 11 checks）。
- e2e **15/15**：GL `4.4.0 NVIDIA 595.97`、viewport 1600×900、overlay drawables 17 个。
- live 演示（2026-10-06）：默认场景 = lit Cube + Sun；默认材质保持白/opaque（隔离修复后）；
  混合红绿方块 × LitTilt/UnlitTilt 实机可辨（证据 `Test/_runs/p1_demo/`）。
- 探针映射、深度、动态纹理重传、混合、光照数值、RT 生命周期均逐断言锁定。

## 5. Agent 工具链

| 工具 | 用法 | 说明 |
|---|---|---|
| `renderer.snapshot`（op） | `engine-editor-cli call renderer.snapshot` | 后端/GL 信息/vieport/资源计数/overlay 键列表/帧统计（p1 low）；无头 `available=false` |
| `frame.request`+`frame.fetch`（op，内部） | MCP `engine_capture` 封装 | 抓帧（PNG 直回或落盘） |
| `capture`（CLI） | `engine-editor-cli capture [editor\|pie] --out x.png` | 只落盘省 token |
| `probe`（CLI） | `engine-editor-cli probe editor --points 160:120;800:450` | **裸帧像素采样**（无 PNG 编解码）→ JSON `[{x,y,rgba}]`；顶左坐标系 |

典型 agent 流程：`renderer.snapshot`（确认后端/规模）→ `probe`（像素级断言: 颜色/变化）
→ `capture`（需要人眼复核时）→ 改场景后重复 probe 对比。

## 6. 已知问题 / 发现（验证体系产出）

| # | 发现 | 状态 |
|---|---|---|
| 1 | `UpdateHighlightConfigCommand → renderer.update_highlight_config` **方法缺失**（OutlinerID.configure 一调即炸） | **已修复**（OpenGLRenderer 补桥接）+ 测试观察 |
| 2 | VertexLayout 一致性: location 2 (normal) 存在于 VBO, Basic/SSVEP 未声明 → 启动时 UserWarning「数据被浪费」 | **Lighting 落地后已部分解决**（Lighting 全用三属性）；Basic/SSVEP 仍浪费 → 快照锁定（`test_vertex_layout`） |
| 3 | 实体绘制无混合/排序（透明不支持）；逐实体 uniform 上传（无 UBO/合批） | **混合+排序已交付**（P1: Material.blend + painter；测试锁定）；UBO/合批仍缺（P2） |
| 4 | 无 MSAA（窗口无 GLFW_SAMPLES 提示）；无 sRGB/色彩管理 | 记录为能力差距（P2/P3） |
| 5 | `registered_overlays`（基类字段）未被 OpenGL 后端使用——真身为 `_resources._overlay_gpu_resources` | `renderer.snapshot` 已按真身读取；协议化记录 |
| 6 | `Test/RHI/` 为遗留验证台（自带渲染器拷贝）；`Renderer/Vulkan|ZenGL` 无回归覆盖 | 记录：公共层改动只保 OpenGL |
| 7 | **内置材质被污染**：`_ensure_unique_material` 旧逻辑在「内置 Default 恰好只剩 1 个引用者」时就地修改共享模板（live 演示逮到：默认 Cube 改用 DefaultLit 后，新实体编辑污染 Default + 克隆继承脏 blend） | **已修复**（内置永远先克隆 + 克隆体除名 builtin_name）+ `test_material_isolation` 锁定 |
| 8 | **切 shader 重置材质参数**：`set_new_shader` 按新表重建 `uniforms_data`（颜色等全丢）——判定为**约定**（防御性重建），编辑器路径须「先切后设」 | 记入 `shader_protocol.md` §6 + gl_lighting 用例注 |
| 9 | GL 对象名复用：删除后 `glGenFramebuffers` 可能返回同名句柄 | RT 重建测试改为「记录被替换」断言；GL 语义记录 |

## 7. 渲染目标（离屏 RT）

### 7.1 模型

- `OpenGLRenderTargets`（组合到 OpenGLRenderer，`renderer._targets`）：`create(rt_id, w, h, with_depth=True)`
  → 记录 `{fbo, tex, depth_rb, width, height, with_depth}`；`destroy(rt_id)` 级联清理 GL 对象 + 注册表。
- **`rt_id` 即纹理 ID**：颜色纹理以 `rt_id` 注册进 `registered_textures`（gl_handle 直挂）+
  `ResourceManager.loaded_texture["rt:<id>"]`（名称形如 `rt:7201`）→ 材质 `texture_id_list`
  直接引用即可采样；`SetEntityTexture(eid, rt_id)` 也走同一路径。
- 场景目标：`SetSceneTargetCommand(rt_id)`（0=屏幕）→ `renderer._scene_target_id`。
  激活时**全帧输出**（clear/实体/后处理/overlay）重定向进 RT；**拾取 pass 跳过**（面向屏幕坐标系）；
  帧尾恢复 FBO 0 + 窗口 viewport（try/finally 保证异常安全）。
- 命令：`CreateRenderTargetCommand / DestroyRenderTargetCommand / SetSceneTargetCommand`（§3.1 流程注册）。

### 7.2 语义锁定（`test_gl_render_targets.py`）

| 项 | 结论 |
|---|---|
| 创建 | FBO 完整校验（失败清理半成品并抛错）；rt_id 已存在 → 先销毁 = 重建语义 |
| 朝向 | RT 与屏幕同向（GL 底左原点）；**不做 Y 翻转** —— 用全屏 quad 展示时消费端按需翻转 |
| 尺寸 | 独立于窗口；`glViewport(0,0,rt_w,rt_h)` 随目标切换 |
| 销毁 | 活跃场景目标被销毁 → 自动回退屏幕；纹理注册表条目按 gl_handle 比对清理（防误删） |
| 无深度 | `with_depth=False` 依然 FBO 完整（纯颜色输出用） |

### 7.3 限制与后续

- 高亮后处理（MRT 专用 FBO + 合成）在 RT 激活下的行为未单独约定 —— 默认场景不用高亮，出现需求再设计（P2）。
- 多 RT / 尺寸变化 / 别名（swap chain 式复用）未做 —— 节点侧需要时再加命令与测试。

## 8. 光照体系（运行链路）

- **组件**：`DirectionalLight`（color_r/g/b + intensity；方向 = Transform 局部 -Z；注册链：
  `BasicComponents.register_contract` + `ComponentRegistry.ensure_defaults` + `NodeGraph/component_registry` +
  `SimulationController._sync_ecs_to_scene` 白名单 + `PrefabManager._COMP_MAP`）。
- **场景**：`SceneManager.ambient_color`（默认 0.18）+ `Scene.ambient_color` 序列化 +
  `SceneSync` 双向同步（编辑器 ↔ PIE 模板）。
- **帧收集**：`OpenGLEntities._collect_light_frame(view)` — 每帧一次：ambient + 至多 4 盏
  （`-model[2,:3]` 归一化）+ 相机世界坐标；**每 program 每帧注入一次**（program 首现时）。
- **默认场景**：`DefaultLight.prefab` → `SceneManager._create_default_light`（EditorHost 首次 Init），
  实体名 `Sun`；默认 Cube 改用 `DefaultLit` 材质（Lighting shader），**用户新建实体仍用 unlit `Default`**
  （SSVEP 刺激色精确性依赖）。
- shader 侧完整规范（uniform 契约/哨兵/数值表）见 `shader_protocol.md` §5/§7。

## 9. 能力矩阵（概要）

对齐基准 = learnopengl.com「现代仍常用」子集（非商业引擎对标）。**详表与优先级见
`roadmap_next.md` 章 G**。摘要：已具备 = 上下文/着色器/纹理/变换/两种相机/深度/拾取 FBO/
高亮后处理/overlay/抓帧 + **实体混合(透明)+排序** + **离屏 RT(FBO) 通用化** + **基本光照
（环境光+至多4方向光, Blinn-Phong, normal 启用）**；主要缺口 = MSAA、UBO/合批、阴影、
立方体贴图/天空盒、实例化、模型导入扩展、sRGB 管理。
