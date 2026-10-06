# media_protocol.md — 动态媒体协议（M1 v2: 节点驱动 GIF/图像）

> 改 `Application/Functions/Media/**`（MediaSystem）、`MediaPlayer` 组件、
> `ShowMedia` 节点、`TextureUpdateCommand` 链前必读。
> **v2 决议（2026-10-06，用户）**：编辑器编辑只是模板；PIE 唯一由 GameRuntime 控制；
> 只有节点编辑器合理建图才生效。蓝图与依赖选型见 `roadmap_next.md` 章 M。

---

## 1. 架构决议（v2）

1. **单一运行时**：不存在"媒体运行循环"。`MediaSystem` 是被动库 — 唯一驱动者 =
   节点 `ShowMedia`（运行在图执行器内；PIE 时位于 GameRuntime 的 RuntimeNodeLayer 逻辑线程）。
2. **编辑器 = 模板**：实体 + `MediaPlayer` 组件参数（source/playing/loop/speed/fit）只是声明。
   编辑器不播放、不创建/绑定动态纹理（v1 的 EditorLayer tick 已移除）。
3. **PIE 语义**：编辑器实体是 **EntitySpawn 模板**（PIE 不直接渲染它们）；
   图内 `OnGameStart → EntitySpawn(template)` 生成运行时实例，`EntityGet(名)` 找到实例，
   `ShowMedia` 逐帧驱动 → PIE 窗口播放。
4. **纹理**：单一纹理栈 + 运行期派生（`media:*` 前缀；不入资源面板、不序列化；
   组件注册单一注册源 = `ComponentRegistry.ensure_defaults()`）。
5. **播放时钟/帧号**在 MediaSystem（不序列化）；组件只存参数。
6. **节点边界**：ShowMedia 只做"驱动播放"；未来状态读取/控制节点（Play/Pause/Seek）
   只操作组件字段，永不碰 shader/像素（`uTime` 属材质 uniform 系统，正交）。

## 2. 数据流（PIE）

```
OnGameStart ──▶ EntitySpawn(template="MemeSquare")         生成运行时实例(eid=N, 名字=模板名)
OnFrameUpdate ─▶ EntityGet("MemeSquare") ─▶ ShowMedia      每帧触发
                    │  Entity(entity_ref) 直连
                    ▼
MediaSystem.advance(engine=GameRuntime, eid, dt)
   ├─ 懒初始化(一次): Pillow 解码(GIF 多帧/静态图单帧, mtime 缓存)
   │    → ResourceManager.CreateTextureFromArray("media:<file>")
   │    → runtime_scene.SetEntityTexture(eid, tex, slot0)   (st.app=GameRuntime → 其渲染器)
   │    → 首帧上传
   ├─ 时钟: acc += dt × speed → 换帧(loop 绕回 / 停末帧) → enqueue TextureUpdateCommand
   │    → GameRuntime.renderer (CommandQueue 带锁) → glTexImage2D 同尺寸重传
   └─ 引擎帧去重: 同一实体同帧多驱动只推进一次 (stamp=engine.get_elapsed_time())
编辑器侧: 无 tick — 编辑只是模板（此句即 v1→v2 的差异本体）。
```

## 3. ShowMedia 节点（IO ▸ Media）

| 引脚 | 方向/类型 | 说明 |
|---|---|---|
| `exec_in` / `exec_out` | exec | 挂 `OnFrameUpdate` 链 → 逐帧播放（推荐）；`OnGameStart` → 只推首帧 |
| `Entity` | data in, `entity_ref` | 必须来自 `Get Entity.Entity`（未连 → 静态检查 error） |

静态校验码：`media_pin_unconnected`（error）/ `media_exec_unconnected`（warning）。
去重：同一实体同引擎帧多个 ShowMedia → 单次 advance。

**五注册点（完整清单）**：

| 注册点 | 文件 |
|---|---|
| 类型/引脚/颜色 | `node_types/media.py` + `node_types/__init__.py`（`MEDIA_COLOR`） |
| 求值器 | `evaluators/media.py` + `NodeGraph/__init__.py` 导入 |
| 控件/菜单/布局 | `widgets/media.py` + `widgets/__init__.py`；`styling.MENU_SECTIONS`；`panel._WIDGET_NODES` |
| 校验 | `validation/checks.py` §12 + `graph_constraints.SHOW_MEDIA` |
| 文档/构图 | `rules.md` + `graph_rules.py`（场景内嵌）+ `GraphBuilder.show_media` |
| 冒烟覆盖 | 场景 `node_editor_smoke` widgets_all_modules 代表节点 |

## 4. MediaSystem API（`Application/Functions/Media/MediaSystem.py`）

