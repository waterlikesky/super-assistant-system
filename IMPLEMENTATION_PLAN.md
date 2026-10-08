# 里程碑（已完成 / 下一步）

> 规则：每条都有可运行的验收；没跑通的不写成已完成。验收统一是 `python3 -m pytest -q` 全绿 + README 快速开始可复制运行。

## 已完成

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M0（6258902） | 统一 ChannelEvent schema、假数据演示、隐私立场 | 已被 M2 取代 |
| M1（eab70f8） | 单层 `.eml` 目录只读摄入 + 脱敏 | 解析器迁入 `sas/connectors/email.py`，断言迁到 `tests/test_email.py` |
| **M2 本地 MVP**（2026-10-07，分支 `claude/optimize-20261007`） | 可安装 `sas` 包；8 种导出格式 connector（微信 txt/csv、eml、mbox、短信 xml/csv、钉钉 csv/xlsx、ChannelEvent json）；入库前脱敏（手机/验证码/身份证/银行卡/邮箱/单号）；sqlite-utils + FTS5 trigram 中文检索；文件指纹增量 + 消息 id 去重 | `tests/test_connectors.py`、`test_redact.py`、`test_store_ingest.py` |
| **M3 记忆闭环 v1**（同上） | 规则抽取 承诺/请求/偏好/事实/约定 + 截止日期；noisy-OR 合并、半衰期衰减、偏好矛盾降权、后续消息自动关闭承诺；人物聚合；`MemoryBackend` 接口 + mem0 可选镜像 | `tests/test_memory.py` |
| **M4 CLI** | `ingest / ask / search / people / person / todos / done / digest / stats / connectors`；ask 离线带出处；digest 输出 Obsidian Markdown；LLM（Ollama / simonw/llm）与语义检索（sqlite-vec）可选，云端需显式开关 | `tests/test_cli.py`、`test_embed.py` |

## 下一步（按优先级）

1. **在真实导出上校准规则**（维护者用自己的 WeChatMsg / Takeout 导出跑一周，记录误报/漏报到 `docs/eval/`，不提交原文）。验收：误报样例转成虚构测试用例。
2. **LLM 辅助抽取**：规则先抽，模型只补漏、只看脱敏片段，输出必须引用 event id；默认关闭。验收：用假后端的测试证明无模型时行为不变、有模型时不越权。
3. **人物别名合并**：同一人在微信备注、邮件显示名、短信通讯录名不同 → `sas person merge A B`，写入 people.aliases。
4. **定时摄入**：`sas watch <目录>` 或 cron 示例；导出目录有新文件就增量摄入并生成当日 digest。
5. **MCP 接口**：把 ask / person / todos 暴露为只读 MCP 工具（参考 mem0-mcp），给 OpenClaw / Claude 当记忆层。
6. 语义检索实测：装 `.[llm,vec]` + 本地 embedding 模型（如 sentence-transformers 插件），补端到端测试。

## 不做

微信解密 / Hook / 协议号；任何发送或自动回复；默认上传全文；企业系统 API 集成（钉钉开放平台、邮件 OAuth 留待有明确需求时单独评估最小权限方案）。
