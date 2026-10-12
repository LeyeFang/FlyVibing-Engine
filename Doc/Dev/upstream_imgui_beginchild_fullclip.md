# 上游 Issue 材料：imgui `BeginChild()` 全裁剪返回 false → 漏配对 `EndChild()` 延迟杀渲染循环

> 由来：Gtec 监视面板扩展开发中发现并修复（2026-10-12，本仓 MyGameEngine-Python）。
> 本文件 = 向 **imgui / imgui_bundle 官方**提 issue 的完整材料（现象 / 最小复现 / 实机证据 / 我方修改 / 建议）。
> 复现脚本：`Utils/Dev/repro_imgui_child_clipping.py`（零依赖，仅需 `imgui_bundle`，无需 GL）。
> 实测环境：**imgui_bundle 1.92.5 / Dear ImGui 1.92.3**，Windows，Python 3.14（free-threading）。

---

## 0. 30 秒速览（中文）

- **现象**：编辑器窗口最小化后恢复时整个渲染循环被异常杀死 ——
  `RuntimeError: IM_ASSERT(... "Must call EndChild() and not End()!" ) --- imgui.cpp:8677`。
- **根因链**：宿主窗口 0×0（最小化）→ `BeginChild()` 返回 **false**（全裁剪）；
  广泛流传的写法 `if (BeginChild()) { ...; EndChild(); }` 会**跳过 `EndChild()`** →
  窗口栈失衡 → 之后任意一个 `End()`（我们这里是面板 `end_panel()`）触发断言。
  跳过错配的那一帧**不一定**当帧报错，错误与根因可能相隔很远，排查成本极高。
- **官方现状（v1.92.3 头文件已核对，原文见 §1 “What the official docs already say” 引文块）**：
  - `imgui.h` 已写明：`BeginChild()` 可能因 “collapsed or **fully clipped**” 返回 false，
    **必须无条件配对 `EndChild()`**；并自认这是与其它 BeginXXX 不一致的“历史遗留”，
    “Will be fixed in a future update”；
  - 官方有调试工具 `io.ConfigDebugBeginReturnValueOnce / ...Loop`（专门用来抓这类错配）；
  - 反向规则并存：`BeginCombo` 明确 “only call EndCombo() if BeginCombo() returns true!” ——
    两套相反语义非常容易踩坑（两种误用各自的报错我们均已实测，见 §2）。
- **建议的 issue 定位**（不是“行为错误”，而是**可用性/诊断成本**反馈，含三个小改进建议）：
  1. `BeginChild()` 文档点名常见现实触发（“例如宿主窗口最小化 → 0×0”）；
  2. `End()` 上的该断言补充行动指引（提示检查跳过 `EndChild()` 的调用方）；
  3. 在 `Begin()/BeginChild()` 文档行交叉引用那对官方调试开关（现藏于 `ImGuiIO` 深处，极易漏）。
- **我方已修**（见 §4）：两个官方扩展示例全部改为 `try/finally` 无条件配对 + 无头回归测试
  （裸 imgui 上下文连续绘制 0×0 / 1×1 / 恢复帧）。

---

## 1. English issue draft（可直接提交）

> 提交前建议先搜一遍是否有重复（关键词：`EndChild`, `Must call EndChild() and not End()`,
> `minimized`, `ConfigDebugBeginReturnValueLoop`, `fully clipped`）。若视为 “working as
> intended / planned fix”，可直接引用 §1.4 的原文并转为文档补强建议后关闭。

### Title (pick one)

- `BeginChild() returning false when fully clipped (e.g. minimized host): the widespread if(){...EndChild();} pattern corrupts the window stack and fails far from the cause — suggest clearer docs/diagnostics`
- (shorter) `Document the BeginChild() false path better: fully-clipped (0x0) plus skipped EndChild() kills a later frame`

### Body

**Environment**
- Dear ImGui 1.92.3 (via imgui_bundle 1.92.5), Windows 11, Python 3.14 free-threaded.
- Also reproduced with the raw C++ window-stack semantics (no backend/renderer involved;
  the repro only exercises Begin/BeginChild/End/EndChild bookkeeping).

**What happened (real-world impact)**
- In our editor, minimizing the host window (a later frame drew with `io.DisplaySize == (0, 0)`)
  made a plugin panel skip `EndChild()` because `BeginChild()` returned false.
