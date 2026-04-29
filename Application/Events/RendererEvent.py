from Application.Events import Event


class RendererMeshReleaseEvent(Event):

    log_info: str = ''
    release_mesh_id: int

    @classmethod
    def Pack(
        cls,
        mesh_id: int
    ) -> None:
        cls.release_mesh_id = mesh_id
        cls.log_info = f"Renderer-Mesh '{mesh_id}' has been released !"
        super().Pack()

    @classmethod
    def UnPack(
        cls
    ) -> None:
        pass
