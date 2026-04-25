TEST_BLOCK_VERTEX_SHADER = """
    #version 330 core
    layout (location = 0) in vec2 aPos;
    void main()
    {
        gl_Position = vec4(aPos.x, aPos.y, 0.0, 1.0);
    }
    """


TEST_BLOCK_FRAGMENTS_SHADER = """
    #version 330 core
    out vec4 FragColor;
    void main()
    {
        FragColor = vec4(1.0, 1.0, 1.0, 1.0);   // 红色
    }
    """


TEST_BLOCK_VERTECIES = [
    -0.5, 0.5,   # 左上角 0
    0.5, 0.5,   # 右上角 1
    0.5, -0.5,   # 右下角 2
    -0.5, -0.5    # 左下角 3
]

# 索引数据（两个三角形构成矩形）
TEST_BLOCK_INDICIES = [
    0, 1, 2,  # 第一个三角形 (右上)
    2, 3, 0   # 第二个三角形 (左下)
]