- The next `End()` (our panel's `end_panel()` -> `ImGui::End()`) raised
  `Must call EndChild() and not End()` (imgui.cpp:8677) and **killed the entire render loop**.
- The mispairing frame is often *not* where the failure surfaces: code review and normal-size
  testing will never see it, because the bad pattern happens to balance whenever the child is
  visible. It only breaks when the child is fully clipped.

**Minimal repro (Python — full script attached in the same folder as this file)**
```python
from imgui_bundle import imgui
imgui.create_context()
io = imgui.get_io()
io.backend_flags |= imgui.BackendFlags_.renderer_has_textures
io.display_size = imgui.ImVec2(1280, 720)

def frame(body):
    imgui.new_frame(); body(); imgui.end_frame(); imgui.render()

def body():                      # the widespread (unsafe) pattern
    imgui.begin("W")
    if imgui.begin_child("C", imgui.ImVec2(300, 200), True):   # False when fully clipped
        imgui.text("content")
        imgui.end_child()        # -> skipped => stack corrupted
    imgui.end()

frame(body)                      # normal size: fine (pairs by luck)
io.display_size = imgui.ImVec2(0, 0)   # host minimized / fully clipped
frame(body)                      # RuntimeError: "Must call EndChild() and not End()!" (imgui.cpp:8677)
```
C++ equivalent:
```cpp
ImGui::Begin("W");
if (ImGui::BeginChild("C", ImVec2(300, 200), true)) {  // false when fully clipped
    ImGui::Text("content");
    ImGui::EndChild();                                  // skipped -> corruption
}
ImGui::End();   // IM_ASSERT "Must call EndChild() and not End()!"
```

**Measured semantics (Dear ImGui 1.92.3, all deterministic)**

| scenario | result |
|---|---|
| `BeginChild()` at normal size, `0x0`, `1x1`, restored | `True, False, False, True`; unconditional `EndChild()` keeps 4 frames balanced |
| bad pattern, frame at normal size | no error (pairs by luck — bug invisible) |
| bad pattern, frame at `0x0` | `BeginChild()==False` → **same-frame assert** `Must call EndChild() and not End()` (imgui.cpp:8677) |
| unconditional `EndCombo()` after `BeginCombo()==false` (opposite rule) | **assert** `Calling EndPopup() too many times or in wrong window!` (imgui.cpp:13112) |
| `io.ConfigDebugBeginReturnValueOnce = true`, correct pattern | frame stays balanced, `BeginChild()` returns false once (tool works) |
| `io.ConfigDebugBeginReturnValueLoop = true`, bad pattern | child flips to false at frame 12 → same assert reproduced in dev |

**What the official docs already say (v1.92.3, quoted for reference)**
```cpp
// imgui.h, Begin():
// - Begin() return false to indicate the window is collapsed or fully clipped, so you may early out and omit submitting
//   anything to the window. Always call a matching End() for each Begin() call, regardless of its return value!

// imgui.h, BeginChild():
// - BeginChild() returns false to indicate the window is collapsed or fully clipped, so you may early out and omit submitting
//   anything to the window. Always call a matching EndChild() for each BeginChild() call, regardless of its return value.
//   [Important: due to legacy reason, Begin/End and BeginChild/EndChild are inconsistent with all other functions
//    such as BeginMenu/EndMenu, BeginPopup/EndPopup, etc. where the EndXXX call should only be called if the corresponding
//    BeginXXX function returned true. Begin and BeginChild are the only odd ones out. Will be fixed in a future update.]

// imgui.h, BeginCombo():
IMGUI_API void EndCombo(); // only call EndCombo() if BeginCombo() returns true!

// imgui.h, ImGuiIO (debug tools):
// Tools to test correct Begin/End and BeginChild/EndChild behaviors.
// - Presently Begin()/End() and BeginChild()/EndChild() needs to ALWAYS be called in tandem, regardless of return value of BeginXXX()
// - This is inconsistent with other BeginXXX functions and create confusion for many users.
// - We expect to update the API eventually. In the meanwhile we provide tools to facilitate checking user-code behavior.
bool ConfigDebugBeginReturnValueOnce; // First-time calls to Begin()/BeginChild() will return false. NEEDS TO BE SET AT APPLICATION BOOT TIME if you don't want to miss windows.
bool ConfigDebugBeginReturnValueLoop; // Some calls to Begin()/BeginChild() will return false. Will cycle through window depths then repeat. ...
```
So this is **documented intended behavior** — the issue we are filing is a request to reduce the
diagnosis cost of a very common misuse, not a claim of wrong behavior.

**Concrete asks (small, non-breaking, docs/diagnostics only)**
1. `BeginChild()` doc comment: mention the mundane real-world cause of the false path —
   “e.g. the host window is fully clipped such as minimized to 0×0” — right next to
   “collapsed or fully clipped”.
2. The `End()`/`EndChild()` mismatch assert (`"Must call EndChild() and not End()"`) could append
   an actionable hint, e.g. “check for a `BeginChild()` whose return value gated your
   `EndChild()` call (the two must always be paired regardless of the return value)”.
3. Cross-reference `io.ConfigDebugBeginReturnValueOnce/Loop` from the `Begin()`/`BeginChild()`
   doc lines; the tools are exactly for this class of bug but are easy to miss inside `ImGuiIO`.

**Our mitigation (for reference)**
- All child windows in our codebase now pair unconditionally, e.g.:
```python
open_ = imgui.begin_child(...)
try:
    if open_:        # skip CONTENT, never skip EndChild
        draw_content()
finally:
    imgui.end_child()
```
- Regression harness: draw frames with the display size forced through `0x0` / `1x1` / restored
  and assert the stack stays balanced (this reproduces the original crash deterministically).

---

## 2. 最小复现（脚本实测输出）

运行方式（本仓 dev venv；任意装有 `imgui_bundle` 的环境同样可运行）：

```powershell
.venv-py314t\Scripts\python.exe Utils\Dev\repro_imgui_child_clipping.py
```

实测输出（2026-10-12，imgui_bundle 1.92.5 / Dear ImGui 1.92.3；
下略 imgui 进程侧同步打印的 `[00002]`/`[00012]` `[imgui-error]` 日志行 ——
它们注明触发窗口与帧号，与脚本输出之间的行序随捕获方式（控制台/重定向）略有差异）：

```
== imgui BeginChild/EndChild pairing under full clipping (0x0) ==
   Dear ImGui: 1.92.3
   imgui_bundle: 1.92.5

-- A: correct pattern (EndChild always) --
   4 frames OK; begin_child() returned per frame: [True, False, False, True]
   children -> False at 0x0/1x1
-- B: wrong pattern (EndChild inside the if) --
   frame@1280x720: no exception (begin_child=True) — mispairing invisible at normal size
   frame@0x0: begin_child=False -> RAISED on the same frame's End() -> RuntimeError: IM_ASSERT( (g.WithinEndChildID == window->ID) && "Must call EndChild() and not End()!" )   ---   imgui.cpp:8677
-- C: asymmetry contrast — EndCombo is conditional --
   conditional EndCombo: OK
   unconditional EndCombo: RAISED -> RuntimeError: IM_ASSERT( (0) && "Calling EndPopup() too many times or in wrong window!" )   ---   imgui.cpp:13112
-- D: official debug tool — io.ConfigDebugBeginReturnValue* --
   debug-once + correct pattern: OK, returns=[('begin', True), ('child', False)]
   debug-loop + wrong pattern: child flipped to false at frame 12 of 12 -> RAISED -> RuntimeError: IM_ASSERT( (g.WithinEndChildID == window->ID) && "Must call EndChild() and not End()!" )   ---   imgui.cpp:8677

RESULT: OK (4/4 semantics confirmed)
```

## 3. 实机证据（本仓编辑器崩溃链，2026-10-12）

```
[EditorHost] Time: 33.6011, Event: WindowResizeEvent, Window Size: (width, height) = (0, 0)
        ← 窗口最小化：0×0（此后帧被完全裁剪）
...
[Live] id=2 op=extension.enable → ok
[13740] [imgui-error] In window 'Gtec Monitor/##gtec_controls_E3D4498F/##gtec_view_5A5EAB57':
                      Must call EndChild() and not End()!
[EditorHost] Time: 84.4790, Event: EngineLifecycleEvent,
             [exception] _render_loop EXCEPTION: IM_ASSERT( (g.WithinEndChildID == window->ID)
             && "Must call EndChild() and not End()!" )   ---   imgui.cpp:8677
Traceback (most recent call last):
  ... Engine._render_loop → EditorImguiLayer.OnRender → UIManager.draw_all
      → panel.end_panel() → BasePanel.py: imgui.end() → RuntimeError
```

要点：跳过错配的帧当时**没有立刻报错**，断言发生在之后一次普通的 `end_panel()` 上 ——
错误与根因（最小化事件）在时间和调用栈上都相隔很远，这是本 issue 想改善的核心。

## 4. 我方修改清单（本仓，供 issue 正文引用）

| 文件 | 修改 | 说明 |
|---|---|---|
| `Functions/EEGDevice/Gtec/extension.py` | `_draw_panel()` 两个子窗口改为 `try/finally` **无条件 `end_child()`**（内容仍按返回值跳过） | 直接修复本次崩溃 |
| `Functions/EEGDevice/Gtec/gtec_scope.py` | `draw_quality_table()` 同样无条件配对；`begin_table` 按返回值在 `finally` 中守卫 | 同类隐患一并清除 |
| `Functions/SerialParallelDevice/extension.py` | 官方 device 示例同隐患修复（`_draw_stream()` 拆出 `_draw_stream_rows()` + 无条件配对） | 示例是全仓参考，必须正确 |
| `Test/Application/Extensions/test_gtec_extension.py` | 新增 “imgui stack balance (clipped 0x0 regression)”：裸 imgui 上下文连续绘制 `1280×720 → 0×0 → 1×1 → 1280×720` 帧并断言栈平衡 | 回归守卫（当时代码按错模式写会立刻失败） |
| `Doc/Dev/ui_protocol.md` §2.13、`Doc/ExtDev/extension_dev_protocol.md` §7.7 | 配对纪律成文：child = 无条件配对；combo/tabitem = 仅返回 true 时 end | 防再次踩坑（含本 issue 结论） |

## 5. 提交提示（中文）

- **先搜重复**：`Must call EndChild() and not End()`、`EndChild` + `minimized`、`ConfigDebugBeginReturnValueLoop`。
- **预期回复**：维护者大概率回 “by design / documented / planned API fix”（头文件原文如此）。
  此时可把 issue 收窄为 §1 “Concrete asks” 三条（纯文档/诊断改进）再讨论；若被直接关闭，
  本仓 §4 的纪律与回归测试已足够自保。
- **附材料**：提交时附上 `Utils/Dev/repro_imgui_child_clipping.py`（或将其内两段代码贴进正文）。
