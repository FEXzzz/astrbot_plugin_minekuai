# 麦块资源与实例助手

适用于 **AstrBot >=4.16,<5 / Python >=3.12 / QQ OneBot v11（NapCat）**。

搜索 Minecraft 模组、整合包、光影、资源包和服务端插件；使用同一套指令和 AI 工具查询麦块实例，并在管理员确认后执行操作。

## 安装

1. 在 AstrBot WebUI 的插件管理中选择从仓库安装，填写 [FEXzzz/astrbot_plugin_minekuai](https://github.com/FEXzzz/astrbot_plugin_minekuai)。也可上传本地 `astrbot_plugin_minekuai-v1.1.0.zip`，或将完整插件目录放入 `AstrBot/data/plugins/astrbot_plugin_minekuai/`。
2. 安装依赖并重载插件。资源搜索不需要 API Key。
3. 在插件配置面板开启图片卡片；资源卡片使用 AstrBot 配置的文转图服务，失败时自动回退文本。
4. 实例管理默认关闭。需要时开启 `instance_enabled`，填写完整的 `mkc_...` 密钥，并在 AstrBot 中设置管理员账号。
5. 在 `operation_permissions` 中逐项选择会话权限，重载插件使 AstrBot 应用保存后的配置。执行服务始终读取当前配置。

实例密钥只在配置面板填写，不通过聊天或 AI 工具绑定。`secret` 只遮罩界面，不加密磁盘上的配置文件。实例接口使用独立 HTTP 客户端，不会把密钥发送给资源、图片或下载地址。

## AstrBot 旧版本兼容

从 1.1.0 起，将兼容下限调整为 AstrBot **4.16.0**，使用同一个安装包支持旧实例和新实例。Python 仍要求 3.12。

- 旧版没有插件独立 `logger` 时，使用 AstrBot 提供的全局日志接口。
- 4.16 的 `html_render()` 没有 `umo` 参数，插件按实际函数签名传参；新版继续传入会话来源，使用会话绑定的渲染配置。渲染内部错误不会触发重复调用。
- AI 工具注册后固定为准确的插件模块归属，使旧版的启停、权限关联与重载清理正确识别本插件。
- 实例别名配置使用 4.16 支持的列表编辑器；1.0.0 的别名字典在首次加载时自动迁移并保存。
- 配置键、插件标识、作者、KV 存储及数据目录保持稳定，已有实例密钥、权限和冷却记录可继续使用；升级安装包后重载插件。
- 4.16 的配置面板没有实现 `secret` 输入遮罩，密钥可能以普通文本框显示；较新的面板支持遮罩。插件无法单独替换宿主面板的输入控件，请只在管理员面板中填写密钥。

接口差异根据 [AstrBot 4.16 Star 源码](https://github.com/AstrBotDevs/AstrBot/blob/v4.16.0/astrbot/core/star/__init__.py)、[旧版工具注册](https://github.com/AstrBotDevs/AstrBot/blob/v4.16.0/astrbot/core/star/context.py) 和 [配置控件](https://github.com/AstrBotDevs/AstrBot/blob/v4.16.0/dashboard/src/components/shared/ConfigItemRenderer.vue) 适配。真实 SDK 加载、指令、工具调用、卡片参数和重载清理用 `scripts/check_astrbot_sdk.py` 验证。

## 资源查询

```text
/麦块 搜索 机械动力
/mk 搜索 优化 类型=模组 来源=mr 版本=1.20.1 加载器=fabric
/麦块 搜索 "Just Enough Items" 类型=模组 来源=cf
/麦块 热门 类型=整合包 来源=cf
/麦块 详情 mr_mod:jei
/麦块 详情 2
/麦块 版本 mr_mod:jei 版本=1.20.1 加载器=forge
/麦块 下载 mr_mod:jei 版本=1.20.1 加载器=forge
/麦块 下载 mr_mod:jei 版本ID=接口返回的版本ID
/麦块 下载 mr_mod:jei 预览=是
/麦块 筛选 类型=模组 来源=mr
/麦块 下一页
/麦块 帮助
```

高级筛选可用 `版本`、`加载器`、`分类`、`客户端`、`服务端`、`翻译`、`排序`、`方向`；多值用英文逗号分隔。关键词搜索默认保留相关度；未指定类型的聚合搜索每类显示一条，不支持伪造翻页，高级筛选和分页需要类型与来源。

| 类型 | 来源 | 标识前缀 |
|---|---|---|
| 模组 | `mr` / `cf` | `mr_mod` / `cf_mod` |
| 整合包 | `mr` / `cf` | `mr_modpack` / `cf_modpack` |
| 光影 | `mr` | `shader` |
| 资源包／材质包 | `mr` | `resourcepack` |
| 插件 | `mr` / `cf` / `spigot` | `mr_plugin` / `cf_plugin` / `spigot_plugin` |

例如 `mr_mod:jei` 和 `cf_mod:jei` 是两个独立资源。有中文优先显示中文；未翻译则显示原文。序号和翻页按平台、会话及发送者隔离，15 分钟后失效。

下载按游戏版本和加载器匹配，默认选择正式版；上游缺少发布类型时明确标记 `unknown`。作者限制分发、付费或没有直链时返回项目页。接口返回的版本范围不一定包含所有历史文件。插件只提供链接。

## 实例管理

```text
/麦块 实例 列表 页=1
/麦块 实例 状态 ab12cd34
/麦块 实例 启动 ab12cd34
/麦块 实例 停止 ab12cd34
/麦块 实例 重启 ab12cd34
/麦块 实例 强停 ab12cd34
/麦块 实例 命令 ab12cd34 say 服务器将在五分钟后重启
/麦块 实例 启动配置 ab12cd34
/麦块 实例 设置变量 ab12cd34 MAX_PLAYERS 20
/麦块 实例 设置变量 ab12cd34 MOTD "欢迎 来到服务器"
/麦块 实例 可切换游戏 ab12cd34
/麦块 实例 切换游戏 ab12cd34 minecraft
/麦块 实例 切换整合包 ab12cd34 id=1
/麦块 实例 切换整合包 ab12cd34 文件=xxx.zip
/麦块 实例 读取文件 ab12cd34 /server.properties 页=1
/麦块 实例 确认 机器人给出的确认码
/麦块 实例 取消 机器人给出的确认码
```

`ab12cd34` 是示例，必须替换为实例列表返回的 8 位 identifier。可在配置面板的 `instance_aliases` 中添加一条记录，填写别名 `生存服`、identifier `ab12cd34`，之后使用 `/麦块 实例 状态 生存服`。旧版字典格式 `{"生存服":"ab12cd34"}` 会在首次加载时自动迁移。

所有写操作都先预览，确认码默认 60 秒有效，只接受同一管理员在同一平台与会话的明确确认。确认码一次使用；权限变化、密钥变化、重载或过期都会阻止执行。AI 工具只能查询或准备操作。

**切换游戏／整合包会删除实例全部文件并重装。请先在面板完成备份。** 两种切换共享每实例 60 秒冷却；插件保存冷却记录。`modpack_id` 是面板安装目录中的 ID，不能拿公共资源 ID 替代；`file_name` 是面板提供的文件名，不是下载 URL。

电源成功响应表示已受理，插件最多查询 30 秒的状态；重启只有观察到状态转换才报告完成。命令成功只表示已提交，不代表拿到了输出。文件只读，最大 1 MB，按最多 4000 字符分页；常见密码、令牌字段会遮罩。私有文件和启动变量使用文本，私有状态卡片仅本地绘制。

### 按操作配置群聊／私聊

每项操作都有 `scope` 和 `allowed_groups`：

| scope | 行为 |
|---|---|
| `disabled` | 禁用 |
| `private` | 仅管理员私聊（默认） |
| `group` | 仅允许列表中的群 |
| `both` | 管理员私聊及允许列表中的群 |

无论 scope 如何，调用者都必须是 **AstrBot 管理员**，普通 QQ 群管理员没有权限。群列表为空时不允许任何群。列表可以写 `123456789`，也可写 `平台实例ID:123456789` 区分多个机器人。

可以单独设置列表、状态、四种电源操作、控制台、启动配置读写、可切换游戏、两种切换和文件读取。例如仅将 `status` 设为 `both` 并添加群号，其他项继续 `private`；也可以授权文件读取在指定群使用。

## 配置与排错

- 默认资源／实例请求预算各 120 次／分钟；上游限制分别为 IP 600 次／分钟和每密钥 300 次／分钟。实例密钥若被其他程序共用，仍共享上游额度。
- 默认读取超时 10 秒、写请求 30 秒；GET 最多 3 次尝试，写请求从不自动重试。写请求超时提示“结果未知”，先检查面板／实例状态再决定是否重新操作。
- 401：密钥无效或被撤销。403：检查面板权限与 IP 白名单；机器人部署位置的出口 IP 必须被允许。409：实例状态冲突或冷却未结束。422：检查变量、游戏或整合包参数。429：稍后重试。
- 中文实例卡片在 Windows 自动查找微软雅黑；Linux 可安装 Noto CJK／文泉驿，或设置 `local_font_path` 为已存在的字体文件；缺少字体回退文本。
- `/麦块 诊断` 查看配置状态和缓存数量；`/麦块 清理缓存` 清理查询缓存。
- 运行数据放在 `data/plugin_data/astrbot_plugin_minekuai/`，KV 存储由 AstrBot 管理。卡片限制为 64 个以内，每次绘制时清理超过 15 分钟的旧卡片；文件内容不写入插件日志或持久化数据库。
- 插件仓库为 [FEXzzz/astrbot_plugin_minekuai](https://github.com/FEXzzz/astrbot_plugin_minekuai)，`metadata.yaml` 已声明仓库地址，可通过 AstrBot 的仓库安装及更新入口使用。

## AI 工具

插件注册 12 个显式 Schema 工具：资源搜索、详情、版本、下载、筛选、结果展示；实例列表、状态、启动配置、可切换游戏、文件读取、准备操作。

例如：“找适合 1.20.1 Fabric 的优化模组”“查看生存服状态”“把生存服最大人数改为 20”。查询工具返回 `result_id`，AI 调用 `minekuai_present` 展示最终卡片或文本。写工具会直接向当前管理员发送预览及确认指令。请在 AstrBot 中启用支持工具调用的聊天模型，并确保会话启用了本插件工具；不配置模型仍可使用全部普通指令。

## 开发与验证

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python scripts/smoke_public.py
python scripts/build_release.py
```

完整私有接口合约见 [docs/client-api.md](docs/client-api.md)。

架构：`main.py` 负责 AstrBot 注册和消息发送，`minekuai/` 包含 HTTP、资源来源适配、实例服务、权限、状态和指令解析，`templates/` 为资源卡片模板。所有入口共用相同业务逻辑和权限检查。

## 参考与许可

- [AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)
- [AstrBot 工具开发](https://docs.astrbot.app/dev/star/guides/ai.html)
- [AstrBot HTML 文转图](https://docs.astrbot.app/dev/star/guides/html-to-pic.html)
- [麦块资源 API](https://bbs.minekuai.com/open-api)
- 实例 API 合约来自面板文档。

插件代码使用 MIT 许可。资源数据由麦块收录，原项目与下载文件的权利归各自作者，中文翻译由上游提供。
