"""sas 命令行。所有命令只读本地导出、只写本地数据库；没有任何发送能力。"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from datetime import date
from pathlib import Path

from sas import __version__
from sas.assistant import CHANNEL_LABEL, Assistant, fmt_time, item_line, reply_label, short
from sas.config import Config, ConfigError
from sas.connectors import REGISTRY
from sas.digest import build_digest, digest_snippets
from sas.embed import get_vector_index
from sas.ingest import ingest_path
from sas.llm import LLMUnavailable, answer_with_llm, get_llm
from sas.memory import get_backend
from sas.privacy import PrivacyError
from sas.store import Store


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sas", description="个人超级助理：只读摄入聊天导出 → 本地记忆 → 问答 / 待办 / 日报")
    p.add_argument("--version", action="version", version=f"sas {__version__}")
    p.add_argument("--db", help="数据库路径（默认 ./data/sas.db，或 SAS_DB_PATH）")
    p.add_argument("--config", help="配置文件（默认 ./sas.toml）")
    p.add_argument("--me", help="导出里代表「我」的昵称，逗号分隔，例如 --me 水如天,Tian")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest", help="摄入导出文件或目录（增量、去重）")
    s.add_argument("paths", nargs="+")
    s.add_argument("--source", default="auto", help="强制格式：wechat / email / sms / dingtalk / events 或具体 connector 名")
    s.add_argument("-r", "--recursive", action="store_true", help="递归子目录（默认只看这一层；点开头的文件始终跳过）")
    s.add_argument("--consent-tag", help="这批数据的同意标记（默认 cli:<今天>）")
    s.add_argument("--force", action="store_true", help="文件没变也重新解析（已入库的消息仍不会重复）")

    s = sub.add_parser("ask", help="用一句话问：某人上次聊了什么 / 我答应过谁什么 / 今天该回谁 / 任意关键词")
    s.add_argument("question")
    s.add_argument("--llm", action="store_true", help="让已配置的 LLM 基于检索结果组织回答（默认离线）")

    s = sub.add_parser("search", help="全文检索消息（中文可用）")
    s.add_argument("terms", nargs="+")
    s.add_argument("-n", type=int, default=10)

    sub.add_parser("people", help="人物列表")
    s = sub.add_parser("person", help="人物画像")
    s.add_argument("name")

    s = sub.add_parser("todos", help="我答应的 / 别人找我的 / 别人答应我的 / 待回复")
    s.add_argument("--person")

    s = sub.add_parser("done", help="手动把一条承诺 / 请求标记完成")
    s.add_argument("id")

    s = sub.add_parser("digest", help="每日摘要（Markdown，Obsidian 友好）")
    s.add_argument("--date", default=None, help="YYYY-MM-DD，默认今天")
    s.add_argument("--out", help="输出目录或 .md 文件；不填则打印")
    s.add_argument("--llm", action="store_true", help="附加一段模型摘要（需配置 LLM 后端）")

    s = sub.add_parser("stats", help="数据与隐私开关概览")
    s.add_argument("--json", action="store_true")
    sub.add_parser("connectors", help="列出支持的导出格式")
    sub.add_parser("sync", help="把本地记忆与人物画像全量推到已配置的记忆镜像（OpenViking / TDAM / mem0）")
    return p


def _open(args) -> tuple[Config, Store, Assistant]:
    overrides = {"db_path": Path(args.db) if args.db else None, "me": args.me}
    config = Config.load(args.config, **overrides)
    store = Store(config.db_path)
    memory = get_backend(config, store)
    vectors, note = get_vector_index(config, store)
    if config.embed_model and vectors is None:
        print(f"[info] 语义检索未启用：{note}", file=sys.stderr)
    return config, store, Assistant(store, memory, reply_window_days=config.reply_window_days, vectors=vectors)


def cmd_ingest(args, config: Config, store: Store, a: Assistant) -> int:
    total_new = total_files = 0
    for path in args.paths:
        try:
            r = ingest_path(path, store=store, memory=a.memory, config=config, source=args.source,
                            recursive=args.recursive, consent_tag=args.consent_tag, force=args.force,
                            vectors=a.vectors)
        except (FileNotFoundError, KeyError) as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1
        for where, reason in r.skipped:
            print(f"skipped {where}: {reason}")
        if r.files == 0:
            print(f"{path}：没有可识别的导出文件（支持的格式见 `sas connectors`；子目录需要 -r）", file=sys.stderr)
        parts = ", ".join(f"{k} {v}" for k, v in r.by_connector.items())
        print(
            f"{path}：{r.files} 个文件（{r.unchanged} 个未变化跳过），新增 {r.new} 条消息"
            + (f"（{parts}）" if parts else "")
            + f"，重复 {r.duplicate} 条；新记忆 {r.memories} 条，自动完成 {r.closed} 条，更新人物 {r.people} 位"
            + (f"；同步到镜像 {r.mirrored} 条" if r.mirrored else "")
        )
        total_new += r.new
        total_files += r.files
    print(f"数据库：{config.db_path}（共 {store.count()} 条消息）")
    return 0 if total_files else 1


def cmd_ask(args, config: Config, store: Store, a: Assistant) -> int:
    ans = a.ask(args.question)
    print(f"问：{args.question}")
    if args.llm and ans.snippets:
        try:
            backend = get_llm(config)
            if backend is None:
                print("（未配置 LLM：设置 SAS_LLM_BACKEND=ollama 或 llm；以下为离线答案）")
            else:
                print("── 模型回答")
                print("  " + answer_with_llm(backend, args.question, ans.snippets, config.allow_cloud_llm).replace("\n", "\n  "))
        except (PrivacyError, LLMUnavailable) as exc:
            print(f"（LLM 未使用：{exc}）")
    print(ans.render())
    return 0


def cmd_search(args, config, store: Store, a) -> int:
    rows = store.search(a.keywords(" ".join(args.terms), []) or args.terms, limit=args.n)
    if not rows:
        print("没有命中。")
    for r in rows:
        print(f"{fmt_time(r, True)} {CHANNEL_LABEL.get(r['channel'], '')}·{r['conversation']} {r['sender']}：{short(r['content_text'], 90)}  {r['id']}")
    return 0


def _pad(text: str, width: int) -> str:
    """按终端显示宽度补空格（中文占两格）。"""
    shown = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    return text + " " * max(1, width - shown)


def cmd_people(args, config, store, a: Assistant) -> int:
    rows = a.people()
    if not rows:
        print("还没有人物。先 `sas ingest <导出路径>`。")
        return 0
    print(_pad("名字", 14) + _pad("渠道", 12) + _pad("收/发", 8) + _pad("未完成", 8) + "最近联系")
    for r in rows:
        ch = "/".join(CHANNEL_LABEL.get(c, c) for c in r["channels"])
        print(_pad(r["name"], 14) + _pad(ch, 12) + _pad(f"{r['msg_in']}/{r['msg_out']}", 8) + _pad(str(r["open"]), 8)
              + r["last_seen"][:16].replace("T", " "))
    return 0


def cmd_person(args, config, store, a: Assistant) -> int:
    prof = a.profile(args.name)
    if not prof:
        print(f"没找到「{args.name}」。用 `sas people` 看已有的人。")
        return 1
    p = prof["person"]
    print(f"# {p['name']}")
    print(f"渠道：{'/'.join(CHANNEL_LABEL.get(c, c) for c in p['channels'])} ｜ 往来：收 {p['msg_in']} / 发 {p['msg_out']}"
          f" ｜ 首次 {p['first_seen'][:10]} ｜ 最近 {p['last_seen'][:16].replace('T', ' ')}")
    if prof["about"]:
        print("\n## 了解到的")
        for i in prof["about"]:
            print("  " + item_line(i))
    if prof["plans"]:
        print("\n## 约定")
        for i in prof["plans"]:
            print("  " + item_line(i))
    t = prof["todos"]
    for key, title in (("mine", "我答应 TA 的"), ("asked", "TA 找我办的"), ("owed", "TA 答应的"), ("delegated", "我托 TA 的")):
        if t[key]:
            print(f"\n## {title}")
            for i in t[key]:
                print("  " + item_line(i))
    if prof["recent"]:
        last = prof["recent"][-1]
        print(f"\n## 最近一次会话（{CHANNEL_LABEL.get(last['channel'], '')}·{last['conversation']}）")
        for r in prof["recent"]:
            print(f"  {fmt_time(r, True)} {r['sender']}：{short(r['content_text'], 80)}")
    return 0


def cmd_todos(args, config, store, a: Assistant) -> int:
    t = a.todos(args.person)
    blocks = [("我答应别人的", t["mine"]), ("别人找我办的", t["asked"]), ("别人答应我的", t["owed"]), ("我托别人的", t["delegated"])]
    for title, items in blocks:
        if items:
            print(f"── {title}（{len(items)}）")
            for i in items:
                print("  " + item_line(i))
    replies = [r for r in a.needs_reply() if not args.person or args.person in (r["conversation"], r["sender"])]
    if replies:
        print(f"── 待回复（{len(replies)}）")
        for r in replies:
            print(f"  {reply_label(r)}（{CHANNEL_LABEL.get(r['channel'], '')} {fmt_time(r, True)}）：{short(r['content_text'])}")
    if not replies and not any(items for _, items in blocks):
        print("没有未完成事项。")
    print("（用 `sas done <#id>` 手动关闭一条）")
    return 0


def cmd_done(args, config, store, a: Assistant) -> int:
    if a.memory.close(args.id.lstrip("#")):
        print(f"已完成：{args.id}")
        return 0
    print(f"找不到唯一匹配的 id：{args.id}", file=sys.stderr)
    return 1


def cmd_digest(args, config: Config, store, a: Assistant) -> int:
    day = args.date or date.today().isoformat()
    summary = None
    if args.llm:
        try:
            backend = get_llm(config)
            snippets = digest_snippets(a, day)
            if backend and snippets:
                summary = answer_with_llm(backend, f"请用 5 条以内要点总结 {day} 的消息，突出待办和需要回复的人。", snippets, config.allow_cloud_llm)
            elif backend is None:
                print("（未配置 LLM，生成纯规则日报）", file=sys.stderr)
        except (PrivacyError, LLMUnavailable) as exc:
            print(f"（LLM 未使用：{exc}）", file=sys.stderr)
    md = build_digest(a, day, summary)
    if not args.out:
        print(md, end="")
        return 0
    out = Path(args.out).expanduser()
    target = out if out.suffix.lower() == ".md" else out / f"{day}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(md, encoding="utf-8")
    print(f"已写入 {target}")
    return 0


def cmd_stats(args, config: Config, store, a: Assistant) -> int:
    s = a.stats()
    s["db"] = str(config.db_path)
    s["privacy"] = {
        "llm_backend": config.llm_backend,
        "allow_cloud_llm": config.allow_cloud_llm,
        "outbound": "disabled（无发送实现）",
        "memory_backend": a.memory.name,
        "memory_mirrors": a.memory.notes,
        "semantic_search": get_vector_index(config, store)[1] if a.vectors is None else "已启用",
    }
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0
    rng = s["range"]
    print(f"数据库：{s['db']}")
    print(f"消息：{s['events']} 条（{rng['a'] or '-'} ~ {rng['b'] or '-'}），其中敏感已整条脱敏 {s['confidential']} 条")
    print("渠道：" + ("，".join(f"{CHANNEL_LABEL.get(k, k)} {v}" for k, v in s["by_channel"].items()) or "-"))
    print(f"人物：{s['people']} ｜ 来源文件：{s['sources']}")
    print("记忆：" + ("，".join(f"{k} {v}" for k, v in sorted(s["memories"].items())) or "-"))
    pv = s["privacy"]
    print(f"隐私：LLM={pv['llm_backend']} ｜ 云模型={'允许(仅脱敏片段)' if pv['allow_cloud_llm'] else '禁止'} ｜ 出站={pv['outbound']} ｜ 记忆后端={pv['memory_backend']}")
    for name, note in pv["memory_mirrors"].items():
        print(f"记忆镜像 {name}：{note}")
    print(f"语义检索：{pv['semantic_search']}")
    return 0


def cmd_connectors(args, *_):
    for name, c in REGISTRY.items():
        print(f"{name:<12} {CHANNEL_LABEL.get(c.channel, c.channel):<4} {'/'.join(c.suffixes):<12} {c.description}")
    return 0


def cmd_sync(args, config: Config, store, a: Assistant) -> int:
    if not a.memory.mirrors:
        reasons = "；".join(f"{k}: {v}" for k, v in a.memory.notes.items()) or "memory_backend=local"
        print(f"没有可用的记忆镜像（{reasons}）。本地 SQLite 仍是完整的真源。")
        return 1
    for name, n in a.memory.sync(store).items():
        print(f"{name}：推送 {n} 份（记忆 + 人物画像，均为脱敏内容）")
    return 0


COMMANDS = {
    "ingest": cmd_ingest, "ask": cmd_ask, "search": cmd_search, "people": cmd_people, "person": cmd_person,
    "todos": cmd_todos, "done": cmd_done, "digest": cmd_digest, "stats": cmd_stats, "connectors": cmd_connectors,
    "sync": cmd_sync,
}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "connectors":
            return cmd_connectors(args)
        config, store, assistant = _open(args)
        return COMMANDS[args.cmd](args, config, store, assistant)
    except (ConfigError, PrivacyError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
