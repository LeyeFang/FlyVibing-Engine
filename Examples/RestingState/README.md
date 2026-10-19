# RestingState

静息态示例：0 s 睁眼；20 s 闭眼；40 s 循环。

入口：编辑器 **File → Open Example → RestingState**。

- `scenes/RestingState.scene`：十字注视 + 睁眼/闭眼时间线。
- 并行口地址 `0x3FF8`，睁眼码 1、闭眼码 2。
- 关键节点带 `@alias` 与 `description`；整批显隐用 `EntityGetTree + EntityListSetVisible`。
