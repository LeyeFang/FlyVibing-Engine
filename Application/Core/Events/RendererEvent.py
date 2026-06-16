from Application.Core.Events.Event import Event


class RendererMeshReleaseEvent(Event):
    """渲染器网格释放通知。"""

    def __init__(self, mesh_id: int) -> None:
        super().__init__()
        self.release_mesh_id: int = mesh_id

    @property
    def log_info(self) -> str:
        return f"Renderer-Mesh '{self.release_mesh_id}' has been released !"

    @classmethod
    def Pack(cls, mesh_id: int) -> None:
        super().Pack(mesh_id)
