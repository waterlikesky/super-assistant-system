"""本地存储：一个 SQLite 文件，全部经 sqlite-utils 建表 / upsert / FTS5。

中文检索：FTS5 trigram 分词器（SQLite ≥ 3.34）。≥3 字的词走 MATCH，
1–2 字的词走 trigram 表上的 LIKE（同样只扫 FTS 表，无需中文分词库）。
生成的 sas.db 可以直接 `datasette data/sas.db` 浏览。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

import sqlite_utils

EVENT_COLUMNS = {
    "id": str,
    "channel": str,
    "direction": str,
    "ts": str,
    "epoch": int,
    "day": str,
    "conversation": str,
    "thread_id": str,
    "sender": str,
    "is_group": int,
    "is_service": int,
    "content_text": str,
    "sensitivity": str,
    "consent_tag": str,
    "raw_ref": str,
    "participants": str,
    "metadata": str,
    "source": str,
    "ingested_at": str,
}
FTS_COLUMNS = ["content_text", "sender", "conversation"]


def sender_of(event: dict) -> str:
    for p in event.get("participants") or []:
        if p.get("role") in {"from", "self"}:
            return p.get("display_name") or p.get("handle") or ""
    return ""


def recipients_of(event: dict) -> list[str]:
    return [
        p.get("display_name") or p.get("handle") or ""
        for p in event.get("participants") or []
        if p.get("role") in {"to", "cc"}
    ]


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite_utils.Database(str(path))
        self._ensure_schema()

    # ---------- schema ----------
    def _ensure_schema(self) -> None:
        db = self.db
        db["events"].create(EVENT_COLUMNS, pk="id", if_not_exists=True)
        for cols in (["day"], ["conversation"], ["sender"], ["epoch"]):
            db["events"].create_index(cols, if_not_exists=True)
        if "events_fts" not in db.table_names():
            db["events"].enable_fts(FTS_COLUMNS, tokenize="trigram", create_triggers=True)
        db["sources"].create(
            {"path": str, "sha256": str, "size": int, "connector": str, "events": int, "last_ingested": str},
            pk="path",
            if_not_exists=True,
        )
        db["people"].create(
            {
                "key": str, "name": str, "aliases": str, "channels": str, "first_seen": str,
                "last_seen": str, "msg_in": int, "msg_out": int, "last_event_id": str,
            },
            pk="key",
            if_not_exists=True,
        )
        db["memories"].create(
            {
                "id": str, "kind": str, "subject": str, "counterpart": str, "text": str,
                "confidence": float, "evidence": int, "first_seen": str, "last_seen": str,
                "due": str, "status": str, "source_event_ids": str, "conversation": str,
                "channel": str, "updated_at": str,
            },
            pk="id",
            if_not_exists=True,
        )
        db["memories"].create_index(["kind", "status"], if_not_exists=True)
        db["memories"].create_index(["subject"], if_not_exists=True)

    # ---------- sources（增量） ----------
    def source_unchanged(self, path: Path, sha256: str) -> bool:
        try:
            row = self.db["sources"].get(str(path.resolve()))
        except sqlite_utils.db.NotFoundError:
            return False
        return row["sha256"] == sha256

    def record_source(self, path: Path, sha256: str, connector: str, events: int) -> None:
        self.db["sources"].upsert(
            {
                "path": str(path.resolve()), "sha256": sha256, "size": path.stat().st_size,
                "connector": connector, "events": events, "last_ingested": datetime.now().isoformat(timespec="seconds"),
            },
            pk="path",
        )

    # ---------- events ----------
    def to_row(self, event: dict, source: str, tz) -> dict:
        when = datetime.fromisoformat(event["timestamp"])
        meta = event.get("metadata") or {}
        return {
            "id": event["id"],
            "channel": event["channel"],
            "direction": event["direction"],
            "ts": when.astimezone(tz).isoformat(),  # 统一到配置时区，展示与按天统计一致
            "epoch": int(when.timestamp()),
            "day": when.astimezone(tz).date().isoformat(),
            "conversation": event.get("conversation") or meta.get("subject") or "",
            "thread_id": event.get("thread_id") or "",
            "sender": "我" if event["direction"] == "outbound" else sender_of(event),
            "is_group": int(bool(meta.get("is_group"))),
            "is_service": int(bool(meta.get("is_service"))),
            "content_text": event["content_text"],
            "sensitivity": event["sensitivity"],
            "consent_tag": event["consent_tag"],
            "raw_ref": event.get("raw_ref") or "",
            "participants": json.dumps(event.get("participants") or [], ensure_ascii=False),
            "metadata": json.dumps(meta, ensure_ascii=False),
            "source": source,
            "ingested_at": datetime.now().isoformat(timespec="seconds"),
        }

    def insert_events(self, rows: list[dict]) -> list[dict]:
        """去重写入：已存在的 id 不覆盖。返回真正新增的行。"""
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        existing: set[str] = set()
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            marks = ",".join("?" * len(chunk))
            existing |= {r[0] for r in self.db.execute(f"select id from events where id in ({marks})", chunk)}
        fresh, seen = [], set(existing)
        for row in rows:
            if row["id"] not in seen:
                seen.add(row["id"])
                fresh.append(row)
        if fresh:
            self.db["events"].insert_all(fresh, pk="id", ignore=True)
        return fresh

    def count(self, table: str = "events") -> int:
        return self.db[table].count if table in self.db.table_names() else 0

    def query(self, sql: str, params: Iterable = ()) -> list[dict]:
        return list(self.db.query(sql, list(params)))

    def search(
        self,
        terms: list[str],
        *,
        person: str | None = None,
        since_day: str | None = None,
        limit: int = 8,
        include_confidential: bool = True,
    ) -> list[dict]:
        """全文检索：命中越多词、词越长、越新，排得越前。"""
        terms = [t for t in dict.fromkeys(t.strip() for t in terms) if t]
        where, params = [], []
        if terms:
            # FTS5 的 MATCH 不能和其他条件 OR，在一起：逐词取 rowid 再合并
            rowids: set[int] = set()
            for t in terms:
                if len(t) >= 3:
                    sql, args = "select rowid from events_fts where events_fts match ?", ['"' + t.replace('"', '""') + '"']
                else:
                    sql = "select rowid from events_fts where content_text like ? or sender like ? or conversation like ?"
                    args = [f"%{t}%"] * 3
                rowids |= {r[0] for r in self.db.execute(sql, args)}
            if not rowids:
                return []
            where.append(f"e.rowid in ({','.join(map(str, rowids))})")
        if person:
            where.append("(e.sender = ? or e.conversation = ? or e.participants like ?)")
            params += [person, person, f'%"display_name": "{person}"%']
        if since_day:
            where.append("e.day >= ?")
            params.append(since_day)
        if not include_confidential:
            where.append("e.sensitivity != 'confidential'")
        sql = "select e.* from events e"
        if where:
            sql += " where " + " and ".join(where)
        sql += " order by e.epoch desc limit 400"
        rows = self.query(sql, params)

        def score(row: dict) -> tuple:
            blob = f"{row['content_text']} {row['sender']} {row['conversation']}"
            hit = sum(len(t) for t in terms if t in blob)
            return (hit, row["epoch"])

        rows.sort(key=score, reverse=True)
        return rows[:limit]

    def events_on(self, day: str) -> list[dict]:
        return self.query("select * from events where day = ? order by epoch", [day])

    def conversation_tail(self, channel: str, conversation: str, limit: int = 6) -> list[dict]:
        rows = self.query(
            "select * from events where channel = ? and conversation = ? order by epoch desc limit ?",
            [channel, conversation, limit],
        )
        return list(reversed(rows))

    def latest_day(self) -> str | None:
        row = self.query("select max(day) as d from events")
        return row[0]["d"] if row else None
