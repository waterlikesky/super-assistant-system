# 数据源全景：打通哪些数据，各用什么方式接入

> 回答「打通所有数据，这些数据都有哪些，都是采用 MCP / CLI / 官方接口来实现吗」。
> 结论先说：**没有一种统一方式**。能用官方接口的用官方接口（IMAP、企业微信会话存档、飞书 / 钉钉开放平台、Google / Microsoft Graph）；个人微信、iPhone 短信这类**没有官方接口**的，只能吃用户自己导出的文件或本机备份；MCP server 是官方接口的一层包装，适合「给 Agent 用」，sas 只启用其中的**只读**工具。
> 所有接入都遵守：只读、本地落库前脱敏、凭据只走环境变量或系统 keyring、出站不实现（见 [PRODUCT.md](PRODUCT.md)）。
> 核实日期 2026-10-07。标「以官方文档为准」的细节（权限名、配额、是否收费）本仓库未能逐条在线核实，接入前请再确认。

## 状态图例

- **已实现**：有 connector、有虚构夹具与测试，`sas` 命令可用
- **桩**：仅文档 / 配置位，无可用代码
- **计划**：列入 [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md)，尚未开工

## 总表

| 数据源 | 实际 / 计划接入方式 | 官方? | 只读? | 认证 | 主要风险 | 本仓库状态 | 链接 |
|--------|--------------------|-------|-------|------|---------|-----------|------|
| **微信（个人号）** | **导出文件**：WeChatMsg / 留痕导出的 txt、csv（`sas ingest`） | ❌ 微信个人号**没有任何官方数据 API**；导出工具为第三方 | ✅ | 无（用户在本机导出） | 本机解密类工具有 ToS / 封号 / 法律风险：**[sjzar/chatlog](https://github.com/sjzar/chatlog) 已于 2025-10 因微信官方函件删库**，PyWxDump 亦已删库。sas 不做解密、Hook、协议号 | ✅ 已实现（txt / csv） | [LC044/WeChatMsg](https://github.com/LC044/WeChatMsg) |
| **企业微信** | 计划：官方「**会话内容存档**」API（企业管理员开通，需员工知情同意，消息用企业 RSA 私钥解密） | ✅ 官方 | ✅ | corpid + 会话存档 secret + RSA 私钥 | **付费的企业接口**（按席位计费，以官方为准）；企业合规与员工同意；数据属于企业，不宜混入个人库 | 计划 | [会话内容存档](https://developer.work.weixin.qq.com/document/path/91360) |
| **钉钉** | 现：用户导出 / 整理的 csv、xlsx；计划：钉钉开放平台 API 或官方 MCP（只启用读类工具） | 导出：用户自有；MCP / API：✅ 官方 | ✅（sas 侧只读） | 企业内部应用 AppKey / AppSecret，管理员授权 | 企业数据边界；开放平台对聊天记录的读取能力有限（以官方文档为准）；MCP 也含写操作工具，sas 不启用 | ✅ 已实现（csv / xlsx）；API / MCP 计划 | [open-dingtalk/dingtalk-mcp](https://github.com/open-dingtalk/dingtalk-mcp) |
| **飞书 / Lark** | 计划：官方 MCP 或官方 CLI 读取消息、文档、日历（只读 scope） | ✅ 官方 | ✅（sas 侧只读） | 自建应用 app_id / app_secret，或用户 OAuth（user_access_token） | 企业租户授权；scope 过大风险；MCP / CLI 均含写操作，需限定工具 | 计划 | [larksuite/lark-openapi-mcp](https://github.com/larksuite/lark-openapi-mcp)、[larksuite/cli](https://github.com/larksuite/cli)（17.5k★，MIT） |
| **邮件：通用 IMAP** | **官方协议 IMAP**：`sas imap`，`EXAMINE` + `BODY.PEEK[]`，按 UID 增量 | ✅ 标准协议 | ✅ 代码层强制（写命令直接抛错） | 邮箱密码 / 授权码，只读环境变量 `SAS_IMAP_PASSWORD` 或 keyring | 授权码等同密码，泄露即可读全部邮件；sas 不落盘凭据 | ✅ 已实现 | 本仓库 `sas/connectors/imap.py` |
| 　QQ 邮箱 | IMAP（`--provider qq`，imap.qq.com:993） | ✅ | ✅ | 网页版设置中开启 IMAP 后生成的**授权码** | 同上 | ✅ 已实现（预设） | QQ 邮箱帮助中心 |
| 　163 / 126 邮箱 | IMAP（`--provider 163`），登录后自动发送 IMAP `ID` 命令（网易要求，否则报 Unsafe Login） | ✅ | ✅ | 客户端**授权码** | 同上 | ✅ 已实现（预设） | 网易邮箱帮助 |
| 　Gmail | 现：IMAP + **应用专用密码**（需开两步验证）；或 Google Takeout 导出 mbox（`sas ingest`）。计划：Gmail API OAuth 只读 scope | ✅ | ✅ | 应用专用密码；或 OAuth `gmail.readonly` | Google 可能收紧应用专用密码；OAuth 应用需验证 | ✅ IMAP / mbox 已实现；API 计划 | [Takeout](https://takeout.google.com) |
| 　Outlook / Microsoft 365 | 现：导出 .eml / .mbox 后 `sas ingest`。计划：Microsoft Graph（`Mail.Read`）或微软官方 MCP | ✅ | ✅ | **OAuth2**（微软已停用 Exchange Online 的基本认证，个人号 IMAP 也需 OAuth，`--provider outlook` 用密码大概率失败） | 企业租户需管理员同意 | 导出文件 ✅；Graph / MCP 计划 | [microsoft/mcp](https://github.com/microsoft/mcp) |
| **短信：Android** | 导出文件：SMS Backup & Restore xml；通用 csv | 导出工具第三方，格式公开 | ✅ | 无 | 验证码、银行短信：入库前整条脱敏 | ✅ 已实现 | SMS Backup & Restore（Google Play） |
| **短信：iPhone** | 计划：iTunes / Finder **本地未加密备份**里的 `sms.db`（备份目录中文件名为 `3d0d7e5fb2ce288813306e4d4636395e047a3d28`），SQLite 只读打开 | ❌ 无官方 API；读本地备份 | ✅（只读打开备份副本） | 无（加密备份需用户密码，暂不支持） | 备份含全部短信 / iMessage；只读副本、不碰原备份 | 计划 | Apple：备份 iPhone |
| **日历：ICS** | 计划：.ics 文件（各家日历都能导出） | ✅ 标准格式 | ✅ | 无 | 低 | 计划 | RFC 5545 |
| 日历：CalDAV | 计划：CalDAV 只读（iCloud、Nextcloud、飞书日历等） | ✅ 标准协议 | ✅ | 应用专用密码 | 凭据同邮箱 | 计划 | RFC 4791 |
| 日历：Google / Outlook | 计划：Google Calendar API（`calendar.readonly`）/ Microsoft Graph（`Calendars.Read`） | ✅ | ✅ | OAuth | OAuth 应用审核 | 计划 | — |
| **通讯录：vCard** | **导出文件** .vcf（iPhone、Android、Google、Outlook 都能导出）；用于**人物别名合并**（微信备注 / 短信联系人 / 邮件显示名并成一个人） | ✅ 标准格式 | ✅ | 无 | 电话只存哈希、邮箱只存打码；不会把整本通讯录灌进人物列表 | ✅ 已实现 | RFC 6350 |
| **笔记：Obsidian** | 计划：直接读 vault 里的 Markdown（本地文件）；sas 已能**写出**日报到 vault | ✅ 本地文件 | ✅ | 无 | 低 | 输出 ✅；读取计划 | — |
| 笔记：Notion | 计划：官方 MCP / Notion API（只读 integration） | ✅ 官方 | ✅ | Integration token（只授权指定页面） | 授权范围 | 计划 | [makenotion/notion-mcp-server](https://github.com/makenotion/notion-mcp-server) |
| 笔记：Apple 备忘录 | 计划：本机 `NoteStore.sqlite` 只读（macOS，需「完全磁盘访问」），或手动导出 | ❌ 无官方 API | ✅ | 系统权限 | 格式为私有 protobuf，系统升级可能失效 | 计划 | — |
| **浏览器历史** | 计划：Chrome `History`、Safari `History.db`（本机 SQLite，复制副本后只读） | ❌ 本地数据库 | ✅ | macOS 读 Safari 需完全磁盘访问 | 敏感度高：默认只取域名 + 标题，不取完整 URL 参数 | 计划 | — |
| **本地文件 / 文档** | 计划：指定目录的 Markdown / PDF / Office；可交给 OpenViking `add_resource` 建 L0/L1 摘要 | ✅ 本地文件 | ✅ | 无 | 别把整个磁盘丢进来；按目录白名单 | 计划 | [ADR 0001](adr/0001-memory-backend.md) |
| 小红书 | 不默认接入；如需，只考虑读取**自己的**收藏 / 笔记 | ❌ 无开放的个人数据 API；社区 MCP 为非官方 | 视实现 | 登录 cookie | **非官方、有封号风险**；违反平台条款的可能性高 | 不做（仅记录） | [xpzouying/xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp)（非官方） |
| 抖音 | 不接入 | 开放平台面向企业 / 创作者经营数据，不提供个人私信 / 浏览历史 | — | — | 同上 | 不做 | — |

## 为什么不是「全部走 MCP」

- MCP server 只是把**已有的官方 API**包装成 Agent 工具。没有官方 API 的数据（个人微信、iPhone 短信、Apple 备忘录），也就没有可靠的官方 MCP；社区 MCP 往往靠逆向或模拟登录，风险和直接用非官方工具一样。
- 多数官方 MCP 同时带**写操作**（发消息、建日程）。sas 的原则是只读，所以即使接 MCP，也只调用读类工具，写类工具不注册。
- 个人语境需要的是**全量、可增量、可回溯**的数据落到本地；MCP 更适合 Agent 临时查一下。sas 的做法是：本地 SQLite 作为真源，需要时再通过 MCP / OpenViking 把**脱敏后的**记忆暴露给其他 Agent。

## 已实现 connector 速查

| connector | 命令 | 说明 |
|-----------|------|------|
| `wechat_txt` / `wechat_csv` | `sas ingest <导出目录> -r --me 你的昵称` | WeChatMsg / 留痕导出 |
| `email_eml` / `email_mbox` | `sas ingest <目录或 .mbox>` | 客户端导出、Gmail Takeout |
| **`imap`** | `SAS_IMAP_PASSWORD=<授权码> sas imap --user you@qq.com --provider qq` | 只读、增量、不标已读 |
| `sms_xml` / `sms_csv` | `sas ingest sms-backup.xml` | Android |
| `dingtalk` | `sas ingest 钉钉.csv --source dingtalk` | 导出 / 整理的 csv、xlsx |
| **`vcard`** | `sas ingest contacts.vcf` | 人物别名合并 |
| `events` | `sas ingest events.jsonl` | 已是 ChannelEvent 的数据 |

格式细节与已知坑见 [connectors.md](connectors.md)。
