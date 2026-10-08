"""每日摘要：确定性生成 Obsidian 友好的 Markdown（frontmatter + [[人名]] 链接）。

可选 --llm：在顶部加一段模型写的摘要（只发送脱敏、非 confidential 片段）。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sas.assistant import CHANNEL_LABEL, Assistant, fmt_time, short
from sas.memory import ME, MemoryItem
from sas.memory.rules import clauses


def _link(name: str) -> str:
    return f"[[{name}]]" if name and name != ME else (name or "")


def _todo(item: MemoryItem, done_box: bool = True) -> str:
    box = "- [x] " if item.status == "done" else "- [ ] " if done_box else "- "
    who = f"{_link(item.subject)} → {_link(item.counterpart)}" if item.counterpart else _link(item.subject)
    due = f"（截止 {item.due}）" if item.due else ""
    return f"{box}{who}：{item.text}{due}"


def build_digest(assistant: Assistant, day: str, llm_summary: str | None = None) -> str:
    store = assistant.store
    rows = store.events_on(day)
    lines = ["---", f"date: {day}", "type: sas-digest", "tags: [sas, 日报]",
             f"generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}", "---", "", f"# {day} 日报", ""]
    if not rows:
        latest = store.latest_day()
        hint = f"最近有数据的一天是 {latest}：`sas digest --date {latest}`" if latest else "数据库还是空的，先 `sas ingest <导出路径>`"
        return "\n".join(lines + [f"这一天没有消息。{hint}", ""])

    by_channel = Counter(CHANNEL_LABEL.get(r["channel"], r["channel"]) for r in rows)
    people = {r["sender"] for r in rows if r["sender"] != ME and not r["is_service"]}
    lines.append(f"**概览**：{len(rows)} 条消息 · " + " / ".join(f"{k} {v}" for k, v in by_channel.most_common()) + f" · 涉及 {len(people)} 人")
    lines.append("")
    if llm_summary:
        lines += ["## 摘要（模型生成，仅基于脱敏片段）", "", llm_summary.strip(), ""]

    ids = {r["id"] for r in rows}
    todays = [m for m in assistant.memory.list(now=assistant.now) if ids & set(m.source_event_ids)]
    created = [m for m in todays if m.source_event_ids[0] in ids]

    replies = [r for r in assistant.needs_reply() if r["day"] == day]
    sections = [
        ("待回复", [f"- {_link(r['conversation'])}（{CHANNEL_LABEL.get(r['channel'], '')} {fmt_time(r)}）：{short(r['content_text'])}" for r in replies]),
        ("我答应的", [_todo(m) for m in todays if m.kind == "commitment" and m.subject == ME]),
        ("别人找我", [_todo(m) for m in created if m.kind == "request" and m.counterpart == ME]),
        ("别人答应的", [_todo(m) for m in created if m.kind == "commitment" and m.subject != ME]),
        ("约定 / 日程", [_todo(m, done_box=False) for m in created if m.kind == "plan"]),
        ("新了解到", [f"- {_link(m.subject)}：{m.text}（{m.label}）" for m in created if m.kind in ("fact", "preference")]),
    ]
    for title, items in sections:
        if items:
            lines += [f"## {title}", "", *items, ""]

    memory_sources = {sid for m in todays for sid in m.source_event_ids}
    convs: dict[tuple, list[dict]] = defaultdict(list)
    notices: list[dict] = []
    for r in rows:
        (notices if r["is_service"] else convs[(r["channel"], r["conversation"])]).append(r)
    lines += ["## 会话", ""]
    for (channel, conv), msgs in sorted(convs.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"### {_link(conv)}（{CHANNEL_LABEL.get(channel, channel)} · {len(msgs)} 条）")
        lines.append("")
        key = [m for m in msgs if m["id"] in memory_sources or any(q for _, q in clauses(m["content_text"]))]
        picked = key[:5] or msgs[-3:]
        for m in sorted(picked, key=lambda m: m["epoch"]):
            text = "（敏感内容已隐藏）" if m["sensitivity"] == "confidential" else short(m["content_text"], 80)
            lines.append(f"- {fmt_time(m)} {m['sender']}：{text}")
        if len(picked) < len(msgs):
            lines.append(f"- …另有 {len(msgs) - len(picked)} 条")
        lines.append("")
    if notices:
        lines += [f"## 通知（{len(notices)} 条）", ""]
        for m in notices:
            text = "（验证码等敏感内容已隐藏）" if m["sensitivity"] == "confidential" else short(m["content_text"], 50)
            lines.append(f"- {fmt_time(m)} {m['conversation']}：{text}")
        lines.append("")
    lines.append(f"<!-- sas 出处：{json.dumps(sorted(ids)[:50], ensure_ascii=False)} -->")
    return "\n".join(lines) + "\n"


def digest_snippets(assistant: Assistant, day: str) -> list[str]:
    return [
        f"{fmt_time(r)} {CHANNEL_LABEL.get(r['channel'], '')}·{r['conversation']} {r['sender']}：{r['content_text']}"
        for r in assistant.store.events_on(day)
        if r["sensitivity"] != "confidential" and not r["is_service"]
    ]
