# Utils/Dev/Installer — 安装器（离线优先）

FlyVibingEngine 的 **Windows GUI 安装包**（Inno Setup 6），内置 Python 运行时，
用户机器零 Python 依赖、免联网。

## 决策记录（2026-10-02 与用户锁定）

| 决策 | 内容 |
|---|---|
| 工具 | **Inno Setup 6**（免费；脚本见 `installer.iss`） |
| 分发形态 | **v1 仅离线版**：依赖 wheelhouse 直接捆绑（包更大但安装期免联网）；在线版以后再说 |
| Python | **内置**：直接复用运行时流水线的 `Resource/runtime/`（python-build-standalone 3.14t），安装版用户不需要任何 Python。启动器固定优选 `python3.14t.exe`（runtime 内含 GIL 版 `python.exe`，无法加载 cp314t 轮子 — 参照 run_game.cmd 同款回退逻辑） |
| 安装模式 | 默认 **per-user**（免管理员）；Wizard 提供 "我 / 所有用户" 选择（选 all-users 时才需要管理员） |
| 更新 | **覆盖重装**（AppId 固定 → 同路径升级；`CloseApplications` 处理占用） |
| PATH | 可选任务：把安装目录加入 PATH → 三方工作区 `mcp.json` 可直接写 `engine-editor-mcp` |
| 文件关联 | 可选任务：`.myproj` → `startup.bat "%1"`（双击开引擎；"自动打开工程"后续在 EntryPoint 支持参数后接通） |
| MCP 客户侧 | 不代装（Node/npm 之类由用户自理 — 那是 agent 侧的事） |

## 构建

```powershell
# 一次性（先重建 wheelhouse，再准备内置运行时）
.venv-py314t\Scripts\python.exe Utils/Dev/collect_wheels.py        # 从 PyPI 补全 Resource/wheels
.venv-py314t\Scripts\python.exe Utils/Dev/prepare_runtime.py       # 若 Resource/runtime 缺失

# 出安装包
.venv-py314t\Scripts\python.exe Utils/Dev/Installer/build_installer.py
#   → Utils/Dev/Installer/dist/FlyVibingEngine-Setup-<version>.exe

# 组装发布目录（exe + checksum + changelog + license + quick start）
.venv-py314t\Scripts\python.exe Utils/Dev/Installer/package_release.py
#   → Utils/Dev/Installer/dist/FlyVibingEngine-<version>-Windows-x64/
#   --zip 可额外生成同名 zip（仅用于离线分发）
```

选项：`--skip-runtime`（仅布局调试，包不可运行）、`--no-compile`（只做 staging）、`--keep-stage`（增量）。

## 发布物取舍

- **主下载 = 安装器 exe**。GitHub Release 直接挂 exe，不要让用户先解压。
- 同时挂 `CHECKSUMS.sha256`、`CHANGELOG.md`、`README-INSTALL.txt`（小文件，可直接查看/校验）。
- **不要默认打 zip**：zip 会隐藏 exe、多一步解压，且 Windows 可能给解压后的 exe 加 Mark-of-the-Web。
- 只有“离线实验室拷贝/无网络分发”才用 `--zip` 作为可选附加资产；portable 运行时另做独立 zip，不要和安装器混在一起。
- 构建中间产物统一留在 `Utils/Dev/Installer/dist/`；仓库根目录不再放 `dist/`。

工具缺失时：`winget install -e --id JRSoftware.InnoSetup`。

## Staging 内容（build/stage）

```
Application/            引擎源码
Examples/               内置 MI / RestingState 示例工程
Resource/               内置资源 + runtime(内置 Python) + wheels(离线 wheelhouse)
Doc/  Utils/User/       文档与用户层工具（Dev 工具链不进包）
startup.bat             启动器（优先用内置 runtime; dev 环境自动回退 venv）
engine-editor-mcp.cmd   MCP 启动器（PATH 任务注册后三方工作区直接调用）
README-INSTALL.txt      快照说明
```

最终发布目录只保留当前版本：

```
Utils/Dev/Installer/dist/FlyVibingEngine-<version>-Windows-x64/
    FlyVibingEngine-Setup-<version>.exe
    CHECKSUMS.sha256
    CHANGELOG.md
    LICENSE
    README-INSTALL.txt
    release-manifest.json
```

旧安装包归档在 `dist/archive/<version>/`，不参与发布。

依赖补齐：staging 时用 `pip --no-index -r Resource/wheels/requirements.export.txt`
把**开发版全量依赖**装进 `stage/Resource/runtime/Lib/site-packages`（安装版 = 开发版环境），
并把独立包 `engine_editor_mcp` 拷入同目录。

## 已知事项 / 后续

- 安装器 UI 暂为英文（ChineseSimplified.isl 后补）；任务文案可改中文（.iss 需 UTF-8 BOM）。
- 压缩用 `lzma2/fast`（构建快）；发布可改 `lzma2/max` 换更小体积（构建更慢）。
- 应用图标 / 安装器图标待定（`Resource/Icons/` 有素材可用后挂 `SetupIconFile`）。
- `.myproj` 关联的"自动打开工程"需要 EntryPoint 接受路径参数（小改动，待排期）。
- 在线版（安装期下载依赖）/ 应用内更新：未来扩展。
