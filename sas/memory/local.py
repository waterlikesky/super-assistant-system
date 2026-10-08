"""默认记忆后端：存在同一个 sas.db 的 memories / people 表里。

演进规则
- 合并：同类、同主体、同对象且关键词 Jaccard ≥ 0.5 视为同一条；置信度按 noisy-OR 叠加
  （1-(1-旧)(1-新)），evidence +1，last_seen 前移
- 矛盾：偏好极性相反（「喜欢咖啡」→「不喜欢咖啡」）时，旧条置信度 ×0.3
- 衰减：effective = confidence × 0.5^(距 last_seen 天数 / 半衰期)，半衰期见 base.HALF_LIFE_DAYS
- 关闭：之后同一会话里出现「已经发你了 / 搞定了」且关键词重叠，对应承诺 / 请求自动 done
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sas.connectors.base import short_hash
from sas.store import Store

from .base import HALF_LIFE_DAYS, ME, TODO_KINDS, MemoryBackend, MemoryItem
from .rules import EventView, is_closing, keywords

NEG_RE = re.compile(r"不太|不|讨厌|没|别|don't|do not|hate")


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _polarity_object(text: str) -> tuple[bool, str]:
    neg = bool(NEG_RE.search(text))
    obj = re.sub(r"最|比较|很|超|特别|一直|喜欢|爱吃|爱喝|爱看|偏好|习惯|讨厌|吃不了|喝不了|吃|喝", "", NEG_RE.sub("", text))
    return neg, obj.strip()


def decayed(confidence: float, kind: str, last_seen: str, now: datetime) -> float:
    try:
        seen = datetime.fromisoformat(last_seen)
    except (TypeError, ValueError):
        return confidence
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    days = max(0.0, (now - seen).total_seconds() / 86400)
    return round(confidence * 0.5 ** (days / HALF_LIFE_DAYS.get(kind, 90.0)), 4)


class LocalMemory(MemoryBackend):
    name = "local"

    def __init__(self, store: Store) -> None:
        self.store = store
        self.table = store.db["memories"]

    # ---------- 写入 ----------
    def _row_to_item(self, row: dict, now: datetime | None = None) -> MemoryItem:
        item = MemoryItem(
            id=row["id"], kind=row["kind"], subject=row["subject"], counterpart=row["counterpart"] or "",
            text=row["text"], confidence=row["confidence"], due=row["due"] or None, status=row["status"] or None,
            source_event_ids=json.loads(row["source_event_ids"] or "[]"), conversation=row["conversation"] or "",
            channel=row["channel"] or "", evidence=row["evidence"], first_seen=row["first_seen"], last_seen=row["last_seen"],
        )
        if now is not None:
            item.effective_confidence = decayed(item.confidence, item.kind, item.last_seen, now)
        return item

    def write(self, items: list[MemoryItem]) -> int:
        created = 0
        for item in items:
            created += self._write_one(item)
        return created

    def _write_one(self, item: MemoryItem) -> int:
        now_iso = datetime.now().isoformat(timespec="seconds")
        kw = keywords(item.text)
        where = "kind = ? and subject = ? and counterpart = ?"
        params = [item.kind, item.subject, item.counterpart]
        if item.kind in TODO_KINDS:
            where += " and status = 'open'"
        for row in self.table.rows_where(where, params):
            if item.kind == "preference":
                neg_new, obj_new = _polarity_object(item.text)
                neg_old, obj_old = _polarity_object(row["text"])
                if obj_new and obj_new == obj_old and neg_new != neg_old:
                    self.table.update(row["id"], {"confidence": round(row["confidence"] * 0.3, 4), "updated_at": now_iso})
                    continue
            same = row["text"] == item.text or _jaccard(kw, keywords(row["text"])) >= 0.5
            if not same:
                continue
            sources = list(dict.fromkeys(json.loads(row["source_event_ids"] or "[]") + item.source_event_ids))
            if len(sources) == len(json.loads(row["source_event_ids"] or "[]")):
                return 0  # 同一条消息重复抽取，不重复加分
            self.table.update(
                row["id"],
                {
                    "confidence": round(1 - (1 - row["confidence"]) * (1 - item.confidence), 4),
                    "evidence": row["evidence"] + 1,
                    "last_seen": max(row["last_seen"], item.observed_at),
                    "first_seen": min(row["first_seen"], item.observed_at),
                    "due": item.due or row["due"],
                    "text": item.text if item.observed_at >= row["last_seen"] else row["text"],
                    "source_event_ids": json.dumps(sources, ensure_ascii=False),
                    "updated_at": now_iso,
                },
            )
            return 0
        item.id = item.kind[0] + "-" + short_hash(item.kind, item.subject, item.counterpart, item.text, item.observed_at, n=7)
        self.table.insert(
            {
                "id": item.id, "kind": item.kind, "subject": item.subject, "counterpart": item.counterpart,
                "text": item.text, "confidence": item.confidence, "evidence": 1,
                "first_seen": item.observed_at, "last_seen": item.observed_at, "due": item.due or "",
                "status": item.status or "", "source_event_ids": json.dumps(item.source_event_ids, ensure_ascii=False),
                "conversation": item.conversation, "channel": item.channel, "updated_at": now_iso,
            },
            ignore=True,
        )
        return 1

    def observe_closure(self, ev: EventView) -> list[str]:
        """后续消息说「已经发你了」等 → 关闭同会话里关键词重叠的未完成事项。"""
        if not is_closing(ev.text):
            return []
        kw = keywords(ev.text)
        if ev.is_me:
            where = "conversation = ? and status = 'open' and ((kind = 'commitment' and subject = ?) or (kind = 'request' and counterpart = ?))"
            params = [ev.conversation, ME, ME]
        else:
            where = "conversation = ? and status = 'open' and kind = 'commitment' and subject = ?"
            params = [ev.conversation, ev.sender]
        closed = []
        for row in self.table.rows_where(where, params):
            if row["first_seen"] < ev.when.astimezone(timezone.utc).isoformat() and kw & keywords(row["text"]):
                sources = json.loads(row["source_event_ids"] or "[]") + [ev.id]
                self.table.update(row["id"], {"status": "done", "source_event_ids": json.dumps(sources, ensure_ascii=False)})
                closed.append(row["id"])
        return closed

    # ---------- 读取 ----------
    def list(self, *, kind=None, subject=None, counterpart=None, status=None, now=None, min_confidence=0.0):
        now = now or datetime.now(timezone.utc)
        clauses, params = [], []
        if kind:
            kinds = (kind,) if isinstance(kind, str) else tuple(kind)
            clauses.append(f"kind in ({','.join('?' * len(kinds))})")
            params += list(kinds)
        for col, value in (("subject", subject), ("counterpart", counterpart), ("status", status)):
            if value is not None:
                clauses.append(f"{col} = ?")
                params.append(value)
        rows = self.table.rows_where(" and ".join(clauses) or None, params or None)
        items = [self._row_to_item(r, now) for r in rows]
        items = [i for i in items if (i.effective_confidence or 0) >= min_confidence]
        items.sort(key=lambda i: (i.due or "9999", -(i.effective_confidence or 0)))
        return items

    def search(self, query: str, *, limit: int = 10, now: datetime | None = None) -> list[MemoryItem]:
        now = now or datetime.now(timezone.utc)
        kw = keywords(query) | {query.strip()}
        scored = []
        for row in self.table.rows:
            blob = f"{row['subject']} {row['counterpart']} {row['text']}"
            hit = sum(1 for k in kw if k and k in blob)
            if hit:
                item = self._row_to_item(row, now)
                scored.append((hit, item.effective_confidence or 0, item))
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [t[2] for t in scored[:limit]]

    def close(self, item_id: str) -> bool:
        rows = list(self.table.rows_where("id = ? or id like ?", [item_id, f"{item_id}%"]))
        if len(rows) != 1:
            return False
        self.table.update(rows[0]["id"], {"status": "done", "updated_at": datetime.now().isoformat(timespec="seconds")})
        return True


# ---------- 人物 ----------

def person_key(name: str) -> str:
    return re.sub(r"\s+", "", name).lower()


def update_people(store: Store, rows: list[dict]) -> int:
    """按显示名聚合人物（跨渠道同名即合并）。服务号、群名不算人。"""
    table = store.db["people"]
    touched = set()
    for row in sorted(rows, key=lambda r: r["epoch"]):
        if row["is_service"]:
            continue
        ev = EventView.from_row(row)
        ts = row["ts"]
        names = [ev.sender] if not ev.is_me else ([] if ev.is_group else ev.counterparts)
        for name in names:
            if not name or name == ME or name == "未知":
                continue
            key = person_key(name)
            try:
                p = table.get(key)
            except Exception:
                p = {"key": key, "name": name, "aliases": "[]", "channels": "[]", "first_seen": ts,
                     "last_seen": ts, "msg_in": 0, "msg_out": 0, "last_event_id": row["id"]}
            channels = sorted(set(json.loads(p["channels"])) | {row["channel"]})
            p.update(
                channels=json.dumps(channels, ensure_ascii=False),
                first_seen=min(p["first_seen"], ts),
                msg_in=p["msg_in"] + (0 if ev.is_me else 1),
                msg_out=p["msg_out"] + (1 if ev.is_me else 0),
            )
            if ts >= p["last_seen"]:
                p.update(last_seen=ts, last_event_id=row["id"])
            table.upsert(p, pk="key")
            touched.add(key)
    return len(touched)
