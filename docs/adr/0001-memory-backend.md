# ADR 0001：记忆后端选型

- 状态：已采纳（2026-10-07）
- 决策人：Claude（实现），待维护者确认
- 依据：TencentDB-Agent-Memory README / INSTALL / MemoryCore v3 API / Python SDK README；OpenViking README / openviking-sdk README；本机已装 SDK 源码（`openviking_sdk` 0.1.13、`tencentdb_agent_memory` 1.0.1-beta.1）与 `openviking` 0.4.23 server 源码（仅用于查 API）

## 背景

sas 的本地规则后端（`LocalMemory`，SQLite）已经能抽承诺 / 请求 / 偏好 / 事实 / 约定，并做合并、衰减、关闭。缺的是：语义检索、更好的摘要与画像、可以被其他 Agent（Claude Code、OpenClaw）复用的记忆。按 borrow-list 的原则，这部分应该借成熟项目，而不是自己写向量库和摘要管线。

候选：TencentDB-Agent-Memory（下称 TDAM）、OpenViking、mem0，以及现状（只用本地规则）。

## 对比

| 维度 | 本地规则（现状） | **OpenViking** | TDAM | mem0 |
|------|-----------------|---------------|------|------|
| 许可 | MIT（本仓库） | 主项目 **AGPL-3.0**；sas 只通过 HTTP 调用独立运行的 server，不分发、不链接其代码，不构成衍生作品 | MIT | Apache-2.0 |
| 活跃度 | — | 39.4k★，持续发版（0.4.x） | 27.8k★，9/29 仍有提交，SDK 仍是 beta | 66.8k★，非常活跃 |
| 安装成本 | 零 | 一个 Python server（`pip install openviking` / Docker），加 1 个 embedding 模型 + 1 个 VLM | memory-core + memory-hub + proxy 三个服务（通常是 Docker），主体 TypeScript，**Node ≥ 22.16**（本机 20.19），`.env` 里要配两组 LLM | `pip install mem0ai`，进程内运行，需要 LLM、embedding 和向量库配置 |
| 本地 / 离线 | 完全离线 | 可以：provider 支持 Ollama；embedding 可用本地 GGUF（bge-small-zh-v1.5，经 llama-cpp-python） | 理论可以（OpenAI 兼容端点指向本地模型），但部署按团队服务设计，内核要求 LLM 连通才启动 | 可以：Ollama + 本地向量库；**默认配置走 OpenAI** |
| 中文 | 规则为中文写的；FTS5 trigram | 好：可选中文 embedding（bge-zh），自带 L0/L1 摘要；示例与社区里有大量中文内容 | 好（腾讯出品，文档有中文版） | 取决于所选模型 |
| 必须云账号 / 付费 key | 否 | 否（自托管）；火山引擎托管版前 50 个文件免费、之后收费，可选 | 否（自托管），但必须提供 LLM 端点 | 否（自托管）；mem0 平台版要 key |
| Python API | 内置 | 官方轻量 SDK `openviking-sdk`（PyPI，只依赖 httpx） | 官方 SDK **不在 PyPI**，只能从仓库 `sdk/memory-core/python` 安装；README 写「v2 API」，包里同时带 `tencentdb_agent_memory.v2`（`/v2/*`）和 `tencentdb_agent_memory.v3`（`/v3/*`，强制 team/agent/user 三元组隔离）。MemoryCore 文档是 v3，部分接口（`*/count`）只有 v3 有。**结论：v2、v3 并存，应使用 v3 客户端** | `mem0.Memory`，进程内 |
| 数据模型 | 结构化表（kind / subject / counterpart / due / status） | `viking://` 虚拟文件系统；资源、记忆、技能都是可读、可编辑的 Markdown 文件；L0 摘要 / L1 概览 / L2 原文分层读取；session commit 自动抽取记忆 | L0 对话 → L1 原子事实 → L2 场景 → L3 Persona；BM25 + 向量 + RRF | 扁平事实列表，ADD / UPDATE / DELETE |
| 与「个人语境 OS」的契合 | 结构好，但没有语义 | **高**：人物画像、每日摘要天然就是文件；用户能直接打开、修改；单用户本机部署是一等公民；能作为 Claude Code / OpenClaw 的共享上下文库 | 中：分层设计很合适，但产品定位是**团队级 Memory Hub**（多租户、面板、代理），对一个人的笔记本电脑来说太重 | 中：最省事，但记忆是黑盒事实列表，画像和出处要自己拼 |

