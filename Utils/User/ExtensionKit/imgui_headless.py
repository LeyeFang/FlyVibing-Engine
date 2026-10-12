"""imgui_headless — 无头 imgui 上下文的**唯一入口**（测试 / 扩展自测 / 无 GL 回归）。

为什么需要它（2026-10-12 实测，协议见 `Doc/ExtDev/extension_dev_protocol.md` §12）:

  1. **ini 落盘**：裸 `imgui.create_context()` 之后若不处理，imgui 会在
     `destroy_context()` 时把 `imgui.ini` 写到**当前工作目录** —— 在仓库/app 根留下
     垃圾文件（扩展自测最常踩：我们在 §12 鼓励作者写这种 GUI 回归测试）。
  2. `io.set_ini_filename("")` 才是"禁用"的正确写法；`imgui.ini` 只在
     `destroy_context()` 落盘（不是每帧）。
  3. ★ `io.set_ini_filename(None)` **会让进程原生访问违例崩溃**（exit 0xC0000005，可复现）
     —— 绝不要用 None。

用法:
    from Utils.User.ExtensionKit.imgui_headless import headless_imgui

    with headless_imgui() as h:
        h.frames([(1280, 720), (0, 0), (1, 1), (1280, 720)], draw=my_panel_draw)
    # 退出时不会有 imgui.ini 产生

注意: 首帧不判定裁剪（0x0 从**第二帧**起才 `BeginChild() == False`），
      所以全裁剪回归必须像上面那样先画一帧正常尺寸。
"""

from __future__ import annotations

from contextlib import contextmanager

from imgui_bundle import imgui

__all__ = ["headless_imgui", "disable_ini"]


def disable_ini(io=None) -> None:
    """禁用 imgui 布局持久化（**唯一正确写法 = 空字符串**）。

    传 `None` 会让进程崩溃（原生访问违例）—— 见模块 docstring。
    """
    (io if io is not None else imgui.get_io()).set_ini_filename("")


class _HeadlessSession:
    """无头会话句柄（`with headless_imgui() as h:`）。"""

    def __init__(self, io) -> None:
        self.io = io

    def set_size(self, width: float, height: float) -> None:
        self.io.display_size = (float(width), float(height))

    def frame(self, draw) -> None:
        """画一帧（`draw()` 自行 begin/end 窗口）。"""
        imgui.new_frame()
        draw()
        imgui.end_frame()
        imgui.render()

    def frames(self, sizes, draw) -> None:
        """按 `sizes` 顺序逐帧绘制 —— 全裁剪回归传 `[(1280,720),(0,0),(1,1),(1280,720)]`。"""
        for width, height in sizes:
            self.set_size(width, height)
            self.frame(draw)


@contextmanager
def headless_imgui(width: float = 1280.0, height: float = 720.0,
                   delta_time: float = 0.016):
    """建一个禁用 ini 的无头 imgui 上下文，退出时销毁（不产生 `imgui.ini`）。"""
    imgui.create_context()
    io = imgui.get_io()
    io.display_size = (float(width), float(height))
    io.delta_time = float(delta_time)
    io.backend_flags |= imgui.BackendFlags_.renderer_has_textures
    disable_ini(io)
    try:
        yield _HeadlessSession(io)
    finally:
        imgui.destroy_context()
