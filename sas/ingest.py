"""摄入管道：识别格式 → 解析 → schema 校验 → 脱敏 → 去重入库 → 抽取记忆 → 更新人物。

增量：同一路径文件内容（sha256）没变就整文件跳过；内容变了也只有新 id 的消息会入库、
只有新消息会进入记忆抽取。
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sas.config import Config
from sas.connectors import ParseContext, SkipRecord, detect, iter_files, resolve_source
from sas.memory import CompositeMemory, EventView, extract, update_people
from sas.redact import classify_sensitivity, redact_event
from sas.schema import ValidationError, validate_event
from sas.store import Store


@dataclass
class IngestReport:
    files: int = 0
    unchanged: int = 0
    parsed: int = 0
    new: int = 0
    duplicate: int = 0
    memories: int = 0
    closed: int = 0
    people: int = 0
    embedded: int = 0
    mirrored: int = 0
    by_connector: Counter = field(default_factory=Counter)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    unrecognized: list[str] = field(default_factory=list)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare(event: dict) -> dict:
    """校验 → 敏感度升级 → 脱敏 → 再校验。返回可入库的事件。"""
    validate_event(event)
    event["sensitivity"] = classify_sensitivity(event.get("content_text", ""), event.get("sensitivity", "personal"))
    redacted = redact_event(event)
    validate_event(redacted)
    return redacted


def ingest_path(
    path: str | Path,
    *,
    store: Store,
    memory: CompositeMemory,
    config: Config,
    source: str | None = None,
    recursive: bool = False,
    consent_tag: str | None = None,
    force: bool = False,
    vectors=None,
) -> IngestReport:
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"路径不存在: {root}")
    candidates = resolve_source(source)
    consent = (consent_tag or "").strip() or f"cli:{date.today().isoformat()}"
    report = IngestReport()
    tz = config.tzinfo()
    new_rows: list[dict] = []

    for file in iter_files(root, recursive=recursive):
        connector = detect(file, candidates)
        if connector is None:
            report.unrecognized.append(str(file))
            continue
        report.files += 1
        sha = file_sha256(file)
        if not force and store.source_unchanged(file, sha):
            report.unchanged += 1
            continue
        ctx = ParseContext(config=config, consent_tag=consent, root=root if root.is_dir() else file.parent)
        rows = []
        try:
            for event in connector.parse(file, ctx):
                where = (event.get("metadata") or {}).get("source_name") or file.name
                try:
                    rows.append(store.to_row(prepare(event), connector.name, tz))
                except ValidationError as exc:
                    ctx.skip(where, f"不符合 schema（{exc.message}）")
        except SkipRecord as exc:
            ctx.skip(file.name, exc.reason)
        report.skipped += ctx.skipped
        report.parsed += len(rows)
        fresh = store.insert_events(rows)
        report.new += len(fresh)
        report.duplicate += len(rows) - len(fresh)
        report.by_connector[connector.name] += len(fresh)
        new_rows += fresh
        if vectors is not None and fresh:
            report.embedded += vectors.add(fresh)
        store.record_source(file, sha, connector.name, len(rows))

    learn(new_rows, store=store, memory=memory, report=report)
    return report


def learn(rows: list[dict], *, store: Store, memory: CompositeMemory, report: IngestReport | None = None) -> None:
    """记忆闭环：按时间顺序处理新消息 —— 先看它是否关闭了旧承诺，再抽新记忆。"""
    report = report or IngestReport()
    for row in sorted(rows, key=lambda r: r["epoch"]):
        ev = EventView.from_row(row)
        report.closed += len(memory.observe_closure(ev))
        report.memories += memory.write(extract(ev))
    report.people += update_people(store, rows)
    if memory.mirrors and rows:
        new_ids = {r["id"] for r in rows}
        changed = [i for i in memory.primary.list() if new_ids & set(i.source_event_ids)]
        names = {r["sender"] for r in rows} | {i.subject for i in changed} | {i.counterpart for i in changed}
        report.mirrored = sum(memory.sync(store, names=names, items=changed).values())
