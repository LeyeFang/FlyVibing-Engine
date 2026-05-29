# GUI 架构文档

> 记录 `Application/Core/UI/` 模块的层级设计、职责边界与扩展指南。
> **每次新增/修改面板或控制器时，请同步更新此文档。**

---

## 一、整体架构分层

```
┌───────────────────────────────────────────────────────────┐
│                        UIManager                          │
│  面板注册 · DockSpace 布局 · 每帧 draw_all 调度 · 菜单栏   │
├───────────────────────────────────────────────────────────┤
│                         Panels                            │
│  ScenePanel | NodeEditorPanel | ToolbarPanel | ...        │
│      只负责绘制（imgui 调用），不持有业务逻辑状态            │
├───────────────────────────────────────────────────────────┤
│                       Controllers                         │
│  SimulationController | SceneBrowserController | ...      │
│   纯 Python 数据/状态层，不 import imgui                   │
├───────────────────────────────────────────────────────────┤
│              SceneManager / ResourceManager               │
│                  引擎核心服务（不受 UI 影响）                │
└───────────────────────────────────────────────────────────┘
```

**依赖方向（单向）**：`Panels → Controllers → SceneManager / ResourceManager`  
**禁止反向依赖**：Controller 和 Manager **绝不能 import imgui**。

---

## 二、文件清单与职责

### `UIManager.py` — 面板注册中心 + DockSpace 布局

| 方法 | 职责 |
|------|------|
| `register()` | 注册面板实例，触发 `on_attach()` |
| `find()` | 按名称查找已注册面板 |
| `draw_all()` | 每帧入口：应用主题 → 全屏背景窗口 → 菜单栏 → DockSpace → 绘制各面板 |
| `_draw_menu_bar()` | 内联菜单栏（File / Edit / View / Help），必须放在 `begin()` 与 `dock_space()` 之间 |
| `_setup_default_dock_layout()` | 设置默认停靠分栏布局 |
| `toggle_panel()` | 切换面板可见性 |

> **为什么菜单栏在 UIManager 而非独立面板？**  
> imgui 的 `DockSpace` 要求 `BeginMainMenuBar()` 在 `Begin("MainDockSpace")` 与 `DockSpace()` 之间调用，无法独立成面板窗口。

---

### `BasePanel.py` — 面板基类

| 方法 | 说明 |
|------|------|
| `on_attach()` | 面板注册时回调（申请资源，如 NodeEditor 上下文） |
| `on_detach()` | 面板移除时回调（释放资源） |
| `draw()` | **抽象方法** — 每帧绘制面板内容，子类必须实现 |
| `begin_panel()` / `end_panel()` | imgui 窗口生命周期 |
| `on_event()` | 可选：接收引擎事件 |

---

### `PanelStyle.py` — 深色主题

独立文件，仅由 `UIManager.draw_all()` 调用一次。定义所有颜色、圆角、间距。

---

### 面板列表 (`panels/`)

| 类 | 窗口名称 | 依赖的 Controller | 职责 |
|----|---------|-------------------|------|
| `ScenePanel` | `"Scene"` | `SimulationController`、`SceneBrowserController`、`ResourceBrowserController` | 场景层级 + 运行控制 + 资源浏览 |
| `NodeEditorPanel` | `"Node Editor"` | — | 节点画布 + 右键菜单 |
| `ToolbarPanel` | `"##Toolbar"` | `SimulationController` | 精简播放控制条 |
| `MenuBarPanel` | — | — | 保留文件但未注册，视未来需求启用 |

---

### 控制器列表 (`controllers/`)

| 控制器 | 职责 | 关键接口 |
|--------|------|---------|
| `SimulationController` | 模拟状态机 | `play()` / `pause()` / `resume()` / `stop()` / `get_state()` / `is_running()` |
| `SceneBrowserController` | 实体列表 & 选择 & 检视 | `get_renderable_entities()` / `select()` / `get_selected()` / `get_summary()` |
| `ResourceBrowserController` | 已加载资源分类查询 | `get_meshes()` / `get_shaders()` / `get_textures()` / `get_materials()` |

---

## 三、核心约定

```
✅ Controller 可以引用: SceneManager, ResourceManager, Event, threading.Lock
✅ Panel 可以引用: imgui, BasePanel, Controller
❌ Controller 不可以引用: imgui, Panel
❌ Manager 不可以引用: imgui, Panel, Controller
```

- Controller 使用 **`@classmethod` 单例风格**（与 UIManager 保持一致），避免实例化耦合
- 面板只保留「纯 UI 状态」（如 `_active_tab`），业务状态全部委托给 Controller
- 面板间共享状态（如播放控制）通过同一个 Controller 访问，杜绝各自维护

---

## 四、扩展指南

### 新增面板

1. **建类** — 在 `panels/` 下新建 `*Panel.py`，继承 `BasePanel`
2. **注册** — 在 `App` 初始化中调用 `UIManager.register(MyPanel())`
3. **暴露** — 在 `panels/__init__.py` 中添加 `__all__` 导出
4. **菜单** — 如需 View 菜单切换可见性，在 `UIManager._draw_menu_bar()` 的 View 菜单中添加名称
5. **Dock** — 如需默认停靠位置，在 `UIManager._setup_default_dock_layout()` 中添加 `dock_builder_dock_window()`

### 新增控制器

1. **建类** — 在 `controllers/` 下新建 `*Controller.py`
2. **风格** — 使用 `@classmethod` 单例风格
3. **约束** — 不得 `import imgui`、`imgui_bundle` 任何内容
4. **导出** — 在 `controllers/__init__.py` 中添加导入

---

## 五、未来扩展备忘

- [ ] **PropertiesPanel**：选中实体的 Transform / Mesh / Material 参数编辑
- [ ] **ConsolePanel**：引擎日志输出面板
- [ ] **AnimationPanel**：时间轴动画编辑
- [ ] **AudioPanel**：音频资源管理与波形预览
- [ ] **EEGPanel**：EEG 设备连接与信号预览
- [ ] **LayoutManager**：保存/恢复用户自定义 Dock 布局
- [ ] **SimulationController ↔ Event 集成**：通过 `SceneEvent` 通知渲染线程状态变更

---

*最后更新: 2026-05-29*