| API | 语义 |
|---|---|
| `load_media(path) -> MediaClip` | Pillow 解码；GIF 全帧 seek（帧时长下限 0.02s）/ 静态图单帧（duration=1.0）；`(abspath, mtime)` 缓存 |
| `advance(engine, eid, dt)` | 单实体推进：懒初始化 → 时钟换帧 → 上传；同引擎帧去重；错误遏制（坏源只停该播放器）；组件缺失打印一次 |
| `snapshot(engine=None)` / `reset(engine=None)` | 诊断快照 / 状态清理（测试隔离） |

- `engine` 语义：`engine.scene` = 该引擎的 SceneManager 视图（PIE=GameRuntime 的实例），
  `engine.renderer` = 其渲染器；无渲染器（无头测试）时仅推进 CPU 侧 —— 全部可无头测。
- 源路径解析：绝对/存在 → 原样；否则相对仓库根（cwd）。

## 5. 组件与注册

`MediaPlayer`（`BasicComponents.py`）：`source ""` / `playing True` / `loop True` / `speed 1.0` / `fit "stretch"`。

| 路径 | 内容 |
|---|---|
| `ensure_defaults()` | 唯一注册源（Init/sync 统一调用） |
| 节点属性质 | `NodeGraph/component_registry.py` `_COMPONENT_PROPERTIES["MediaPlayer"]` |
| **PIE 模板白名单** | `SimulationController._sync_ecs_to_scene` 显式携带 `MediaPlayer`（与 Transform/Camera/MeshRenderer 并列）—— 不加则 EntitySpawn 实例缺组件、ShowMedia 无法驱动 |

## 6. 渲染命令链（与 v1 相同）

`TextureUpdateCommand(texture_id, image_data, w, h, ch)` → `OpenGLRenderer.update_texture_data`
→ `OpenGLResourceManager.update_texture_data`（未注册→合成 Texture 走 `register_texture`；
已注册→bind 原句柄 + `glTexImage2D` 同尺寸 + mipmap）。CPU 侧入口
`ResourceManager.CreateTextureFromArray`（np (H,W,1|3|4) uint8）。

## 7. 测试与验收（v2 已通过）

| 层 | 证据 |
|---|---|
| core | **23/23**（含新增两项）：`test_media_system` 无头解码/时钟/引擎帧去重/遏制；`test_media_node` 注册/静态检查/干跑惰性/节点驱动 + **PIE 模板白名单**钉住 |
| live e2e | 模板视图抓帧 39.5KB（编辑器无播放）→ Run（sim.state Running, last_error ""）→ **PIE 三连抓帧 diff 28576 / 31942 px**（变化区域≈252×269 = 方块），两帧鹦鹉姿态不同 → Stop 后编辑器视图字节数与 pre-PIE 完全一致（39546 = 39546，无残留） |
| 引擎日志 | `[EntityGet] 'MemeSquare' → eid=6`（生成的实例被逐帧找到）；PIE `runtime_alive` 全程 true |
| 序列化 | `Test/TestProject/Test/scenes/meme_gif_2d.scene`：`game_type "2d"` + `MediaPlayer.source` + **node_graph 8 节点**（含 EntitySpawn/ShowMedia 与四条连线） |

## 8. 已知边界 / 后续

- `fit` contain/cover：材质 UV 实现；M1 仅 stretch。
- 动态纹理引用释放：场景频繁重载时旧 `media:*` 纹理仍留 `loaded_texture`（无引用计数）。
- 模板组件白名单（`_sync_ecs_to_scene`）当前逐组件枚举 —— 未来可通用化（全 @component 深拷贝）。
- 编辑器视图不显示媒体预览（模板语义，by design）；如需静态首帧预览另议。
- M2 音频（sounddevice vs SDL2）→ M3 视频（imageio-ffmpeg, 同一命令通道 + 触发对齐）→ M4 打包评测。

## 9. 文件地图（v2）

| 文件 | 角色 |
|---|---|
| `Application/Functions/Media/MediaSystem.py` (+`__init__.py`) | 解码缓存 / 播放时钟 / 纹理协调（被动库） |
| `Application/Core/NodeGraph/node_types/media.py` | ShowMedia 类型/引脚 |
| `Application/Core/NodeGraph/evaluators/media.py` | 求值器（干跑惰性; ctx.scene.app → advance） |
| `Application/Core/NodeGraph/validation/checks.py` | §12 媒体静态检查 |
| `Application/Core/Scene/BasicComponents.py` | MediaPlayer 组件（模板参数） |
| `Application/Editor/UI/panels/node_editor/widgets/media.py` | 目标回显 + 接线提示控件 |
| `Application/Editor/UI/controllers/SimulationController.py` | PIE 模板同步白名单（携带 MediaPlayer） |
| `Application/Core/Renderer/*` + `Application/Resource/ResourceManager.py` | 纹理更新命令链（同 v1） |
| `Test/Application/Media/test_media_system.py` / `test_media_node.py` | core 验收 |
| `Test/TestProject/Test/scenes/meme_gif_2d.scene` | 演示场景（模板实体 + 驱动图） |
