"""入库：脱敏落盘、增量 + 去重、FTS5 中文检索、不联网。"""

import shutil
import socket
import subprocess

from sas.ingest import ingest_path

from .conftest import EXPORTS, ROOT

SECRETS = [
    "13912345678", "110101199003071234", "13800001234", "6225 8812 3456 7898", "482913",
    "SF1234567890123", "13700001111", "13600002222", "alice@example.com", "lisa@example.com",
]


def test_ingest_all_fixtures(ingested, store):
    assert ingested.new == 28
    assert set(ingested.by_connector) == {"wechat_txt", "wechat_csv", "email_mbox", "email_eml", "sms_xml", "sms_csv", "dingtalk"}
    assert {r["channel"] for r in store.query("select distinct channel from events")} == {"wechat", "email", "sms", "dingtalk"}


def test_no_plaintext_secrets_anywhere_in_db(ingested, config, store):
    store.db.conn.commit()
    raw = config.db_path.read_bytes().decode("utf-8", errors="ignore")
    for secret in SECRETS:
        assert secret not in raw, secret
    assert "[REDACTED_CONFIDENTIAL_OTP_MESSAGE]" in raw


def test_reingest_is_noop_and_force_still_dedupes(ingested, config, store, memory):
    again = ingest_path(EXPORTS, store=store, memory=memory, config=config, recursive=True)
    assert again.new == 0 and again.unchanged == again.files
    forced = ingest_path(EXPORTS, store=store, memory=memory, config=config, recursive=True, force=True)
    assert forced.new == 0 and forced.duplicate == 28 and forced.memories == 0
    assert store.count() == 28


def test_incremental_export_only_adds_new_messages(tmp_path, config, store, memory):
    src = tmp_path / "老王.txt"
    shutil.copy(EXPORTS / "wechat" / "老王.txt", src)
    first = ingest_path(src, store=store, memory=memory, config=config)
    assert first.new == 7
    with src.open("a", encoding="utf-8") as fh:
        fh.write("2026-10-07 08:00:00 老王\n明天下午三点开会别忘了\n")
    second = ingest_path(src, store=store, memory=memory, config=config)
    assert (second.new, second.duplicate) == (1, 7)


def test_overlapping_exports_dedupe(tmp_path, config, store, memory):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    shutil.copy(EXPORTS / "sms" / "messages.csv", a / "messages.csv")
    shutil.copy(EXPORTS / "sms" / "messages.csv", b / "messages-copy.csv")
    ingest_path(a, store=store, memory=memory, config=config)
    second = ingest_path(b, store=store, memory=memory, config=config)
    assert second.new == 0 and second.duplicate == 2


def test_fts_uses_trigram_and_finds_chinese(ingested, store):
    sql = store.query("select sql from sqlite_master where name = 'events_fts'")[0]["sql"]
    assert "trigram" in sql
    assert [r["sender"] for r in store.search(["报价单"])] == ["我", "我"]  # ≥3 字：MATCH
    assert store.search(["香菜"])[0]["sender"] == "老王"  # 2 字：trigram 表上的 LIKE
    assert store.search(["接口文档"])[0]["channel"] == "dingtalk"
    assert store.search(["体检报告"], person="妈妈")
    assert not store.search(["体检报告"], person="老王")
    assert store.search(["不存在的词语"]) == []


def test_fts_tracks_new_rows(ingested, store, config, memory, tmp_path):
    p = tmp_path / "新朋友.txt"
    p.write_text("2026-10-07 09:00:00 新朋友\n我们在西溪湿地见\n", encoding="utf-8")
    ingest_path(p, store=store, memory=memory, config=config)
    assert store.search(["西溪湿地"])


def test_ingest_never_opens_sockets(monkeypatch, config, store, memory):
    def refuse(*_a, **_k):
        raise AssertionError("意外的网络连接")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    report = ingest_path(EXPORTS, store=store, memory=memory, config=config, recursive=True)
    assert report.new == 28


def test_data_dir_is_gitignored():
    for path in ("data/sas.db", "data/processed/events.jsonl"):
        assert subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT, check=False).returncode == 0
