# 超级助理 sas

> **跑在你自己电脑上的「个人语境 OS」**：只读摄入微信 / 钉钉 / 邮件 / 短信导出，脱敏后存进本地 SQLite，持续抽出人物、承诺、待办、偏好，一句话问回来。不发消息，不上传。

能回答：**某人上次聊了什么 · 我答应过谁什么 · 今天该回谁 · 今天发生了什么 · 这个人喜欢什么**。产品定义见 [docs/PRODUCT.md](docs/PRODUCT.md)。

## 5 分钟快速开始

需要 Python ≥ 3.11（SQLite ≥ 3.34，用于中文 trigram 检索；Python 3.11+ 自带的一般都满足）。

```bash
git clone https://github.com/waterlikesky/super-assistant-system.git
cd super-assistant-system
python3 -m venv .venv && source .venv/bin/activate
pip install -e .            # 得到 sas 命令
```

> 不想装包：`pip install -r requirements.txt`，然后把下面的 `sas` 换成 `python -m sas`。

用仓库里的**全虚构**样例数据跑一遍（数据库默认写到 `./data/sas.db`，已 gitignore）：

```bash
sas ingest fixtures/exports -r                 # 微信 txt/csv、邮件 mbox/eml、短信 xml/csv、钉钉 csv
sas ask "上次和老王聊了什么"
sas ask "我答应过谁什么"
sas ask "今天该回谁"
sas ask "报价单"                               # 任意关键词，中文全文检索
sas people
sas person 老王                                # 人物画像：偏好、事实、约定、未完成事项、最近会话
sas todos                                      # 我答应的 / 别人找我的 / 别人答应我的 / 待回复
sas digest --date 2026-10-06 --out data/digests  # 每日摘要 → data/digests/2026-10-06.md
sas stats
```

再跑一次 `sas ingest fixtures/exports -r`，会显示「新增 0 条」——增量 + 去重。

`sas ask "上次和老王聊了什么"` 的输出节选：

```
── 与 老王 最近的交流（微信·老王，2026-10-06）
  10-06 18:20 我：报价单已经发你了，查收 [5]
  10-06 20:05 老王：收到。身份证号 [ID_CARD] 帮我填一下报名表 [6]
── 关于 老王 的记忆
  [请求] 老王 → 我：你周四前能帮我看下合同吗（截止 2026-10-08，置信 0.53） #r-11a12f5
  [偏好] 老王：不吃香菜（置信 0.59） #p-4189ab9
── 出处
  [5] 2026-10-06 18:20 微信·老王  wechat:f0db8c9ac7abec48
```

身份证号、手机号在入库前已经被替换；「我明天把报价单发你」这条承诺因为后面说了「已经发你了」被自动标为完成。

## 用你自己的数据

