"""从「明天 / 周五前 / 下周三 / 10月15日 / 15号 / 月底」里解析出日期（相对消息发送时间）。"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

WEEKDAY = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6, "末": 5}
EN_WEEKDAY = {d.lower(): i for i, d in enumerate(calendar.day_name)}

MONTH_DAY_RE = re.compile(r"(\d{1,2})月(\d{1,2})[日号]")
DAY_RE = re.compile(r"(?<![\d月])(\d{1,2})[号日](?!\d)")
WEEK_RE = re.compile(r"(下下|下|这|本|上)?(?:周|星期|礼拜)([一二三四五六日天末])")
EN_WEEK_RE = re.compile(r"(?i)\b(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b")


def resolve_due(text: str, ref: date) -> str | None:
    if not text:
        return None
    m = MONTH_DAY_RE.search(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            target = date(ref.year, month, day)
        except ValueError:
            return None
        if (ref - target).days > 30:
            target = date(ref.year + 1, month, day)
        return target.isoformat()

    m = WEEK_RE.search(text)
    if m:
        prefix, wd = m.group(1) or "", WEEKDAY[m.group(2)]
        week_start = ref - timedelta(days=ref.weekday())
        if prefix in ("下",):
            target = week_start + timedelta(days=7 + wd)
        elif prefix == "下下":
            target = week_start + timedelta(days=14 + wd)
        elif prefix == "上":
            target = week_start + timedelta(days=wd - 7)
        elif prefix in ("这", "本"):
            target = week_start + timedelta(days=wd)
        else:
            target = week_start + timedelta(days=wd)
            if target < ref:
                target += timedelta(days=7)
        return target.isoformat()

    for word, delta in (("大后天", 3), ("后天", 2), ("明早", 1), ("明晚", 1), ("明天", 1), ("明日", 1),
                        ("今天", 0), ("今晚", 0), ("今日", 0), ("下班前", 0), ("马上", 0), ("这就", 0)):
        if word in text:
            return (ref + timedelta(days=delta)).isoformat()
    if "月底" in text:
        return date(ref.year, ref.month, calendar.monthrange(ref.year, ref.month)[1]).isoformat()

    m = DAY_RE.search(text)
    if m:
        day = int(m.group(1))
        year, month = ref.year, ref.month
        if day < ref.day:
            month += 1
            if month > 12:
                year, month = year + 1, 1
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None

    lowered = text.lower()
    if "tomorrow" in lowered:
        return (ref + timedelta(days=1)).isoformat()
    if "today" in lowered or "tonight" in lowered:
        return ref.isoformat()
    m = EN_WEEK_RE.search(text)
    if m:
        wd = EN_WEEKDAY[m.group(2).lower()]
        delta = (wd - ref.weekday()) % 7
        if m.group(1):
            delta = delta + 7 if delta else 7
        return (ref + timedelta(days=delta)).isoformat()
    return None
