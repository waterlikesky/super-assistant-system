# Borrow list：先借成熟轮子，再写自己的胶水

> 调研日期：2026-10-07（PT）。数据来自 GitHub API（stars / license / 最近 push）和生财有术 MCP 检索。
> 整理者：Grok Bot（executor），用作 Claude 重构的输入。原则：**能依赖就依赖，能包一层就包一层，只在「个人语境 + 隐私边界」这层自己写。**

## 1. 结论速览

| 层 | 决定 | 选型 | 理由 |
|----|------|------|------|
| 存储 + 全文检索 | **依赖** | [simonw/sqlite-utils](https://github.com/simonw/sqlite-utils)（2.2k★，Apache-2.0，活跃） | upsert、建表、`enable_fts`（FTS5）一行搞定，不手写 SQL 迁移 |
| 浏览 UI（可选） | **依赖（可选）** | [simonw/datasette](https://github.com/simonw/datasette)（11.5k★，Apache-2.0） | 本地 `datasette sas.db` 直接浏览/搜索，不自己写前端 |
| 向量检索（可选） | **依赖（可选）** | [asg017/sqlite-vec](https://github.com/asg017/sqlite-vec)（8.2k★，Apache-2.0） | 同一个 SQLite 文件里加向量，不引入独立向量库 |
| LLM 后端（可选） | **依赖（可选）** | [simonw/llm](https://github.com/simonw/llm)（12.6k★，Apache-2.0）+ [ollama](https://github.com/ollama/ollama)（182k★，MIT） | 一个接口接本地 Ollama / 云模型 / embeddings；默认离线规则抽取 |
| 长期记忆 / 上下文库 | **镜像适配器（主推）** | [volcengine/OpenViking](https://github.com/volcengine/OpenViking)（39.4k★，主项目 **AGPL-3.0**；`openviking-sdk` 轻量 HTTP 客户端） | `viking://` 文件系统 + L0/L1/L2 分层；记忆、画像、日报写成 Markdown 由它建摘要与向量。**只通过 HTTP 调用用户自托管的 server，不含其代码**。决策见 [ADR 0001](../adr/0001-memory-backend.md) |
| 团队级记忆 Hub | **镜像适配器（可选）** | [TencentCloud/TencentDB-Agent-Memory](https://github.com/TencentCloud/TencentDB-Agent-Memory)（27.8k★，MIT） | L0→L3 分层 + BM25/向量/RRF；三服务 + Node ≥22.16 + LLM，偏团队；Python SDK 不在 PyPI，包内 v2/v3 并存，适配器只用 v3 |
| 长期记忆 / 事实抽取 | **适配器（可选后端）** | [mem0ai/mem0](https://github.com/mem0ai/mem0)（66.8k★，Apache-2.0，今天仍在 push；PyPI `mem0ai` 2.2.1） | 成熟的 ADD/UPDATE/DELETE 事实记忆；保留为可选镜像，不再主推（默认配置走 OpenAI，记忆是黑盒事实列表） |
| 用户画像记忆（参考） | 参考 | [memodb-io/memobase](https://github.com/memodb-io/memobase)（2.9k★，Apache-2.0） | profile 槽位（人/偏好/事件）设计参考 |
| 时间知识图谱（后续） | 参考，M3 以后 | [getzep/graphiti](https://github.com/getzep/graphiti)（31.5k★，Apache-2.0）、[topoteretes/cognee](https://github.com/topoteretes/cognee)（31.6k★） | 「谁在什么时候说了什么」的时序关系；MVP 不引入 |
| 自进化 agent 记忆架构 | 参考 | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)（252k★，MIT）、[letta-ai/letta](https://github.com/letta-ai/letta)（25k★，Apache-2.0） | Hermes：会话 / 持久 / 技能三层记忆 + SQLite FTS5 按需检索；Letta：core vs archival memory。我们照这个分层 |
| 数据源模块化 | 参考 | [karlicoss/HPI](https://github.com/karlicoss/HPI)（1.6k★，MIT）、[dogsheep](https://github.com/dogsheep)、[simonw/mbox-to-sqlite](https://github.com/simonw/mbox-to-sqlite) | 「一个数据源一个模块 → SQLite」的成熟模式；邮件解析直接用 Python 标准库 `mailbox` / `email` |
| 第二大脑形态 | 参考 | [khoj-ai/khoj](https://github.com/khoj-ai/khoj)（37.6k★，**AGPL**）、[basicmachines-co/basic-memory](https://github.com/basicmachines-co/basic-memory)（4.1k★，**AGPL**）、[thedotmack/claude-mem](https://github.com/thedotmack/claude-mem)（97.7k★，Apache-2.0） | 只借思路（Markdown 可读记忆、Obsidian 输出），**不拷 AGPL 代码** |

## 2. 微信：只吃导出，不自己做解密

| 项目 | 状态 | 用法 |
|------|------|------|
| [LC044/WeChatMsg](https://github.com/LC044/WeChatMsg)（MemoTrace 留痕，42k★，无 license） | 仍在 | 用户自己用它导出 txt/csv/html → `sas ingest --source wechat_export` 吃导出文件 |
| [Rion-Wu-tech/wechat-intelligence-hub](https://github.com/Rion-Wu-tech/wechat-intelligence-hub)（2.6k★，**AGPL**，9 月仍在更新） | 活跃；含只读 `wechat-cli` / `rion-wechat-reader` | 最接近本项目的「微信情报库」（日报、待回复、承诺、商机）。作为**上游只读来源**：吃它的导出 JSON；产品形态参考，不拷代码 |
| [chenchen1010/wechat-chat-decrypt-skill](https://github.com/chenchen1010/wechat-chat-decrypt-skill)（Apache-2.0） | 活跃；只验证特定微信版本（Win 4.1.8.101 / Mac 4.1.8） | 用户本人授权、本机解密并导出 Markdown，再交给本项目摄入；本仓库不调用解密 |
| [sjzar/chatlog](https://github.com/sjzar/chatlog)（9.2k★） | **2025-10-20 收到微信官方函件后删除全部代码** | 不依赖。生财里大量教程（欢乐马、阿紫、Orime、HEXIN）基于它，旧副本有合规风险 |
| [xaoyaoo/PyWxDump](https://github.com/xaoyaoo/PyWxDump) | 已删库 | 不依赖 |

**结论**：本仓库只定义「导出文件 → ChannelEvent」的 connector；解密、取钥、Hook 一律不碰（版本坑 + 风控 + 法律风险，chatlog / PyWxDump 已是前车之鉴）。

## 3. 渠道编排 / 出站（MVP 不做，出站默认关闭）

- [openclaw/openclaw](https://github.com/openclaw/openclaw)（392k★，MIT）：多平台个人 agent；后续可把本仓库做成它的「记忆/语境」技能或 MCP。
- [langbot-app/LangBot](https://github.com/langbot-app/LangBot)（18k★，Apache-2.0）、[chatwoot/chatwoot](https://github.com/chatwoot/chatwoot)（37.6k★）：IM 机器人 / 客服收件箱；出站风控大，MVP 不接。
- [mem0ai/mem0-mcp](https://github.com/mem0ai/mem0-mcp)：后续暴露 MCP 时参考。

## 4. 生财有术圈友的实战与坑

| 帖子 | 借鉴点 |
|------|--------|
| 纪钟《如何构建更懂自己的 AI 和生财主页？》https://scys.com/articleDetail/xq_topic/45548541854245848 | 破解接入微信有风控；要「持续定期获取聊天记录」→ 增量摄入 + 去重 |
| 盟主君《10 分钟雇个带永久记忆的赛博管家》（Hermes）https://scys.com/articleDetail/xq_topic/82255514414254242 | 聊天进本地 SQLite + FTS5，按需检索，不把历史全塞上下文；三层记忆 |
| 千寻《7449 条实战经验总结：Hermes Agent》https://scys.com/articleDetail/xq_topic/45544585512222418 | 本地负责提取微信等脏活，云端负责自动化 → 本地优先、云端只拿摘要 |
| 枕棠《Agent 员工军团》https://scys.com/articleDetail/xq_topic/82258825454528882 | 别把所有聊天/PDF 全扔进知识库；按任务沉淀需要的信息 |
| 欢乐马《我用 ChatLog 做了 6 件事》https://scys.com/articleDetail/xq_topic/4845218242485128 | 聊天记录比日记真实：人物画像、关系、复盘是高价值用例 |
| 阿紫《零基础开发微信群聊精华总结工具》https://scys.com/articleDetail/xq_topic/14588242225258522 / Orime《航海群聊总结教程》https://scys.com/articleDetail/xq_topic/1524112555128122 | 群聊日报是刚需；MCP 一句话总结「容易丢内容」→ 先确定性抽取再交给模型；Mac 需关 SIP = 高风险，不进默认路径 |
| HEXIN《一人公司 57 天》https://scys.com/articleDetail/xq_topic/45544415448544828 | 微信体系「只进不出」；好友关系/互动统计是实际需求 |
| colaandice《Workbuddy 入门》https://scys.com/articleDetail/xq_topic/22258815142412581 | 官方/半官方转发聊天给 agent 的路径可作为低风险导入方式 |
| 亦仁《Agent 与 FDE 的实践与观察》https://scys.com/articleDetail/xq_topic/55522414484184224 | AI 第二大脑结合 Obsidian：日报/画像输出成 Markdown，进用户自己的笔记库 |

## 5. 对 MVP 的直接要求

1. 依赖 `sqlite-utils` 做存储与 FTS5；不手写 ORM / 迁移框架。
2. 邮件用标准库 `mailbox` / `email`；不自己写 MIME 解析。
3. 记忆层定义 `MemoryBackend` 接口：默认本地规则 + SQLite（永远是真源）；外部后端只做镜像增强——OpenViking（主推）、TDAM、mem0，缺包或 server 不可达时优雅降级（ADR 0001）。
4. LLM 可选，经 `llm` 库或 Ollama HTTP；默认离线可用。
5. 微信只吃 WeChatMsg / wechat-intelligence-hub / decrypt-skill 的导出物；不碰解密。
6. 输出可落 Markdown（Obsidian 友好）与 `datasette` 可浏览的 `sas.db`。

## 6. 早期调研补遗（2026-10-07 由 scys-findings.md、github-landscape.md 合并而来）

生财有术帖（§4 之外）：

| 帖子 | entityId | 一句话 |
|------|----------|--------|
| 陈钟琦《解密微信聊天记录》保姆级教程 | `82255448142454542` | 本机解密交给 Coding Agent；需降级到特定微信版本并关自动更新 → 本仓库不走这条路 |
| 苏格《把 AI 接入微信：个人知识库》 | `45544211552415428` | 只读本机库的 wechat-cli；有 DMCA 下架与版本风险；任务要窄 |
| 浅笑《OpenClaw 完全实战手册》 | `14588481154454282` | 多渠道助理已成熟，自建应专注记忆 + 隐私 + 统一 schema |
| 《100 个 Agent 案例》 | `45548881511411458` | LangBot / Chatwoot 可作出站与统一收件箱参考 |
| 亦仁：AI 爽用法 / 超级助理系统 | `45548581185112528` | 「打通所有数据、越用越聪明」——本仓库灵感来源 |
| 《把业务流程做成 AI Agent 员工》 | `14422114455242422` | 知识库是文件集合不是永久记忆；大库要检索而非全塞上下文 |

其他看过但不采用：LinkAI（商业托管，数据在第三方）、n8n / Make（工作流编排，记忆需自建）、CowAgent / Wechaty 系协议号机器人（偏出站，账号风控高，不作数据底座）、[tzwkb/wechat-decrypt](https://github.com/tzwkb/wechat-decrypt)（本机解密，同 §2 结论）、LangGraph memory（积木而非成品）。