| 渠道 | 怎么导出 | 命令 |
|------|---------|------|
| 微信 | 用 [WeChatMsg / 留痕](https://github.com/LC044/WeChatMsg) 导出 txt 或 csv（每个聊天一个文件，文件名 = 会话名） | `sas --me 你的微信昵称 ingest ~/导出/微信 -r` |
| 邮件 | Gmail Takeout / Thunderbird 的 `.mbox`；或客户端「另存为 .eml」 | `sas ingest ~/Takeout/Mail` |
| 短信 | Android 用 SMS Backup & Restore 导出 xml；或任意含「号码/内容/时间」列的 csv | `sas ingest sms-backup.xml` |
| 钉钉 | 聊天记录导出或整理成 csv/xlsx，列名含「时间、发送人、内容」（可选「会话」） | `sas ingest 钉钉.csv --source dingtalk` |

- `--me` 告诉 sas 导出里哪个昵称是你（用于判断「谁答应了谁」）；也可以写进 `sas.toml`：`me = ["水如天"]`、`me_emails = ["me@example.com"]`。
- 识别不准时用 `--source wechat|email|sms|dingtalk` 强制格式；`sas connectors` 列出全部格式，列名与已知坑见 [docs/connectors.md](docs/connectors.md)。
- 定期重新导出、重新 `sas ingest` 即可，只有新消息会被处理。
- 想用浏览器翻数据：`pip install datasette && datasette data/sas.db`。
- 全部遗忘：删除 `data/sas.db`。

## 架构

```
 你自己的导出文件（只读）
 WeChatMsg txt/csv · mbox/eml · SMS xml/csv · 钉钉 csv/xlsx
              │  sas/connectors/   一个格式一个 connector，注册表 + 自动识别
              ▼
   ChannelEvent（sas/schemas/channel_event.schema.json，jsonschema 校验）
              │  sas/redact.py     入库前脱敏：手机/验证码/身份证/银行卡/邮箱/单号
              ▼
   data/sas.db（sqlite-utils）── events + events_fts（FTS5 trigram，中文可搜）
              │                   sources（文件指纹 → 增量） · 可选 vec_events（sqlite-vec）
              │  sas/memory/       MemoryBackend：本地规则抽取（默认）| mem0 镜像（可选）
              ▼
   memories：承诺 / 请求 / 偏好 / 事实 / 约定 ── 合并、置信度、半衰期衰减、自动关闭
   people：跨渠道人物
              │  sas/assistant.py · sas/digest.py · sas/cli.py
              ▼
   sas ask / people / person / todos / digest（Markdown → Obsidian）
              ┆  可选 sas/llm.py：Ollama 本机 / simonw/llm；云端需显式开关、只发脱敏片段
```

## 借用的开源

按 [docs/research/borrow-list.md](docs/research/borrow-list.md) §5：能依赖就依赖，只在「个人语境 + 隐私边界」这层自己写。

| 用途 | 项目 | 用法 |
|------|------|------|
| 存储、FTS5 | [simonw/sqlite-utils](https://github.com/simonw/sqlite-utils) | 建表、upsert、`enable_fts(tokenize="trigram")` |
| 浏览 | [simonw/datasette](https://github.com/simonw/datasette)（可选） | `datasette data/sas.db` |
| 邮件解析 | Python 标准库 `mailbox` / `email` | 不自己写 MIME 解析 |
| 微信 | [LC044/WeChatMsg](https://github.com/LC044/WeChatMsg) 的导出物 | 只吃导出文件，不碰解密 |
| LLM（可选） | [simonw/llm](https://github.com/simonw/llm)、[Ollama](https://github.com/ollama/ollama) | `SAS_LLM_BACKEND=ollama` 或 `llm` |
| 记忆（可选） | [mem0ai/mem0](https://github.com/mem0ai/mem0) | `SAS_MEMORY_BACKEND=mem0` 时作为镜像；缺包自动降级 |
| 向量（可选） | [asg017/sqlite-vec](https://github.com/asg017/sqlite-vec) + llm embeddings | `SAS_EMBED_MODEL=...` 时启用 |
| 设计参考 | Hermes Agent、Letta、Memobase、HPI、dogsheep | 分层记忆、一源一模块 → SQLite |

## 配置与隐私边界

配置优先级：默认值 → `./sas.toml`（或 `--config`）→ 环境变量 `SAS_*`。见 [.env.example](.env.example)。

| 项 | 默认 | 说明 |
|----|------|------|
| `SAS_DB_PATH` | `data/sas.db` | 唯一的数据文件；`--db` 覆盖 |
| `SAS_ME` / `SAS_ME_EMAILS` | `我` | 你在导出里的昵称 / 邮箱 |
| `SAS_TZ` | `Asia/Shanghai` | 无时区的导出时间按此解释 |
| `SAS_LLM_BACKEND` | `none` | `none` 纯离线；`ollama` 本机；`llm` 走 simonw/llm |
| `SAS_ALLOW_CLOUD_LLM` | `false` | 云端模型（含 mem0 默认配置、云 embedding）必须显式打开；打开后也只发脱敏片段，`confidential` 消息永不外发 |
| `SAS_OUTBOUND_ENABLED` | `false` | **没有发送实现**；设为 true 会直接报错退出 |
| `SAS_MEMORY_BACKEND` | `local` | `mem0` 时额外镜像到 mem0 |
| `SAS_EMBED_MODEL` | 空 | 设置后启用语义检索（需 `.[llm,vec]`） |

- 原始导出不复制、不上传；`raw_ref` 只记本机路径。
- 脱敏发生在入库**之前**：数据库文件里搜不到手机号、身份证、银行卡、验证码（有测试锁住）。
- 微信解密、Hook、协议号一律不做；企业钉钉数据请先确认公司政策。

## 开发

```bash
python3 -m pytest -q        # 全部离线；mem0 / sqlite-vec 未安装时相关用例 skip
```

代码地图：`sas/connectors/`（加新格式：写一个 `Connector` 子类并 `register`）、`sas/redact.py`、`sas/store.py`、`sas/memory/`（`rules.py` 抽取规则、`local.py` 合并与衰减）、`sas/assistant.py`、`sas/digest.py`、`sas/cli.py`。

## 路线图

已完成与下一步见 [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)。近期：LLM 辅助抽取（规则先行、模型补漏）、按人合并别名、MCP 接口（给 OpenClaw / Claude 当记忆层）、定时摄入。

协作约定：[GPT_COLLAB.md](GPT_COLLAB.md)（编码 Agent）、[GROK_COLLAB.md](GROK_COLLAB.md)（产品 / 验收）。审计记录：[docs/CRITIQUE.md](docs/CRITIQUE.md)。

## License

MIT。第三方项目遵循各自许可证；文档中引用的生财有术帖子仅供学习，版权归原作者。
