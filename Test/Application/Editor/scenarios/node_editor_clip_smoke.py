"""GUI 守卫: 节点编辑器在 0x0 / 1x1 / 正常窗口尺寸下都必须每帧返回。

回归 2026-10-19 扩展侧 issue: 左/右 dock 内容区为 0 时，imgui-node-editor
的 begin/end 栈若未闭合会卡死在原生 end()（表现为 GUI 场景永不退出）。
"""

NAME = "node_editor_clip_smoke"
TIER = "gui"


def run(ctx) -> None:
    import faulthandler
    import time

    import glfw

    # 进程级超时兜底：真正卡死时不要等外部 CI 超时。
    faulthandler.dump_traceback_later(8, exit=True)
    try:
        ctx.frames(3)
        panel = ctx.panel("Node Editor")
        ctx.expect(panel is not None, "Node Editor panel registered")
        ctx.expect(getattr(panel, "visible", False), "Node Editor starts visible")

        cases = ((0, 0), (1, 1), (320, 240), (1600, 900))
        for width, height in cases:
            glfw.set_window_size(ctx.boot.window, width, height)
            t0 = time.perf_counter()
            ctx.frames(3)
            elapsed = time.perf_counter() - t0
            ctx.expect(elapsed < 2.0,
                       f"{width}x{height}: 3 frames returned in {elapsed:.2f}s")
            fb = glfw.get_framebuffer_size(ctx.boot.window)
            # Windows/GLFW 会把宽度下限钳到 120；高度仍会到 0/1。
            # 断言重点是内容区被裁小且帧循环仍能返回。
            if width in (0, 1):
                ctx.expect(fb[0] <= 160 and fb[1] <= 1,
                           f"{width}x{height} clipped (framebuffer={fb})")

        ctx.frames(2)
        snap = ctx.snapshot("restored")
        ctx.expect(snap["width"] == 1600 and snap["height"] == 900,
                   f"restored viewport ({snap['width']}x{snap['height']})")
        ctx.expect(snap["bytes"] > 10000, "restored snapshot non-trivial")
    finally:
        faulthandler.cancel_dump_traceback_later()
