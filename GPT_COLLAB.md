# 与 GPT / Codex 协作约定

面向仓库维护者（水如天）与编码 Agent（GPT、Codex、Claude Code 等）。

> Claude↔Grok：实现与测试走本文件；把「超级助理是什么」交给 Grok 时，整段复制 [`GROK_COLLAB.md`](GROK_COLLAB.md) 里的提示词。

---

## 1. 角色

| 角色 | 职责 |
|------|------|
| 维护者 | 定优先级、提供真实账号/导出、合并 PR、隐私拍板 |
| 编码 Agent | 按里程碑改代码与文档；写测试；诚实报告阻塞 |
| 调研 Agent | 更新 `docs/research/*`；不夸大 stars 与可用性 |
| Grok CLI | 产品定义、验收标准、审偏离主线、中文说明；提示词见 [`GROK_COLLAB.md`](GROK_COLLAB.md) |

---

## 2. PR 约定

1. **分支命名**：`feat/m1-file-ingest`、`fix/redact-phone`、`docs/scys-update`
2. **一次一个里程碑切片**；禁止「顺便打通微信」
3. **PR 描述必须含**：
   - 对应 `IMPLEMENTATION_PLAN` 哪一节
   - 如何本地验收（命令）
   - 未完成项 / 阻塞
   - 是否触及真实个人数据（默认否）
4. **不要**在 commit 里放 `.env`、聊天导出、token
5. **不要伪造**：未跑通的验收、未验证的 Claude/Codex 成功、未测试的微信版本

---

## 3. 验收标准（通用）

- 文档与代码一致：README「已支持」= 真能跑
- 新 connector 有夹具测试或明确「仅手工」
- 隐私：新路径默认不上传 raw
- 中文用户可读说明（可中英混排，关键警告用中文）

---

## 4. 推荐工作流

```
1. 打开 IMPLEMENTATION_PLAN 当前 M
2. 复制文末「领取任务模板」给 GPT
3. Agent 实现 → 本地验收 → PR
4. 维护者用自己的导出文件复验（Agent 无用户真实邮箱时不要催凭证进仓库）
5. 合并后勾选计划中的 checkbox
```

---

## 5. 禁止事项

- 将完整微信/短信记录粘贴进 Issue / PR / Chat 日志
- 为绕过 Auto-review 或平台风控而改包装命令
- 声称「已打通所有数据」「已越用越聪明」而实际仅有 stub
- 默认打开 outbound

---

## 6. 归因

- 生财帖与开源项目在文档中留链接 / entityId
- Agent 生成代码在 PR 中可注明模型；**失败如实写**

---

## 7. 下一步（给维护者）

当前完成后，请打开：

1. `IMPLEMENTATION_PLAN.md` → **M1**
2. `docs/problems/channel-ingestion-pitfalls.md`（接入前过清单）
3. `schemas/channel_event.schema.json` + `ingest/demo_run.py`（理解数据形状）

对 Claude / Codex 说：「按 IMPLEMENTATION_PLAN 的 M1，只实现 `.eml` 目录的 file_export。不要做邮件 OAuth、微信或出站。」
