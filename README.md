# 个人超级助理系统（Super Assistant System）

> 目标：打通微信 / 钉钉 / 邮件 / 短信等个人数据，本地优先记忆，越用越聪明。  
> 现状：**研究 + 架构 + 实现骨架**（M0）。尚未实现真实渠道接入或记忆闭环——请勿夸大能力。  
> 协作：与 GPT / Codex / Claude 按 `GPT_COLLAB.md` + `IMPLEMENTATION_PLAN.md` 分阶段推进；Grok CLI 入口见 `GROK_COLLAB.md`（Claude↔Grok）。

仓库：https://github.com/waterlikesky/super-assistant-system

---

## 1. 问题陈述

把微信、钉钉、邮件、短信「喂给 Agent」时，常见失败模式：

| 痛点 | 表现 |
|------|------|
| 渠道封闭 | 微信个人号几乎无合法全量 API；聊天在本地加密库，不是 CRM |
| 一股脑投喂 | 把 PDF / 全量聊天 / 课程全扔进知识库 → 噪声大、检索差、成本高 |
| 版本与合规 | 本机解密依赖特定微信版本；降级/关更新；DMCA 下架风险 |
| 隐私外泄 | 完整聊天默认上传第三方模型 = 高风险 |
| 缺少统一模型 | 各渠道字段不一，无法做跨渠道事实抽取与记忆进化 |
| 出站失控 | 「机器人」一上就自动回复，风控与误发 |

生财社区相关实践见 [`docs/research/scys-findings.md`](docs/research/scys-findings.md)；开源景观见 [`docs/research/github-landscape.md`](docs/research/github-landscape.md)；渠道坑见 [`docs/problems/channel-ingestion-pitfalls.md`](docs/problems/channel-ingestion-pitfalls.md)。

---

## 2. 调研结论（摘要）

1. **真实沟通环境（微信/飞书/钉钉）比手工投喂更能代表「你」**，但微信本机解密有版本坑与风控，必须本地、只读、可选。
2. **不要全量扔进知识库**（枕棠等）：先按任务整理真正需要的信息，再沉淀事实。
3. **「越用越聪明」≠ 一次 ingest 全量聊天**，而是：定时摘要 → 事实抽取 → 记忆写入 → 检索增强。
4. **合规清晰的渠道先做**（邮件 OAuth / 导出文件）；微信本机只读作可选插件；出站默认关闭。
5. 可复用开源：Mem0（记忆层）、LangBot / n8n / Chatwoot（渠道编排参考）、OpenClaw（多渠道助理实践）、wechat 本机解密 skill（可选）。

---

## 3. 架构草图（v0）

详见 [`docs/architecture/v0.md`](docs/architecture/v0.md)。

```
接入层（只读 connectors）
  微信本机解密 | 钉钉 API | 邮件 OAuth | 短信/导出文件
        ↓
统一事件 / 消息 Schema（schemas/）
        ↓
本地记忆层：向量检索 + 结构化事实 + 脱敏
        ↓
Agent 编排（问答 / 摘要 / 提醒；出站默认关）
```

**隐私边界**：本地优先；禁止默认上传完整聊天；密钥不进 git；企业钉钉数据与个人数据隔离。

---

## 4. 阶段计划

| 里程碑 | 内容 | 状态 |
|--------|------|------|
| **M0** | 仓库骨架、统一 schema、假数据 ingest 演示 | ✅ 本仓库 |
| **M1** | 单一合规渠道只读摄入（优先邮件 OAuth 或导出文件） | 待做 |
| **M2** | 统一记忆层（Mem0 自托管或 SQLite+向量）+ 脱敏 | 待做 |
| **M3** | 「越用越聪明」闭环（摘要→事实→写入→检索） | 待做 |
| **可选** | 微信本机只读插件（版本坑标注）；钉钉；出站需显式开关 | 待评估 |

完整任务拆解：[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)。

---

## 5. 与 GPT / Claude / Grok 协作方式

- 编码 Agent（GPT / Codex / Claude）：[`GPT_COLLAB.md`](GPT_COLLAB.md)
- Grok CLI（产品定义、验收、审偏离）：[`GROK_COLLAB.md`](GROK_COLLAB.md) — 内含可整段粘贴的提示词

原则：

- 一次一个里程碑 / PR；验收标准写在计划里
- 诚实归因：不伪造「已跑通 Claude / 已接入微信」
- 密钥与原始聊天永不进仓库
- Claude↔Grok：实现归 Claude；「超级助理是什么」与验收文案归 Grok

---

## 6. 目录结构

```
connectors/     # 各渠道只读适配器（M0 仅为接口占位）
ingest/         # 摄入管道：规范化 → 脱敏 → 落盘
memory/         # 记忆层接口（事实 / 向量）
agent/          # Agent 编排占位
schemas/        # 统一事件 JSON Schema
fixtures/       # 假数据（无真实隐私）
docs/           # 研究、架构、坑
```

快速演示（假数据，无需 API Key）：

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m ingest.demo_run
```

---

## 7. 免责声明

- 微信个人聊天记录解密可能违反微信服务条款，存在账号与法律风险；本项目默认**不启用**微信 connector。
- 企业钉钉/邮件数据可能受公司政策约束，请先取得授权。
- 本仓库文档引用生财有术帖子仅供个人学习研究，版权归原作者。

---

## 8. License

MIT（代码骨架）。文档中的第三方项目各自遵循其许可证。
