# Changelog

## 1.0.0 — 2026-10-24

### English

FlyVibingEngine 1.0.0 is the first Windows release with a complete authoring,
preview, and export path.

- **Node groups** — groups can be renamed and described in-place, dragged,
  resized, nested, and populated by dragging members in or out. Each group has
  a real `GroupStart`/`GroupEnd` pair rendered as `Group entry` / `Group exit`
  ports with draggable connection dots.
- **Graph focus** — `Fit` waits until group bounds are registered, so freshly
  imported or opened graphs remain readable instead of zooming to a tiny view.
- **Examples** — `Examples/MI` and `Examples/RestingState` are refreshed with
  nested groups, group descriptions, group boxes, and entry/exit nodes.
- **Windows installer** — bundles Python 3.14 free-threaded, the offline
  wheelhouse, the editor toolchain, and the bundled examples. No Python or
  package manager is required on the target machine.
- **Toolchain** — ships `engine-editor-mcp` and `flyvibing-node-editor` for
  live editor automation and offline graph validation.

Compatibility: Windows 10/11 x64; Python 3.14 free-threaded runtime;
`engine-editor-mcp` 0.5.x / `flyvibing-node-editor` 0.1.x.

### 简体中文

FlyVibingEngine 1.0.0 是首个包含完整编辑、预览与导出链路的 Windows 版本。

- **节点组** — 支持就地重命名/描述、整体拖动、右下角缩放、嵌套，以及成员
  拖入/拖出。每个组拥有真实的 `GroupStart`/`GroupEnd` 节点，并渲染为带
  可拖拽圆点的 `Group entry` / `Group exit` 端口。
- **图视图** — `Fit` 会等待组框尺寸注册完成，新导入/打开的图不会缩成不可读
  的极小视图。
- **示例工程** — `Examples/MI` 与 `Examples/RestingState` 已重整：嵌套组、
  组描述、组框与入口/出口节点均已写入场景。
- **Windows 安装包** — 内置 Python 3.14 free-threaded、离线 wheelhouse、
  编辑器工具链和示例工程；目标机无需安装 Python 或包管理器。
- **工具链** — 随包提供 `engine-editor-mcp` 与 `flyvibing-node-editor`，
  分别用于实机编辑自动化与离线图校验。

兼容性：Windows 10/11 x64；Python 3.14 free-threaded 运行时；
`engine-editor-mcp` 0.5.x / `flyvibing-node-editor` 0.1.x。
