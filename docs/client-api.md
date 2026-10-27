# 麦块面板实例 API 合约

本文件整理自用户在 2026-10-26 提供的接口规范，供适配和回归测试使用。没有密钥时只能验证模拟响应，不能据此声称真实实例联调通过。

- Base URL：`https://api.minekuai.cn/panel/client-api`
- 请求头：`Authorization: Bearer <完整 mkc_ 密钥>`、`Content-Type: application/json`、`Accept: application/json`。
- 密钥仅访问自己的实例，权限与面板一致；IP 白名单拒绝返回 403。
- 每把密钥 300 次／分钟；游戏切换与整合包切换每实例共享 60 秒冷却。
- `{id}` 为 `/servers` 返回的 8 位 `identifier`，不是完整 UUID，也不是资源项目 ID。

| 方法 | 路径 | 参数 |
|---|---|---|
| GET | `/servers` | `page`、`per_page` |
| GET | `/servers/{id}` | 状态位于 `stats.attributes.current_state`，资源用量位于 `resources` |
| POST | `/servers/{id}/power` | `{"signal":"start/stop/restart/kill"}` |
| POST | `/servers/{id}/command` | `{"command":"say hello"}`；必须运行中 |
| GET | `/servers/{id}/startup` | 获取变量与启动命令 |
| PUT | `/servers/{id}/startup/variable` | `{"key":"env_variable","value":"值"}` |
| GET | `/servers/{id}/allowed-games` | 获取合法 `game_type` |
| POST | `/servers/{id}/game-switch` | `{"game_type":"minecraft"}`；清空全部文件并重装 |
| POST | `/servers/{id}/modpack-switch` | `{"modpack_id":1}` 或 `{"file_name":"xxx.zip"}`；清空全部文件并重装 |
| GET | `/servers/{id}/files/contents` | 查询参数 `file=/server.properties`；成功返回原始 `text/plain`；最大 1 MB |

HTTP 2xx 为成功，失败返回 `{"error":"失败原因"}`。401 密钥无效、403 权限／IP 白名单、404 不存在、409 状态冲突、422 参数错误、429 限流。电源、命令和切换动作成功返回 `{"success":true}`；变量修改成功响应结构需要接入时核对，并通过重新读取变量核验。

列表完整包裹、启动变量完整包裹、游戏列表完整包裹以及资源指标单位未在所给示例中完整展开。适配器接受常见的 `data[].attributes` 和文档语义对应的显式字段；不认识的结构直接报错，不继续修改。仅 `_bytes` 字段按字节换算，其余没有明确单位的数字显示接口原值。

控制台 API 不提供执行输出。规范未提供实例文件写入／上传、备份／恢复、整合包候选目录接口，因此插件不伪造这些能力。
