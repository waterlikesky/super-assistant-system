# 实现计划（可交给 GPT / Codex）

> 原则：一次一个里程碑；每阶段有验收标准；不伪造跑通。  
> 协作约定见 `GPT_COLLAB.md`。

---

## M0 — 仓库骨架 + Schema + 假数据演示（本提交）

**任务**

- [x] 文档：README、生财/GitHub 调研、架构、坑、协作说明
- [x] `schemas/channel_event.schema.json`
- [x] `connectors/` 接口占位（email / file / wechat_disabled）
- [x] `ingest/demo_run.py`：读 `fixtures/sample_events` → 脱敏 → 打印规范化结果
- [x] `memory/` 内存版 stub（dict facts）

**验收**

```bash
python -m ingest.demo_run
# 退出码 0；输出至少 1 条 redacted event 与 1 条抽取事实（规则/假 LLM）
```

**禁止**：声称已连接真实微信/邮箱。

---

## M1 — 单一渠道只读摄入（优先合规）

**推荐顺序**：`file_export`（用户导出的 mbox/eml/csv）→ 再 `email` OAuth 只读。

**任务拆解（可开 PR：`feat/m1-file-or-email-ingest`）**

1. 实现 `connectors/file_export.py`：解析一种导出格式 → `ChannelEvent`
2. 或 `connectors/email_imap_or_oauth.py`：最小只读；token 存系统钥匙串/本地加密文件
3. `ingest/pipeline.py`：validate（jsonschema）→ redact → 写入 `data/processed/`（gitignored）
4. 文档：`docs/connectors/email_or_file.md`（权限截图说明、撤销方式）
5. 测试：用脱敏假 mbox 夹具，无真实邮箱

**验收**

- 本地跑通：导出文件 → `data/processed/*.jsonl`
- CI 或本地 pytest：非法事件被拒；敏感字段被 redact
- README 更新「M1 已支持 X」——仅写真实已支持格式

**不做**：微信；出站；多渠道并行。

---

## M2 — 统一记忆层

**任务（PR：`feat/m2-local-memory`）**

1. 选定后端之一并写进配置：
   - A. SQLite + 本地 embedding（sentence-transformers / 小号 API 仅向量）
   - B. 自托管 Mem0（Docker），API 包一层 `memory/store.py`
2. 接口：`upsert_chunks` / `upsert_facts` / `search(query, user_id, k)`
3. 事实抽取：先规则 + 可选 LLM（**只送脱敏文本**）
4. 单测：写入后能按关键词/语义搜回

**验收**

- `python -m ingest.demo_run --persist` 后 `python -m memory.search_cli "快递"` 能命中夹具
- 配置 `allow_raw_llm_upload=false` 有测试锁住

**不做**：Letta 全量 runtime（可列为 M2.5 调研）。

---

## M3 — 越用越聪明闭环

**任务（PR：`feat/m3-memory-loop`）**

1. 定时/手动 job：`jobs/summarize_and_extract.py`
2. 对新增事件窗口做摘要 → 事实合并（冲突策略文档化）
3. Agent 最小 CLI：`agent/ask.py "我最近和谁约了开会？"` → 先 search 再答
4. 指标（简陋即可）：命中率抽检表 `docs/eval/m3_smoke.md`

**验收**

- 同一问题在「仅 raw」vs「记忆后」对比，文档记录一次真实输出
- 无记忆时明确说「不知道」，禁止编造

---

## 可选里程碑

### M2W — 微信本机只读插件

- 默认 `enabled: false`
- 包装社区 skill（陈钟琦 / 苏格文工具链），**不 vendoring 违规代码**
- README 大字警告：版本、降级、条款、风控
- 验收：在标注版本机上只读导出 → ChannelEvent；失败则文档写「未验证」

### M-DT — 钉钉只读

- 企业授权流程文档；租户隔离

### M-OUT — 出站

- 显式 feature flag + 人工确认；优先飞书/邮件草稿，而非微信个人号

---

## GPT / Codex 领取任务时的模板

```
请阅读 GPT_COLLAB.md 与 IMPLEMENTATION_PLAN.md 的 Mx。
只实现 Mx 列出的任务；不要顺手做微信或出站。
验收命令：……
若阻塞（缺 OAuth 凭证/缺真机微信），在 PR 描述写阻塞，提交到可测的假数据边界为止。
```
