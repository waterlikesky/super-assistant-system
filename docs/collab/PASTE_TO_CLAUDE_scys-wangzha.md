# 给 Claude Code 的可粘贴提示词（Claude 恢复登录/配额后整段粘）

```text
你是主控。按生财帖落地 Claude + Codex + Grok 协作：
https://scys.com/articleDetail/xq_topic/55521518825445424
（《Claude + Codex + Grok，就是王炸》）

背景：
- GPT / Grok Bot 已打通 bridge 文件通道这一半（mac-claude-bridge）
- 另一半断了：你（Claude）应能直接拉起 Codex / Grok，不靠复制粘贴；当前云端 Claude -p 曾 403，本机曾 429 配额尽
- 参考：https://github.com/waterlikesky/super-assistant-system
- bridge 任务：mac-claude-bridge inbox/to-claude/20261007-0857/REQUEST.md

请你现在做：
1. 读该帖：主控=Claude Code；执行=Codex（CLI+官方插件 https://github.com/openai/codex-plugin-cc）；按需=Grok Build CLI（https://docs.x.ai/build/overview）
2. 检查本机已装工具，缺什么按官方装；需要登录时给我步骤
3. 用一个只读小任务验证：你能实际调用 Codex（再试 Grok）并拿到结果——不要只写「应该可以」
4. 针对「云端 Claude → Grok Bot → Codex/Grok/zcode」：写清哪台机器跑主控、哪台跑执行；更新 bridge 的 CLAUDE.md / 协作文档；不要把 Mac 路径当 Linux 已通
5. 结果写回 inbox/from-claude/20261007-0857/RESULT.md（可覆盖诚实失败稿），HANDOFF → ready-for-mac，./bridge.sh push

禁止：伪造已接通；密钥进 git；安装 macOS EGO 到 Linux。
```
