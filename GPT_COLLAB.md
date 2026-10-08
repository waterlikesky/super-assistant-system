# 编码 Agent 协作约定（GPT / Codex / Claude）

**先读**：[README](README.md)（怎么跑）→ [docs/PRODUCT.md](docs/PRODUCT.md)（做什么 / 不做什么）→ [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)（下一步）→ [docs/research/borrow-list.md](docs/research/borrow-list.md)（先借轮子）。

## 代码地图

`sas/connectors/` 导出格式（一格式一类，注册表）· `sas/redact.py` 脱敏 · `sas/store.py` sqlite-utils + FTS5 · `sas/memory/` 抽取规则、合并衰减、mem0 适配 · `sas/assistant.py` 问答/待办/人物 · `sas/digest.py` 日报 · `sas/llm.py`、`sas/embed.py` 可选模型 · `sas/cli.py` 命令 · `fixtures/` 全虚构样例 · `tests/`。

## 规则

1. 一个 PR 一个可验收切片；PR 描述写：对应计划哪一条、验收命令、未完成项、是否触及真实数据（默认否）。
2. 合并前 `python3 -m pytest -q` 全绿；改了用户可见行为就同步 README。
3. 新 connector / 新抽取规则必须带**虚构**夹具和测试；不得有发送、联网能力。
4. 隐私护栏不可放松：入库前脱敏、出站无实现、云模型需 `SAS_ALLOW_CLOUD_LLM=true` 且只发脱敏片段。改动这些要在 PR 里单独说明。
5. 不提交 `.env`、`data/`、真实聊天导出、token；不把真实聊天贴进 Issue / PR / 对话日志。
6. 诚实：没跑通就写没跑通；不写「已打通微信」「已越用越聪明」之类超出测试的话。
7. 能用成熟库就不自己写（sqlite-utils、标准库 email/mailbox、llm、mem0、sqlite-vec）；AGPL 项目只借思路不拷代码。

分支：`feat/<主题>`、`fix/<主题>`、`docs/<主题>`。Claude ↔ Grok 分工见 [GROK_COLLAB.md](GROK_COLLAB.md)。
