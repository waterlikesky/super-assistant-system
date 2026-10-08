"""通讯录 → 人物别名合并。

规则（幂等，每次摄入后都跑一遍）：
1. 联系人的姓名 / 昵称 / N 字段任一等于某个人物名，或其电话哈希出现在该人物的消息参与方里，
   或打码邮箱匹配且显示名与别名有重叠 → 视为同一人；
2. 命中多个人物时合并：保留消息最多的那个名字作显示名，其余名字进 aliases，往来计数相加；
3. 记忆里的 subject / counterpart 改写为显示名，这样 todos / person / digest 自动聚到一起；
4. 通讯录里没出现在消息中的人不会进入人物列表（不把整个通讯录灌进来）。
"""

from __future__ import annotations

import json

from sas.connectors.base import short_hash
from sas.connectors.vcard import Contact
from sas.store import Store


def save_contacts(store: Store, contacts: list[Contact]) -> int:
    rows = [
        {
            "key": short_hash(c.name, *sorted(c.handles), n=16),
            "name": c.name,
            "aliases": json.dumps(sorted(c.aliases), ensure_ascii=False),
            "handles": json.dumps(sorted(c.handles), ensure_ascii=False),
            "org": c.org,
        }
        for c in contacts
    ]
    store.db["contacts"].upsert_all(rows, pk="key")
    return len(rows)


def _handle_index(store: Store) -> dict[str, set[str]]:
    """参与方 handle → 出现过的显示名（不含「我」）。"""
    index: dict[str, set[str]] = {}
    sql = """select distinct json_extract(p.value, '$.handle') h, json_extract(p.value, '$.display_name') n
             from events, json_each(events.participants) p where json_extract(p.value, '$.role') != 'self'"""
    for row in store.query(sql):
        if row["h"] and row["n"] and row["n"] != "我":
            index.setdefault(row["h"], set()).add(row["n"])
    return index


def link_contacts(store: Store) -> int:
    if "contacts" not in store.db.table_names() or not store.count("contacts"):
        return 0
    people = {p["name"]: p for p in store.query("select * from people")}
    by_alias = {}
    for p in people.values():
        for alias in json.loads(p.get("aliases") or "[]") + [p["name"]]:
            by_alias[alias] = p["name"]
    handles = _handle_index(store)
    merged = 0
    for c in store.query("select * from contacts"):
        aliases = set(json.loads(c["aliases"]))
        names = {by_alias[a] for a in aliases if a in by_alias}
        for h in json.loads(c["handles"]):
            for n in handles.get(h, ()):
                # 电话哈希是精确匹配；打码邮箱（al***@x.com）可能撞车，还要求显示名与别名有重叠
                if h.startswith("tel:") or any(a.lower() in n.lower() or n.lower() in a.lower() for a in aliases):
                    if by_alias.get(n, n) in people:
                        names.add(by_alias.get(n, n))
        names = {n for n in names if n in people}
        if not names:
            continue
        canonical = max(names, key=lambda n: (people[n]["msg_in"] + people[n]["msg_out"], n))
        target = dict(people[canonical])
        all_aliases = set(json.loads(target.get("aliases") or "[]")) | aliases | names
        channels = set(json.loads(target["channels"]))
        for other in names - {canonical}:
            o = people.pop(other)
            all_aliases |= set(json.loads(o.get("aliases") or "[]"))
            channels |= set(json.loads(o["channels"]))
            target["msg_in"] += o["msg_in"]
            target["msg_out"] += o["msg_out"]
            target["first_seen"] = min(target["first_seen"], o["first_seen"])
            if o["last_seen"] > target["last_seen"]:
                target["last_seen"], target["last_event_id"] = o["last_seen"], o["last_event_id"]
            store.db["people"].delete(o["key"])
            merged += 1
        all_aliases.discard(canonical)
        target.update(aliases=json.dumps(sorted(all_aliases), ensure_ascii=False),
                      channels=json.dumps(sorted(channels), ensure_ascii=False), org=c["org"] or target.get("org") or "")
        store.db["people"].upsert(target, pk="key", alter=True)
        people[canonical] = target
        for alias in all_aliases:
            by_alias[alias] = canonical
            for col in ("subject", "counterpart"):
                store.db.execute(f"update memories set {col} = ? where {col} = ?", [canonical, alias])
    store.db.conn.commit()
    return merged


def names_of(store: Store, name: str) -> set[str]:
    """一个人物的全部叫法（显示名 + 别名）。"""
    rows = store.query("select name, aliases from people where name = ?", [name])
    if not rows:
        return {name}
    return {rows[0]["name"], *json.loads(rows[0].get("aliases") or "[]")}
