"""离线规则抽取：从一条（已脱敏的）消息里抽 承诺 / 请求 / 偏好 / 事实 / 约定。

先确定性抽取、再（可选）交给模型润色 —— borrow-list §4：「MCP 一句话总结容易丢内容」。
规则宁缺毋滥：只认带动作动词的承诺 / 请求，问句不当承诺，否定句不当承诺。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .base import ME, MemoryItem
from .timeparse import resolve_due

CLAUSE_RE = re.compile(r"[^。！？!?\n；;，,]+[。！？!?；;，,]?")
LEAD_FILLER_RE = re.compile(r"^(?:好的?|好呀|好嘞|行|嗯+|没问题|可以|OK|ok|收到|对了|另外|那|哈哈+)[，,、 ]*")
TRAIL_PUNCT = "。！？!?；;，, "

ACTION = r"(?:发|给|整理|准备|提交|更新|回复|回你|联系|处理|安排|看|改|写|做|订|带|买|打|约|跟进|确认|搞定|到|交|负责|过一遍|查|问|修|测|弄|算|寄|还|转|填|签|传|帮|(?i:\b(?:send|share|call|email|review|finish|check|book|bring|prepare|update|reply|follow up|get back|fix|look)\b))"
WHEN = (
    r"(?:会|来|去|负责|争取|尽快|马上|稍后|晚点|回头|这就|一定|今天|今晚|明天|明早|后天|"
    r"下周[一二三四五六日天]?|这周[一二三四五六日天]?|周[一二三四五六日天]|月底前?|下班前|\d{1,2}号前?)"
)
COMMIT_RES = [
    re.compile(rf"我{WHEN}.{{0,30}}"),
    re.compile(r"我.{0,12}(?:发|给|传|转|寄)(?:你|您)"),
    re.compile(r"包在我身上"),
    re.compile(r"(?i)\bI(?:'ll| will| am going to|'m going to)\b.{2,60}"),
]
NEGATION_RE = re.compile(r"不会|没法|不能|不去|没空|来不及|不行|won't|can't|cannot")

REQUEST_RES = [
    re.compile(r"(?:你|您)(?:能|可以|可否|方便|能不能|有空|帮忙)"),
    re.compile(r"(?:你|您).{0,6}(?:帮我|帮忙)"),
    re.compile(r"^(?:麻烦|劳烦|辛苦|请)(?!问)"),
    re.compile(r"(?<!我)(?:帮我|记得|别忘了|不要忘了|能否)"),
    re.compile(r"(?i)\b(?:can|could|would) you\b|^please\b"),
    re.compile(r"(?:大家|各位|所有人|全体)"),
]
BROADCAST_RE = re.compile(r"大家|各位|所有人|全体|@所有人")

PREF_RE = re.compile(
    r"我(?:最|比较|很|超|特别|一直)?(?:(?:喜欢|爱吃|爱喝|爱看|偏好|习惯|讨厌|不喜欢|不太喜欢|不吃|不喝|吃不了|喝不了).{1,20}|对.{1,6}过敏.{0,20})"
)
PREF_EN_RE = re.compile(r"(?i)\bI (?:really )?(?:like|love|prefer|hate|don't like|do not like)\b.{1,40}")
FACT_RES = [
    re.compile(
        r"我(?:下个月|下周|明年|今年|最近|已经|刚刚?|准备)?(?:搬到|搬去|搬家到|住在|入职|加入了?|换到|调到|跳槽到|毕业于|离职|在.{1,8}(?:工作|上班|读书))[^，。！？]{0,20}"
    ),
    re.compile(r"我的(?:生日|老家|新地址|公司|学校|孩子|女儿|儿子)[^，。！？]{1,20}"),
    re.compile(r"我(?:女儿|儿子|老婆|老公|孩子|爸|妈)[^，。！？]{2,20}"),
]
TIMEWORD = r"(?:今天|明天|后天|今晚|明晚|明早|周[一二三四五六日天末]|星期[一二三四五六日天]|下周[一二三四五六日天]?|这周[一二三四五六日天末]?|\d{1,2}月\d{1,2}[日号]|\d{1,2}[日号])"
PLAN_RES = [
    re.compile(TIMEWORD + r".{0,14}(?:见面|见|开会|会议|吃饭|聚餐|碰头|面试|复诊|出发|发布|上线|聚)"),
    re.compile(r"(?:时间|日期)(?:改到|改成|定在|定于|约在).{2,20}"),
    re.compile(r"(?i)\blet'?s meet\b.{0,40}"),
]
CLOSE_RE = re.compile(
    r"(?:已经|已)(?:发|给|传|交|提交|更新|整理|完成|搞定|处理|办|订|买|寄|回)|发你了|发过去了|发给你了|搞定了|弄好了|做完了|完成了|办好了|(?i:\b(?:done|sent|finished)\b)"
)

BASE_CONFIDENCE = {"commitment": 0.6, "request": 0.55, "preference": 0.6, "fact": 0.5, "plan": 0.5}

STOP_CHARS = set("我你您他她它们的了把吗呢吧啊和与也就都很是在有个这那给")
TIME_BIGRAMS = {"今天", "明天", "后天", "今晚", "明晚", "下周", "这周", "上午", "下午", "晚上", "周一", "周二",
                "周三", "周四", "周五", "周六", "周日", "月底", "之前", "下班", "班前", "尽快", "马上"}


@dataclass
class EventView:
    id: str
    channel: str
    when: datetime
    text: str
    sender: str
    is_me: bool
    counterparts: list[str]
    is_group: bool
    is_service: bool
    conversation: str
    sensitivity: str

    @classmethod
    def from_row(cls, row: dict) -> "EventView":
        participants = json.loads(row.get("participants") or "[]")
        is_me = row["direction"] == "outbound"
        if is_me:
            counterparts = [p.get("display_name") or p.get("handle") for p in participants if p.get("role") in {"to", "cc"}]
        else:
            counterparts = [ME]
        if row.get("is_group"):
            counterparts = [row["conversation"]] if is_me else [ME]
        return cls(
            id=row["id"],
            channel=row["channel"],
            when=datetime.fromisoformat(row["ts"]),
            text=row["content_text"],
            sender=ME if is_me else (row.get("sender") or "未知"),
            is_me=is_me,
            counterparts=[c for c in counterparts if c] or [row.get("conversation") or "未知"],
            is_group=bool(row.get("is_group")),
            is_service=bool(row.get("is_service")),
            conversation=row.get("conversation") or "",
            sensitivity=row.get("sensitivity") or "personal",
        )


def clauses(text: str) -> list[tuple[str, bool]]:
    """切成小句，并标记是否问句。"""
    out = []
    for m in CLAUSE_RE.finditer(text):
        raw = m.group(0).strip()
        if not raw:
            continue
        question = raw[-1] in "？?" or bool(re.search(r"(吗|么|嘛|呢)[。！？!?，,]?$", raw))
        body = LEAD_FILLER_RE.sub("", raw).strip(TRAIL_PUNCT)
        if body:
            out.append((body, question))
    return out


def keywords(text: str) -> set[str]:
    """用于合并 / 关闭待办的关键词：中文二元组 + 英文词，去掉代词与时间词。"""
    grams = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        for i in range(len(run) - 1):
            g = run[i : i + 2]
            if not (set(g) & STOP_CHARS) and g not in TIME_BIGRAMS:
                grams.add(g)
    grams |= {w.lower() for w in re.findall(r"[A-Za-z0-9]{2,}", text)}
    return grams


def _item(kind: str, ev: EventView, subject: str, text: str, counterpart: str = "", due_text: str = "") -> MemoryItem:
    due = None
    if kind in {"commitment", "request", "plan"}:
        due = resolve_due(text, ev.when.date()) or resolve_due(due_text, ev.when.date())
    return MemoryItem(
        kind=kind,
        subject=subject,
        counterpart=counterpart,
        text=text.strip(TRAIL_PUNCT)[:120],
        confidence=BASE_CONFIDENCE[kind],
        due=due,
        status="open" if kind in {"commitment", "request"} else None,
        source_event_ids=[ev.id],
        observed_at=ev.when.astimezone(timezone.utc).isoformat(),
        conversation=ev.conversation,
        channel=ev.channel,
    )


def extract(ev: EventView) -> list[MemoryItem]:
    if ev.sensitivity == "confidential" or ev.is_service or not ev.text.strip():
        return []
    items: list[MemoryItem] = []
    counterpart = ev.counterparts[0]
    for clause, question in clauses(ev.text):
        has_action = re.search(ACTION, clause) is not None
        if not question and has_action and not NEGATION_RE.search(clause):
            if any(p.search(clause) for p in COMMIT_RES):
                to = ev.conversation if ev.is_group else counterpart
                items.append(_item("commitment", ev, ev.sender, clause, to, ev.text))
                continue
        if has_action and any(p.search(clause) for p in REQUEST_RES):
            if ev.is_group and not ev.is_me and not BROADCAST_RE.search(clause):
                pass  # 群里点名别人的事，不算找我
            elif not (ev.is_group and ev.is_me):
                items.append(_item("request", ev, ev.sender, clause, counterpart, ev.text))
                continue
        if not question:
            m = PREF_RE.search(clause) or PREF_EN_RE.search(clause)
            if m:
                items.append(_item("preference", ev, ev.sender, re.sub(r"^我|^I\s+", "", m.group(0))))
                continue
            m = next((r.search(clause) for r in FACT_RES if r.search(clause)), None)
            if m:
                items.append(_item("fact", ev, ev.sender, re.sub(r"^我", "", m.group(0))))
                continue
            if any(p.search(clause) for p in PLAN_RES):
                who = ev.conversation if ev.is_group else (counterpart if ev.is_me else ev.sender)
                items.append(_item("plan", ev, who, clause))
    return items


def is_closing(text: str) -> bool:
    return bool(CLOSE_RE.search(text))
