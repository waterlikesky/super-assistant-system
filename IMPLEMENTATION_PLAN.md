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

## M1 — `file_export`：只读解析 `.eml` 目录

**决定（Grok，2026-10-07，仓库当时为 M0）**：本里程碑只做这一种输入。mbox、csv、邮件 OAuth、微信、钉钉、出站都不在这个 PR。

**为何先做导出文件**：`.eml` 可以用脱敏夹具在本地跑完，不需要邮箱凭证。邮件 OAuth 还要最小 scope、钥匙串和撤销说明，缺凭证时只能停在假数据。OAuth 列为下一条，不提前开工。

**任务（PR：`feat/m1-file-ingest`）**

1. `connectors/file_export.py`：给定一个目录，只读取这一层里的 `*.eml`（不递归子目录，不进入隐藏目录）。每封信产出一条 `ChannelEvent`：
   - `channel` 为 `email`；`metadata.ingest_via` 为 `file_export`
   - `direction` 为 `inbound`
   - `id` 稳定：优先 `Message-ID`；没有则用 `file:` 加相对路径的稳定哈希。同一文件重跑，`id` 不变
   - `timestamp` 取 `Date`。缺省或无法解析时，该文件失败并记入错误清单，不写半条事件
   - `participants` 来自 From / To / Cc；handle 在落盘前打码
   - `thread_id`：有 `In-Reply-To` 或 `References` 的第一个 id 则用之，否则 `null`
   - `content_text` 为纯文本：有 `text/plain` 用它，否则从 HTML 去掉标签。遇到单独一行 `-- ` 时丢掉其后的签名；没有这行就保留正文，并在 connector 文档里写明
   - `consent_tag` 由调用方传入；缺省则拒绝运行
   - `raw_ref` 只记本地路径，不把原信复制进仓库
   - 附件只把文件名和大小写入 `metadata.attachments`，字节不进 `content_text`
2. 增加摄入入口（新模块，或在现有 pipeline 上加写盘）：`validate`（jsonschema）→ `redact` → 写入 `data/processed/events.jsonl`
3. `.gitignore` 已含 `data/processed/`（本定义补丁补上；M0 计划写了要忽略，当时文件里没有）。实现时确认这一行仍在，且 jsonl 不会被提交
4. 脱敏至少覆盖：正文手机号变成 `[PHONE]`；正文和 handle 里的邮箱本地部分打码；`sensitivity=confidential` 或命中验证码的正文不得原样落盘
5. 夹具：`fixtures/sample_exports/mail/` 放 2 封脱敏 `.eml`（一封普通信，一封含手机号、邮箱和验证码），再放 1 个应被拒绝的文件（坏日期或空正文）
6. 文档：`docs/connectors/file_export.md`，写清只支持 `.eml` 目录、怎样从邮件客户端导出、数据留在本机、怎样删掉 `data/processed/`
7. README 的「已支持」只写 `.eml` 目录只读摄入

**验收（实现者跑完再勾。本节写入时 M1 尚未实现，下列命令还不能当已通过）**

```bash
python -m ingest.demo_run
# 退出码 0。M0 假数据路径仍可用。

pytest -q
# 含 tests/test_file_export.py：
# 合法 eml 通过 schema；
# jsonl 里看不到夹具中的手机号和验证码明文；
# 坏文件被拒绝，且没有对应事件；
# 默认 WechatLocalConnector 仍拒绝迭代；
# EmailOAuthConnector 仍是 NotImplementedError；
# 跑夹具时没有对外网络连接。

python -m ingest.file_export_run \
  --input fixtures/sample_exports/mail \
  --out data/processed/events.jsonl \
  --consent-tag fixture-m1
# 退出码 0
# jsonl 至少 2 行，每行通过 channel_event.schema.json
# git check-ignore -q data/processed/events.jsonl 的退出码为 0
```

**失败时**

- 目录不存在，或其中没有 `.eml`：非 0 退出，stderr 写明原因，不留下表示成功的空文件
- 单封解析失败：跳过该文件，stdout 列出路径和原因；其余成功的仍写入。全部失败则退出码非 0
- 缺 `--consent-tag`：非 0 退出，不写盘

**不做**：微信；邮件 OAuth；出站；mbox；csv；多渠道并行。

**下一条（另开 PR，本里程碑不实现）**：邮件 OAuth 只读。前置是本验收通过；token 放系统钥匙串或本地加密文件；scope 只读；文档写清撤销步骤。

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
