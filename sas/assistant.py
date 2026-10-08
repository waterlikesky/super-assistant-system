"""面向用户的查询：问答、人物、待办、待回复、统计。全部离线可用，每条结论带出处。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sas.memory import ME, TODO_KINDS, CompositeMemory, MemoryItem
from sas.memory.rules import BROADCAST_RE, REQUEST_RES, clauses
from sas.store import Store

CHANNEL_LABEL = {"wechat": "微信", "dingtalk": "钉钉", "email": "邮件", "sms": "短信", "feishu": "飞书", "file": "文件", "other": "其他"}

STOP_PHRASES = sorted(
    """我们 我的 我 你们 你 他们 他 她 它 的 了 吗 呢 吧 啊 么 什么 怎么 怎样 哪些 哪个 哪天 几号 谁 上次 上一次 最近 最后
    和 跟 与 同 聊了 聊过 聊 说了 说过 说 讲了 讲 关于 有没有 是不是 有 是 在 一下 告诉 帮我 查一下 查 找 问 消息 记录
    时候 那个 这个 一些 东西 事情 事 情况 内容 吗？ ？ ? 今天 该 回 谁 the a an what did do i me my about with is was""".split(),
    key=len,
    reverse=True,
)

INTENTS = {
    "reply": re.compile(r"该回|回复谁|回谁|没回|待回复|未回复|要回"),
    "promise": re.compile(r"答应|承诺|欠(?:了)?(?:谁|人)|许诺"),
    "todo": re.compile(r"待办|要做|该做|找我|托我|让我|todo", re.I),
    "pref": re.compile(r"喜欢|偏好|爱吃|爱喝|不吃|不喝|口味|习惯|讨厌|忌口"),
    "plan": re.compile(r"约了|约定|安排|日程|计划|开会|见面|什么时候"),
    "last": re.compile(r"上次|最近|聊了什么|聊过|说了什么|聊啥|说啥|最后一次"),
}


def fmt_time(row: dict, with_date: bool = False) -> str:
    ts = datetime.fromisoformat(row["ts"])
    return ts.strftime("%Y-%m-%d %H:%M" if with_date else "%H:%M")


def short(text: str, n: int = 60) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def reply_label(row: dict) -> str:
    """待回复里显示谁：邮件显示「发件人「主题」」，IM 显示会话名。"""
    if row["channel"] == "email":
        return f"{row['sender']}「{row['conversation']}」"
    return row["conversation"]


def item_line(item: MemoryItem, *, with_id: bool = True) -> str:
    who = item.subject if not item.counterpart or item.kind in {"preference", "fact"} else f"{item.subject} → {item.counterpart}"
    bits = [f"[{item.label}] {who}：{item.text}" if who else f"[{item.label}] {item.text}"]
    meta = []
    if item.due:
        meta.append(f"截止 {item.due}")
    if item.effective_confidence is not None:
        meta.append(f"置信 {item.effective_confidence:.2f}")
    if item.evidence > 1:
        meta.append(f"{item.evidence} 次提到")
    if item.status == "done":
        meta.append("已完成")
    if meta:
        bits.append(f"（{'，'.join(meta)}）")
    if item.source != "local":
        bits.append(f"（来自 {item.source}）")
    elif with_id and item.id:
        bits.append(f" #{item.id}")
    return "".join(bits)


@dataclass
class Answer:
    question: str
    sections: list[tuple[str, list[str]]] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    snippets: list[str] = field(default_factory=list)

    def cite(self, row: dict) -> str:
        for i, src in enumerate(self.sources, start=1):
            if src["id"] == row["id"]:
                return f"[{i}]"
        self.sources.append(row)
        if row["sensitivity"] != "confidential":
            self.snippets.append(f"{fmt_time(row, True)} {CHANNEL_LABEL.get(row['channel'], row['channel'])}·{row['conversation']} {row['sender']}：{row['content_text']}")
        return f"[{len(self.sources)}]"

    def add(self, title: str, lines: list[str]) -> None:
        if lines:
            self.sections.append((title, lines))

    @property
    def empty(self) -> bool:
        return not self.sections

    def render(self) -> str:
        out = []
        if self.empty:
            out.append("不知道：本地数据里没有找到相关内容。可以换个说法，或先 `sas ingest` 更多导出。")
        for title, lines in self.sections:
            out.append(f"── {title}")
            out += [f"  {line}" for line in lines]
        if self.sources:
            out.append("── 出处")
            for i, row in enumerate(self.sources, start=1):
                ch = CHANNEL_LABEL.get(row["channel"], row["channel"])
                out.append(f"  [{i}] {fmt_time(row, True)} {ch}·{row['conversation']}  {row['id']}")
        return "\n".join(out)


class Assistant:
    def __init__(self, store: Store, memory: CompositeMemory, *, now: datetime | None = None,
                 reply_window_days: int = 7, vectors=None) -> None:
        self.store = store
        self.vectors = vectors
        self.memory = memory
        self.now = now or datetime.now(timezone.utc)
        self.reply_window_days = reply_window_days

    # ---------- 基础查询 ----------
    def known_names(self) -> list[str]:
        names = {r["name"] for r in self.store.query("select name from people")}
        names |= {r["conversation"] for r in self.store.query("select distinct conversation from events where conversation != ''")}
        return sorted((n for n in names if n and len(n) >= 2), key=len, reverse=True)

    def mentioned_people(self, text: str) -> list[str]:
        found, rest = [], text
        for name in self.known_names():
            if name and name in rest:
                found.append(name)
                rest = rest.replace(name, " ")
        return found

    def keywords(self, question: str, exclude: list[str]) -> list[str]:
        text = question
        for name in exclude:
            text = text.replace(name, " ")
        for word in STOP_PHRASES:
            text = text.replace(word, " ")
        terms = []
        for token in re.split(r"[\s,，。！？!?、；;：:“”\"'（）()\[\]【】]+", text):
            if not token:
                continue
            if re.fullmatch(r"[A-Za-z0-9_.-]+", token):
                if len(token) >= 2:
                    terms.append(token)
                continue
            if len(token) >= 2:
                terms.append(token)
            if len(token) >= 4:
                terms += [token[i : i + 2] for i in range(len(token) - 1)]
        return list(dict.fromkeys(terms))

    def is_person(self, name: str) -> bool:
        return bool(self.store.query("select 1 from people where name = ?", [name]))

    def last_conversation(self, name: str, limit: int = 6) -> list[dict]:
        rows = self.store.query(
            """select * from events where (sender = ? or conversation = ? or participants like ?)
               order by epoch desc limit 1""",
            [name, name, f'%"display_name": "{name}"%'],
        )
        if not rows:
            return []
        last = rows[0]
        return self.store.conversation_tail(last["channel"], last["conversation"], limit)

    def todos(self, person: str | None = None) -> dict[str, list[MemoryItem]]:
        open_items = self.memory.list(kind=TODO_KINDS, status="open", now=self.now)
        def about(i: MemoryItem) -> bool:
            return person is None or person in (i.subject, i.counterpart, i.conversation)
        return {
            "mine": [i for i in open_items if i.kind == "commitment" and i.subject == ME and about(i)],
            "asked": [i for i in open_items if i.kind == "request" and i.counterpart == ME and about(i)],
            "owed": [i for i in open_items if i.kind == "commitment" and i.subject != ME and about(i)],
            "delegated": [i for i in open_items if i.kind == "request" and i.subject == ME and about(i)],
        }

    def needs_reply(self) -> list[dict]:
        """每个会话的最后一条：对方发来、不是通知、在窗口期内；群聊只算提问 / 点到大家的请求。"""
        anchor = self.store.query("select max(epoch) as m from events")[0]["m"]
        if anchor is None:
            return []
        since = anchor - self.reply_window_days * 86400
        rows = self.store.query(
            """select e.* from events e join (
                   select channel, conversation, max(epoch) as m from events group by channel, conversation
               ) last on e.channel = last.channel and e.conversation = last.conversation and e.epoch = last.m
               where e.direction = 'inbound' and e.is_service = 0 and e.sensitivity != 'confidential' and e.epoch >= ?
               order by e.epoch desc""",
            [since],
        )
        out = []
        for row in rows:
            asks = any(q for _, q in clauses(row["content_text"])) or any(p.search(row["content_text"]) for p in REQUEST_RES)
            if row["is_group"] and not (asks and BROADCAST_RE.search(row["content_text"])):
                continue
            out.append({**row, "asks": asks})
        out.sort(key=lambda r: (not r["asks"], -r["epoch"]))
        return out

    def people(self) -> list[dict]:
        rows = self.store.query("select * from people order by last_seen desc")
        todo = self.memory.list(kind=TODO_KINDS, status="open", now=self.now)
        for row in rows:
            row["channels"] = json.loads(row["channels"])
            row["open"] = sum(1 for i in todo if row["name"] in (i.subject, i.counterpart))
        return rows

    def profile(self, name: str) -> dict | None:
        matches = self.store.query("select * from people where name = ? or name like ?", [name, f"%{name}%"])
        if not matches:
            return None
        person = matches[0]
        person["channels"] = json.loads(person["channels"])
        n = person["name"]
        about = self.memory.list(kind=("fact", "preference"), subject=n, now=self.now)
        plans = [i for i in self.memory.list(kind="plan", now=self.now) if i.subject == n]
        return {
            "person": person,
            "about": about,
            "plans": plans,
            "todos": self.todos(n),
            "recent": self.last_conversation(n, limit=8),
        }

    # ---------- 问答 ----------
    def ask(self, question: str) -> Answer:
        ans = Answer(question)
        names = self.mentioned_people(question)
        person = names[0] if names else None
        hit = {k for k, r in INTENTS.items() if r.search(question)}

        if "reply" in hit:
            ans.add("该回复的", [f"{reply_label(r)}（{CHANNEL_LABEL.get(r['channel'], r['channel'])}，{fmt_time(r, True)}）：{short(r['content_text'])} {ans.cite(r)}" for r in self.needs_reply()])
        if "promise" in hit or "todo" in hit:
            t = self.todos(person)
            if "promise" in hit:
                ans.add("我答应别人的", [self._todo_line(i, ans) for i in t["mine"]])
                if person:
                    ans.add(f"{person} 答应我的", [self._todo_line(i, ans) for i in t["owed"]])
            if "todo" in hit:
                ans.add("别人找我办的", [self._todo_line(i, ans) for i in t["asked"]])
        # 意图词本身不算检索词；「火星移民计划」里的「计划」不该列出全部日程
        rest = question
        for r in INTENTS.values():
            rest = r.sub(" ", rest)
        terms = self.keywords(rest, names)

        def relevant(i: MemoryItem) -> bool:
            if person:
                return person in (i.subject, i.counterpart, i.conversation)
            return not terms or any(t in f"{i.subject}{i.text}" for t in terms)

        if "pref" in hit:
            items = [i for i in self.memory.list(kind="preference", now=self.now) if relevant(i)]
            ans.add("偏好", [self._todo_line(i, ans) for i in items])
        if "plan" in hit:
            items = [i for i in self.memory.list(kind="plan", now=self.now) if relevant(i)]
            ans.add("约定 / 日程", [self._todo_line(i, ans) for i in items])
        if person and ("last" in hit or not hit):
            rows = self.last_conversation(person)
            if rows:
                head = f"与 {person} 最近的交流（{CHANNEL_LABEL.get(rows[-1]['channel'], '')}·{rows[-1]['conversation']}，{rows[-1]['day']}）"
                ans.add(head, [f"{fmt_time(r, True)[5:]} {r['sender']}：{short(r['content_text'], 80)} {ans.cite(r)}" for r in rows])
                related = [i for i in self.memory.list(now=self.now) if person in (i.subject, i.counterpart) and i.status != "done"]
                ans.add(f"关于 {person} 的记忆", [item_line(i) for i in related[:8]])

        if terms and not (hit & {"reply", "promise", "todo"}):
            rows = self.store.search(terms, person=person if self.is_person(person or "") else None, limit=6)
            if self.vectors is not None:
                seen = {r["id"] for r in rows}
                rows += [r for r in self.vectors.search(question, k=4) if r["id"] not in seen]
            if rows:
                ans.add("相关消息", [f"{fmt_time(r, True)} {r['sender']}@{r['conversation']}：{short(r['content_text'], 80)} {ans.cite(r)}" for r in rows])
            mems = [m for m in self.memory.search(" ".join(terms), now=self.now) if m.status != "done"]
            if mems and not (hit & {"pref", "plan"}):
                local = [m for m in mems if m.source == "local"][:5]
                remote = [m for m in mems if m.source != "local"][:3]
                ans.add("相关记忆", [item_line(m) for m in local + remote])
        return ans

    def _todo_line(self, item: MemoryItem, ans: Answer) -> str:
        rows = self.store.query("select * from events where id = ?", item.source_event_ids[:1])
        cite = f" {ans.cite(rows[0])}" if rows else ""
        return item_line(item) + cite

    # ---------- 统计 ----------
    def stats(self) -> dict:
        q = self.store.query
        return {
            "events": self.store.count("events"),
            "by_channel": {r["channel"]: r["n"] for r in q("select channel, count(*) n from events group by channel order by n desc")},
            "range": q("select min(day) a, max(day) b from events")[0],
            "people": self.store.count("people"),
            "memories": {f"{r['kind']}/{r['status'] or '-'}": r["n"] for r in q("select kind, status, count(*) n from memories group by kind, status")},
            "sources": self.store.count("sources"),
            "confidential": q("select count(*) n from events where sensitivity = 'confidential'")[0]["n"],
        }
