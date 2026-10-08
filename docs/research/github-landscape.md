# GitHub / 开源景观

> 检索时间：2026-10-07（PT）。stars 为当时近似值，会变动。  
> 原则：优先可自托管、隐私可控；微信相关默认作**可选参考**，不默认依赖。

---

## 1. 记忆层（Memory）

| 仓库 | Stars（约） | 适用场景 | 局限 / 隐私 |
|------|-------------|----------|-------------|
| [mem0ai/mem0](https://github.com/mem0ai/mem0) | ~66k | Agent 事实抽取与长期记忆；可挂到自建 Agent | 云服务会上传；**请自托管**；需自己做脱敏与 scope |
| [letta-ai/letta](https://github.com/letta-ai/letta) / [letta-code](https://github.com/letta-ai/letta-code) | Letta 系数千级 | 原 MemGPT：有状态 Agent 运行时，记忆分页更「像人」 | 更重；学习成本高；对本项目 M2 可选，非必须 |
| [coleam00/mcp-mem0](https://github.com/coleam00/mcp-mem0) | ~0.7k | 把 Mem0 暴露为 MCP | 依赖 Mem0 部署方式 |
| [NirDiamant/Agent_Memory_Techniques](https://github.com/NirDiamant/Agent_Memory_Techniques) | ~1k | 教程/notebook：buffer、向量、图谱、Mem0/Letta/Zep | 教学用，非产品 |
| [TeleAI-UAGI/telemem](https://github.com/TeleAI-UAGI/telemem) | ~0.5k | Mem0 风格替代、去重与长对话 | 生态较新，需自评稳定性 |

**本仓库倾向**：M2 先 **SQLite + 本地向量（或自托管 Mem0）**；Letta 留给「需要完整 stateful runtime」时再评估。

---

## 2. 微信相关（高脆弱 / 合规敏感）

| 仓库 / 工具 | 说明 | 局限 |
|-------------|------|------|
| [chenchen1010/wechat-chat-decrypt-skill](https://github.com/chenchen1010/wechat-chat-decrypt-skill) | 生财陈钟琦：本机解密 → 给 Coding Agent 读 | 绑定微信版本；需降级；仅本地 |
| robbin/wechat-exporter 等 | Mac 解密导出 skill（社区常见） | 版本漂移即失效 |
| ydotdog/wechat-export-macos | macOS 导出 | 同上 |
| yichen-wechat-local-vault / huohuoer/wechat-cli | 苏格文：只读本机库 | **DMCA 下架风险**、版本绑定；新版微信常挂 |
| [tzwkb/wechat-decrypt](https://github.com/tzwkb/wechat-decrypt) | 2026-10-07 仍可见：本机密钥解密微信 4.x，只读查询 | 要设备密钥；macOS / Windows 路径不同；不进本仓库，不作 M1 |
| [zhayujie/CowAgent](https://github.com/zhayujie/CowAgent)（原 chatgpt-on-wechat 系） | ~47k；多渠道个人助理 / Agent Harness | 偏「机器人出站」；账号风控与条款风险高 |
| [fuergaosi233/wechat-chatgpt](https://github.com/fuergaosi233/wechat-chatgpt) 等 | Wechaty 等协议接 ChatGPT | 协议号/网页号不稳定，**不推荐作个人数据底座** |

**结论**：微信路径只做 **可选只读插件**；文档写清版本与风险；默认关闭出站。

---

## 3. 多渠道编排 / 助理产品

| 名称 | 类型 | 适用 | 局限 |
|------|------|------|------|
| [langbot-app/LangBot](https://github.com/langbot-app/LangBot) | 开源 ~18k | 企微/公众号/飞书/钉钉/Discord 等 Agent IM 平台 | 偏 bot 出站；企业号权限与审核 |
| [openclaw/openclaw](https://github.com/openclaw/openclaw) | 开源（stars 极高） | 多平台「真正做事」的个人 AI；own-your-data | 体量大；自建需裁剪；国内部署见生财手册 |
| Chatwoot | 开源客服 inbox | 邮件等多渠道统一收件 | 客服场景；非个人记忆进化 |
| n8n / Make | 工作流 | LLM + 连接器编排 | 记忆与「越用越聪明」需自建节点 |
| LinkAI | **商业**超级助理 | 微信/钉钉/飞书等一站式 | 数据在第三方；适合「买而不是造」；本仓库走自建 |
| LangGraph / LangChain memory | 框架 | 图编排 + checkpointer | 是积木不是成品；隐私仍取决于你部署何处 |

---

## 4. 推荐自建技术路线（本仓库）

```
统一事件 Schema
    + 本地记忆（Mem0 自托管 或 SQLite/向量 + 事实表）
    + M1 先做用户自己导出的一层 .eml 目录；邮件 OAuth 排在这条验收之后
    + 微信本机只读作可选插件（版本坑标注）
    + 出站默认关闭
```

**不要做的事**

- 默认把完整微信聊天上传云端 LLM
- 以协议号机器人作为「数据打通」的第一路径
- 把社区 PDF/全量聊天无筛选灌进向量库

**可以借鉴但不 fork 全家桶**

- OpenClaw / LangBot：渠道适配思路
- Mem0：记忆 API 形状（add / search / 用户 scope）
- Chatwoot：多渠道统一 inbox 的数据模型灵感

---

## 5. stars 快照备注

| 项目 | 约 stars（2026-10-07） |
|------|------------------------|
| mem0ai/mem0 | 66k+ |
| openclaw/openclaw | 极高（检索显示异常大，以官方页为准） |
| zhayujie/CowAgent | ~47k |
| langbot-app/LangBot | ~18k |
| letta-ai/letta-code | ~3.5k |
| n8n-io/n8n | 业界常用（工作流） |

数字仅供横向对比，选型以 **隐私、可控、任务匹配** 为准。
