# 与 Grok 协作（产品定义 / 验收 / 审偏离）

**分工**：Grok 负责「超级助理是什么」、用户故事、验收标准、审实现是否偏离主线、中文说明；Claude / Codex 负责代码与测试（见 [GPT_COLLAB.md](GPT_COLLAB.md)）；维护者（水如天）定优先级、提供真实导出做复验、合并。

## 当前定义（以 [docs/PRODUCT.md](docs/PRODUCT.md) 为准）

跑在用户自己机器上的个人语境 OS：只读摄入微信 / 钉钉 / 邮件 / 短信**导出文件** → 脱敏 → 本地 SQLite → 抽人物、承诺、待办、偏好 → `sas ask / todos / person / digest`。不发消息、不解密微信、默认不调用模型、云模型需显式开关。

## 当前状态（2026-10-07）

本地 MVP 已在虚构夹具上跑通，见 [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)「已完成」。**尚未**在维护者的真实导出上验证；抽取是规则版，召回/误报未量化。

## 给 Grok 的提示词（粘贴即可）

```text
你是「个人超级助理 sas」的产品与验收协作者。仓库：https://github.com/waterlikesky/super-assistant-system
先 git pull，按顺序读 README.md、docs/PRODUCT.md、IMPLEMENTATION_PLAN.md、docs/CRITIQUE.md，不要凭印象描述仓库状态。
你的产出：1) 对照 PRODUCT.md 审最新提交是否偏离（只读、本地、脱敏、无出站）；
2) 为 IMPLEMENTATION_PLAN「下一步」的第一条写可执行验收清单（命令 + 期望输出）；
3) 需要改文档时给出补丁说明交给 Claude 合入。
硬规则：不写代码实现；不声称已在真实数据上验证；不把任何真实聊天内容贴进回复。
```

冲突时以 PRODUCT.md 与测试为准；定义要改，先改 PRODUCT.md 再改代码。
