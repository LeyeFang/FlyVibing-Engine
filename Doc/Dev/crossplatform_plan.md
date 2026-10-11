# 跨平台适配与安装工程计划（Windows + macOS）

> 状态：**立项（2026-10-11）**。目标平台：Windows 与 macOS（神经心理学实验 / BCI 工程的
> 主流平台）。含"另一台机器安装测试"执行规划。
> 已完成先行实测（2026-10-11）：依赖 wheel 矩阵 + OpenGL 依赖面 —— 见 §1。

---

## 1. 先行实测结论（数据支撑规划）

### 1.1 macOS arm64（Python 3.14）wheel 矩阵（pip download 实测）

| 包 | cp314t（free-threaded） | cp314（GIL） | 结论 |
|---|---|---|---|
| numpy / scipy / zengl / esper / mcp / pillow / rpds | ✅ 全有 | ✅ | 无障碍 |
| **imgui_bundle** | ❌ 无 | ✅ 1.92.900（macosx_14_0_arm64 专用轮） | **mac 侧先走 GIL 版 3.14** |
| glfw（py2.py3-none 纯轮） | ✅ | ✅ | 无障碍 |

**结论**：macOS 适配以 **GIL 版 Python 3.14** 为基线可完整 pip 安装；
free-threaded 等上游 imgui_bundle cp314t mac 轮（Windows 侧因完全无轮，已用 bootstrap wheel 方案）。

### 1.2 OpenGL 依赖面（全仓 grep）

- 引擎**零使用** GL 4.2+ 专属 API（`glTexStorage*` / `glDispatchCompute` / SSBO 绑定 / `glMapBufferRange` 等均无）；
- 全部硬编码点：6 个 shader 的 `#version 440 core` + `EditorWindow.py` / `RuntimeWindow.py`
  各 3 行「请求 4.4 core」window hint；
- macOS 上限 4.1 → **降级面 = shader 版本声明 + hint 平台自适应 + 全 GL 回归**
  （4.1 下 MRT / 浮点 RT / stencil / 混合行为需逐项实测）。

## 2. 风险表（优先级排序）

| # | 风险 | 状态 | 影响面 |
|---|---|---|---|
| 1 | **macOS 主线程约束**（Cocoa 要求窗口/事件在进程主线程；现架构为渲染线程持窗） | 未验证，理论必撞 | 可能迫使 Engine 线程模型加平台适配层 —— **最高优先级 spike** |
| 2 | OpenGL 4.1 上限 | 依赖面已缩（§1.2） | shader/hint 改动 + GL 全回归 |
| 3 | 依赖 wheel 覆盖 | 已基本排除（§1.1） | mac 基线 = GIL 版 |
| 4 | 安装包 / 签名 / 公证 | 工程与商业决策 | Apple 开发者账号（$99/年）决策；不签名 = Gatekeeper 拦截（右键打开 + 文档对策） |
| 5 | 细碎差异：COM↔/dev/tty.*、GBK↔UTF-8 控制台、进程 terminate 语义、路径分隔/大小写 | 可静态审计 | 逐项清单化 |

## 3. 阶段计划（P0 → P4）

### P0 零硬件静态审计（现在即可做，可与改名并行）
- [ ] wheel 矩阵扫描脚本化（本仓 `pip download --platform macosx_14_0_arm64` 即可，产出报告）；
- [ ] 平台分支 grep 清单：`os.name / sys.platform / COM / GBK / \\ 路径 / win32` 引用点；
- [ ] GL/shader 清单固化（§1.2 数据 + 4.1 兼容性逐项核对）；
- [ ] GitHub Actions 骨架：`windows-latest` + `macos-14`（arm64）跑 core 非 GL 子集
      （runner 空闲环境即 4.1 → 天然降级回归靶机）。

### P1 macOS 实机 spike（拿到 Mac 立即执行 — 先证伪最大风险）
- [ ] 干净环境装配（python.org 3.14 GIL + pip install 依赖矩阵）→ `test_runner` 非 GL 子集；
- [ ] GL 探测报告（4.1 差异全清单：shader 编译/RT/光照/窗口）；
- [ ] **编辑器窗口 spike**（主线程约束显形：窗口创建线程、事件泵、GL 上下文归属）；
- [ ] MCP loopback（8977 连通）。
- 产出：macOS 差距报告 + 2 个架构决策（线程模型改法、渲染基线改法）。

### P2 适配实现（依据 P1 结论）
- [ ] 平台层抽象：window / thread / path / console / process / serial 的集中点（平台差异只在此层）；
- [ ] GL 基线改造（shader 版本 / hint / 版本探测与报错）；
- [ ] 双端启动脚本（`startup.bat` / `startup.command`），`-Xgil=0` 改为**自适应**（GIL 构建不得硬性传参）。

### P3 安装工程
- Windows：Inno 构建自动化（CI artifact）+ 干净机验收清单；
- macOS：`.pkg`（推荐，可脚本化）vs `.dmg` 决策；签名 + 公证（依赖 D1 决策）；
  runtime 打包 = python.org 3.14 安装器产物 + `macosx_arm64` wheelhouse；
- 双端安装包分离构建（各自 CI job）。

### P4 持续
- 双平台 CI 门禁（core 测试 + 构建校验）；release checklist 固化（含安装/卸载/卸载残留）。

## 4. 另一台机器安装测试（方法）

1. **双端共用「安装验收清单」**（先写清单再上机器）：
   安装 → 启动（窗口/横幅）→ MCP 连接（CLI ping）→ 扩展 enable（Extensions 菜单截图）→
   跑一个样例实验（PIE 或 dry-run）→ 退出 → 卸载 → 残留检查（目录/注册表/快捷方式）。
2. **顺序**：先在 Windows 干净 VM（Hyper-V，快照回滚）把流程磨合熟 →
   再上真 Mac（原生或仅限 Apple 硬件的 VM）—— 避免同时 debug「流程」与「平台」两件事。
3. 清单尽量脚本化（PowerShell / bash），人工只做 UI 截图确认项。

## 5. 决策点

| # | 决策 | 建议 |
|---|---|---|
| D1 | Apple Developer 账号 + 公证 | 发放正式版必需（$99/年）；开发期可先不签名（右键打开 + 文档） |
| D2 | mac Python 基线 | **先 GIL 版 3.14**；free-threaded 后置（等 imgui_bundle 上游） |
| D3 | CI 平台/预算 | GitHub Actions macOS runner 按分钟计费，先小规模（core 子集） |
