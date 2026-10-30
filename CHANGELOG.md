# Changelog

## Unreleased

### English

- **Distribution policies split** — game export is now user-specific and
  on-demand: only extension node packs referenced by the project scenes are
  copied, and `export:false` remains a hard opt-out. The installer uses a
  separate mainline allowlist (`Application/Functions/official_extensions.json`);
  local/third-party directories never ship, while official extensions are not
  dropped just because they opt out of game export. Both paths exclude the
  git-ignored `Application/Editor/Config/` local state.
- **Extension state location** — extension enablement and `ctx.data_dir`
  now default to `%APPDATA%/FlyVibingEngine/` (`editor_state/extensions.json`
  and `extensions_data/<id>/`) instead of the repository/install tree; existing
  `FVE_*` / legacy `MGE_*` environment overrides still work.
- **Provider signatures** — node cards show a muted provider line under the
  title (`@Official` for core and official packs, `@Community` by default for
  runtime packs, or an explicit `signature` from the pack). Examples show
  `Name @Provider`; community examples are discovered from
  `%APPDATA%/FlyVibingEngine/examples` and remain outside the mainline tree.
- **Extension graph API** — `ctx.graph` now supports owned-node discovery,
  `add_node` / `update_node` / `set_props` / `replace_props` / `remove_node`,
  link add/remove, and `request_redraw()`. Mutations bump a canvas revision
  and request an editor repaint; extension writes are limited to its own owner.
- **Extension docs** — UI, node-pack, and Example development guides moved to
  the `FlyVibing-User-And-Developer-Utils` repository as the single source.

### 简体中文

- **发行策略拆分** — 游戏导出改为用户态按需：只带当前工程场景引用的扩展
  节点包，`export:false` 仍是硬 opt-out；安装包走独立的 mainline
  allowlist（`Application/Functions/official_extensions.json`）——本地/第三方
  目录不进包，但官方扩展不会因为“对游戏导出关闭”而被错杀。两条路径都排除
  git-ignored 的 `Application/Editor/Config/` 本地状态。
- **扩展状态目录** — 扩展启用状态与 `ctx.data_dir` 默认迁到
  `%APPDATA%/FlyVibingEngine/`（`editor_state/extensions.json` 与
  `extensions_data/<id>/`），不再写仓库/安装目录；`FVE_*` 与旧 `MGE_*`
  环境变量覆盖仍有效。
- **提供者签名** — 节点卡标题下恢复灰色签名行：核心节点/官方扩展为
  `@Official`，运行期扩展默认 `@Community`，也可由 pack 显式写 `signature`。
  Example 菜单显示 `名称 @提供者`；社区示例从
  `%APPDATA%/FlyVibingEngine/examples` 读取，不进入主线 `Examples/`。
- **扩展图 API** — `ctx.graph` 支持检索自己的节点、`add_node` /
  `update_node` / `set_props` / `replace_props` / `remove_node`、连线增删与
  `request_redraw()`。变更会递增 canvas revision 并请求编辑器重绘；扩展写入
  默认限制在自身 owner。
- **扩展文档** — UI、节点与 Example 开发指南迁移到
  `FlyVibing-User-And-Developer-Utils` 仓库作为唯一源。

## 1.0.1 — 2026-10-24

### English

- **Installer fix** — all-users installs no longer fail with
  `Error creating registry key: HKEY_LOCAL_MACHINE\Environment` (code 87).
  The PATH entry is now written to the correct hive/subkey via
  `[Code]`; per-user installs still use `HKCU\Environment`.

### 简体中文

- **安装器修复** — 选择“所有用户”安装时不再报
  `Error creating registry key: HKEY_LOCAL_MACHINE\Environment`（code 87）。
  PATH 写入改由 `[Code]` 按安装模式选择正确的注册表根与子键；当前用户安装仍写
  `HKCU\Environment`。

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
