# 导出格式与接入坑

sas 只读**你自己导出的文件**。`sas connectors` 列出全部格式；自动识别不准时用 `--source` 强制。

## 支持的格式

| connector | 来源 | 识别方式 | 要点 |
|-----------|------|---------|------|
| `wechat_txt` | WeChatMsg / 留痕「导出 txt」 | `.txt` 且有 `2026-10-05 21:40:12 昵称` 抬头行（也接受「昵称 时间」） | 文件名 = 会话名；多个非「我」发言人 → 群聊；用 `--me 昵称` 标出自己 |
| `wechat_csv` | WeChatMsg / 留痕「导出 csv」 | 表头含 `StrContent` / `IsSender` | 只保留文本（Type 1/49）；`IsSender=1` 即我发出 |
| `email_eml` | 客户端「另存为 .eml」 | `.eml` | 纯文本优先、HTML 去标签；`-- ` 后签名丢弃；附件只记文件名与大小；缺/坏 Date、空正文跳过 |
| `email_mbox` | Gmail Takeout、Thunderbird | `.mbox` 或以 `From ` 开头的无后缀文件 | `X-Gmail-Labels: Sent` 或 `me_emails` 判断为我发出；`Re:/回复:` 归并到同一会话 |
| `sms_xml` | Android「SMS Backup & Restore」 | `.xml` 含 `<smses` | `type=2` / `msg_box=2` 为我发出；mms 只取文本部分；号码入库前换成哈希 |
| `sms_csv` | 任意短信 csv | 表头有号码列 + 内容列 | 列名别名：号码/address、内容/body、时间/date、类型/type（1/2、接收/发送）、联系人/contact_name |
| `dingtalk` | 钉钉导出或手工整理 | `.csv` 表头含 时间 + 发送人 + 内容；`.xlsx` 文件名含「钉钉/dingtalk」 | 可选「会话」列，否则用文件名；xlsx 需 `pip install '.[xlsx]'` |
| `vcard` | 通讯录 `.vcf`（3.0 / 4.0 / 2.1 QUOTED-PRINTABLE） | `.vcf` | 不产生消息；按姓名 / 昵称 / 电话哈希 / 打码邮箱把人物合并，别名进 `people.aliases` |
| `imap`（命令 `sas imap`） | 任意 IMAP 邮箱（QQ / 163 / Gmail 预设） | 不走文件识别 | `EXAMINE` + `BODY.PEEK[]`，写命令在代码层被拒；按 UIDVALIDITY + UID 增量；密码只读 `SAS_IMAP_PASSWORD` 或 keyring |
| `events` | 已是 ChannelEvent 的 `.json/.jsonl` | 含 `"channel"` 与 `"content_text"` | 用于对接其他工具的产出 |

通用规则：目录默认只读这一层，`-r` 才递归；点开头的文件/目录一律跳过；解析失败的单条记录打印 `skipped <位置>: <原因>` 后跳过，不写半条。无时区的时间按 `SAS_TZ`（默认 Asia/Shanghai）解释。

**加新格式**：在 `sas/connectors/` 写一个 `Connector` 子类（`sniff` 判断能否处理、`parse` 产出 ChannelEvent 字典），在 `sas/connectors/__init__.py` 注册，再加一个虚构夹具和测试。connector 不得有任何发送或联网能力（注册时检查 `read_only`）。

## 已知坑与对策

| 渠道 | 坑 | 对策 |
|------|----|------|
| 微信 | 没有官方个人数据 API；本机解密绑定客户端版本，chatlog / PyWxDump 已因官方函件删库 | 只吃导出文件；解密、取钥、Hook 不进本仓库 |
| 微信 | 导出 txt 里自己的昵称是真实昵称，不是「我」 | `--me` 或 `sas.toml` 里 `me = [...]` |
| 微信 / 钉钉 | 群里「你能…吗」可能是问别人 | 群聊只把「大家/各位」或点名我的请求算作找我 |
| 邮件 | HTML、签名、附件污染检索 | 纯文本优先、剥签名、附件只记元数据 |
| 邮件 / 短信 | 银行、快递、验证码等通知刷屏 | 服务号（短号、106/95 开头、noreply/notice 邮箱）不算人、不进待回复；含验证码整条替换 |
| 钉钉 | 企业数据受公司政策约束 | 先确认授权；可用单独的 `--db` 与个人数据物理隔离 |
| 通用 | 一次导入全部历史、全塞给模型 | 增量摄入 + 本地检索 Top-K；模型只看命中的脱敏片段 |
| 通用 | 重复导出、导出范围重叠 | 文件指纹跳过未变文件；消息稳定 id 去重 |

## 接入新渠道前检查

- [ ] 只读？没有任何发送路径？
- [ ] 有没有官方 / 合规的导出方式？没有就不做。
- [ ] 能映射到 ChannelEvent？脱敏规则覆盖这个渠道特有的号码？
- [ ] 失败时数据仍只在本机？
- [ ] 有虚构夹具 + 测试？
