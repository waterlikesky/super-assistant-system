# 批判性审计（2026-10-07，重构前 `d734c73`）

对照产品意图：「只读摄入多渠道 → 统一事件 → 本地可演进记忆 → 越用越聪明；出站关闭、本地优先」。

## 结论一句话

文档写了 ~900 行，能用的代码只有一个 `.eml` 解析器和一个脱敏函数。用户今天拿它**什么也做不了**：没有存储、没有检索、没有记忆、没有能问的命令。

## 哪里烂

| # | 问题 | 证据 | 为什么致命 |
|---|------|------|-----------|
| 1 | **没有持久化** | `memory/store.py` 是进程内 list；`agent/ask.py` 每次 new 一个空 store，永远回答「不知道」 | 「记忆」「越用越聪明」无从谈起 |
| 2 | **没有检索** | `InMemoryStore.search` 是子串匹配；无 FTS，中文无分词 | 「我上次和老王聊了什么」答不了 |
| 3 | **记忆抽取是演示** | `naive_extract_facts` 只认 `meet/见面/约/项目`，subject 写死 `user`/`project`，同 subject+predicate 直接覆盖 | 没有人物、承诺、偏好；没有置信度演进与衰减 |
| 4 | **渠道只有 1/4** | 只有 `.eml` 单层目录；微信/短信/钉钉为零，`wechat_local`/`email_oauth` 是只会抛异常的空壳 | 产品核心卖点（微信语境）完全缺失 |
| 5 | **无增量、无去重** | `file_export_run` 每次覆盖 JSONL | 「持续定期摄入」（borrow-list §4 纪钟帖）做不到 |
| 6 | **不可安装** | 无 `pyproject.toml`；入口散在 `python -m ingest.xxx` | 用户要记 3 个模块路径 |
| 7 | **文档 ≫ 代码** | README 182 行、计划 200 行、两份 collab、v0/pitfalls/scys/landscape 四份调研，内容大量重复；GROK_COLLAB 里塞了整段提示词 | 读者找不到「怎么用」；文档状态与代码不一致（GROK_COLLAB 仍说「仅 M0」） |
| 8 | **流程过度** | 「一次只做一种输入」被执行成 M1 只做 `.eml`，mbox 都排除在外 | 每个里程碑都只交付管道一小段，端到端从未闭合 |
| 9 | 脱敏覆盖不全 | 只有手机号/验证码/邮箱/快递单；无身份证、银行卡；`验证码是 123456` 这种写法靠 sensitivity 兜底 | 入库前漏敏感号码 |

## 值得保留的

- `connectors/file_export.py` 的 `.eml` 解析（纯文本优先、HTML 降级、签名剥离、附件只记元数据、稳定 id、坏日期拒收）——质量不错，整体迁入新包。
- `ingest/redact.py` 的思路（入库前脱敏、验证码整条替换）——扩充后沿用。
- `tests/test_file_export.py` 的断言（明文不落盘、坏文件跳过、id 稳定、不开 socket、数据目录 gitignore）——迁移到新入口继续守住。
- `ChannelEvent` schema 的骨架与「只读、出站默认关」的隐私立场。

## 怎么改

1. **先闭环，再扩面**：一个可安装的 `sas` 命令，端到端跑通 `ingest → 存储 → 记忆 → ask/people/todos/digest`。
2. **按 borrow-list §5 借轮子**：存储与 FTS5 用 `sqlite-utils`（trigram 分词器解决中文检索）；邮件用标准库 `mailbox`/`email`；记忆层 `MemoryBackend` 接口，默认本地规则 + SQLite，mem0 作可选适配器；LLM 走 `llm` 库或 Ollama HTTP，默认离线；微信只吃 WeChatMsg 等工具的导出物。
3. **四个渠道各一个导出格式 connector**，统一注册表；稳定 id + 文件指纹 → 增量与去重。
4. **记忆有生命周期**：人物 / 事实 / 承诺 / 待办 / 偏好；重复观测合并提高置信度，按半衰期衰减，承诺可被后续消息自动关闭。
5. **文档砍到能读完**：一页产品定义、一份 README、一份路线图；调研合并为 borrow-list + 一份坑清单；一次性提示词删除。