## 决定

1. **本地 SQLite 永远是真源**。`LocalMemory` 保留为默认、零依赖后端；所有外部后端都是**镜像增强层**。外部后端不可达时只告警，摄入、问答、待办都不受影响。
2. **主推 OpenViking**，实现为 `OpenVikingMemory`（`sas/memory/openviking_adapter.py`），走官方 `openviking-sdk`：
   - 写入：每条记忆、每个人物画像、每日摘要写成 `viking://resources/sas/...` 下的 Markdown（`batch_write`，mode=`upsert`），由 OpenViking 生成 L0/L1 并建向量；
   - 检索：`find(target_uri=viking://resources/sas)`，结果合并进 `sas ask` 的「相关记忆」；
   - 配置：`openviking_url`、`openviking_root`、`openviking_models`（`local` / `cloud`），API key 只从环境变量 `OPENVIKING_API_KEY` 读取。
3. **TDAM 作为可选适配器**，实现为 `TDAMMemory`（`sas/memory/tdam_adapter.py`），走官方 SDK 的 **v3** 客户端：记忆写入 L0 `conversation/add`（每条记忆一条消息，session = `sas-<kind>`），检索走 L1 `atomic/search`，画像读 L3 `core/read`。适合已经在团队里部署了 TDAM 的用户。
4. **mem0 适配器保留**，仍为可选，不再主推。
5. 隐私护栏对所有外部后端一致：
   - 只发送脱敏后的文本（`privacy.prepare_for_model` 再过一遍）；`confidential` 事件不会产生记忆，自然不会外发；
   - 后端可能使用云模型时（`openviking_models=cloud`、TDAM 一律视为由服务端 LLM 处理、mem0 默认配置），必须显式 `SAS_ALLOW_CLOUD_LLM=true`，否则拒绝启用并降级为本地；
   - server 地址不是本机时同样视为云端。

## 为什么不选另外两个做主后端

- **TDAM**：许可最友好（MIT），分层模型也最接近我们想要的「事实 → 场景 → 画像」，但它是给团队用的 Memory Hub：Docker 起三个服务、Node 22.16+、内核启动前必须连通 LLM、Python SDK 不在 PyPI 且是 beta。对「一个人、一台电脑、默认离线」来说门槛过高。
- **mem0**：安装最省事，但记忆是黑盒事实列表，和 sas 已有的结构化表重复；默认配置走 OpenAI，容易误把数据发到云端。

## 后果

- 新增可选依赖：`pip install '.[openviking]'`（openviking-sdk）、`'.[tdam]'`（需要从官方仓库手动安装 SDK，见 README）。
- 测试：适配器用假 server（FastAPI + uvicorn，测 OpenViking SDK 的真实 HTTP 往返）和 `httpx.MockTransport`（TDAM v3 客户端支持注入 `httpx.Client`）覆盖；设置 `OPENVIKING_URL` / `TDAM_URL` 时才跑真实集成测试。
- AGPL 说明写进 README 和 borrow-list：sas 不包含 OpenViking 代码，只把它当一个外部 HTTP 服务；如果用户修改 OpenViking 并对外提供网络服务，AGPL 义务归该部署方。
- 风险：OpenViking 的 API 仍在 0.x 快速迭代，适配器只用了 `health / batch_write / find / read` 四个调用，升级时影响面小。
