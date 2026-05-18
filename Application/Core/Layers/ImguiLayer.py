from Application.Core.Layers.Layer import Layer

from imgui_bundle import imgui


class ImguiLayer(Layer):
    @classmethod
    def OnAttach(cls):
        pass

    @classmethod
    def OnDetach(cls):
        pass

    @classmethod
    def OnEvent(cls, event):
        pass

    @classmethod
    def OnUpdate(cls):
        # 1. 首先调用后端的 new_frame（顺序必须是 glfw -> opengl3）
        imgui.backends.glfw_new_frame()
        imgui.backends.opengl3_new_frame()
        imgui.new_frame()
        imgui.show_demo_window()
        
        # 4. 调用 render（注意：render 应该在每帧的最后，并且要交换缓冲区）
        imgui.render()
        imgui.backends.opengl3_render_draw_data(imgui.get_draw_data())
