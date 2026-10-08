"""微信 / 短信 / 钉钉 / ChannelEvent connector：每个夹具都能解析、过 schema、方向正确。"""

from pathlib import Path

import pytest

from sas.connectors import REGISTRY, ParseContext, detect, iter_files, resolve_source
from sas.ingest import prepare
from sas.schema import validate_event

from .conftest import EXPORTS, ROOT


def parse(name: str, path: Path, config):
    ctx = ParseContext(config=config, consent_tag="t")
    events = list(REGISTRY[name].parse(path, ctx))
    for e in events:
        validate_event(e)
        validate_event(prepare(dict(e)))
    return events, ctx


@pytest.mark.parametrize(
    "rel, expected",
    [
        ("wechat/老王.txt", "wechat_txt"),
        ("wechat/读书会.csv", "wechat_csv"),
        ("email/archive.mbox", "email_mbox"),
        ("email/weekend-hike.eml", "email_eml"),
        ("sms/sms-backup.xml", "sms_xml"),
        ("sms/messages.csv", "sms_csv"),
        ("dingtalk/项目周会群.csv", "dingtalk"),
    ],
)
def test_autodetect_every_fixture(rel, expected):
    assert detect(EXPORTS / rel, resolve_source(None)).name == expected


def test_every_registered_connector_is_read_only():
    for c in REGISTRY.values():
        assert c.read_only
        assert not any(hasattr(c, m) for m in ("send", "reply", "post"))


def test_wechat_txt(config):
    events, ctx = parse("wechat_txt", EXPORTS / "wechat" / "老王.txt", config)
    assert len(events) == 7 and not ctx.skipped
    first = events[0]
    assert first["conversation"] == "老王" and first["direction"] == "inbound"
    assert first["timestamp"] == "2026-10-05T21:40:12+08:00"
    assert events[1]["direction"] == "outbound"
    assert first["metadata"]["is_group"] is False
    assert "\n" not in events[0]["content_text"].strip()


def test_wechat_txt_name_first_header_and_me_alias(tmp_path):
    from sas.config import Config

    path = tmp_path / "小李.txt"
    path.write_text("小李 2026-10-01 08:00:00\n早\n\n水如天 2026-10-01 08:01:00\n早，我明天把文件发你\n", encoding="utf-8")
    cfg = Config.load(env={}, me="水如天", db_path=tmp_path / "x.db")
    events = list(REGISTRY["wechat_txt"].parse(path, ParseContext(config=cfg, consent_tag="t")))
    assert [e["direction"] for e in events] == ["inbound", "outbound"]


def test_wechat_csv_group_keeps_text_only(config):
    events, _ = parse("wechat_csv", EXPORTS / "wechat" / "读书会.csv", config)
    assert len(events) == 5  # 图片 / 撤回系统消息被忽略
    assert all(e["metadata"]["is_group"] for e in events)
    assert sum(e["direction"] == "outbound" for e in events) == 2
    assert {p["display_name"] for e in events for p in e["participants"]} >= {"小美", "阿杰", "我"}


def test_sms_xml(config):
    events, ctx = parse("sms_xml", EXPORTS / "sms" / "sms-backup.xml", config)
    assert len(events) == 5
    assert ("sms-backup.xml#6", "正文为空") in ctx.skipped
    mom = next(e for e in events if e["conversation"] == "妈妈")
    assert mom["participants"][0]["handle"].startswith("tel:")
    assert "13700001111" not in str(mom)
    mms = next(e for e in events if "开会" in e["content_text"])
    assert mms["direction"] == "inbound"
    bank = events[0]
    assert bank["metadata"]["is_service"] is True
    assert prepare(dict(bank))["sensitivity"] == "confidential"


def test_sms_csv(config):
    events, _ = parse("sms_csv", EXPORTS / "sms" / "messages.csv", config)
    assert [e["direction"] for e in events] == ["inbound", "outbound"]
    assert events[0]["conversation"] == "李医生"


def test_dingtalk_csv_groups_by_conversation(config):
    events, ctx = parse("dingtalk", EXPORTS / "dingtalk" / "项目周会群.csv", config)
    assert len(events) == 5 and len(ctx.skipped) == 1
    convs = {e["conversation"] for e in events}
    assert convs == {"项目周会群", "赵经理"}
    assert next(e for e in events if e["conversation"] == "赵经理")["metadata"]["is_group"] is False


def test_dingtalk_xlsx(tmp_path, config):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["时间", "发送人", "内容"])
    ws.append(["2026-10-06 09:00", "赵经理", "大家周三前提交周报"])
    path = tmp_path / "钉钉导出.xlsx"
    wb.save(path)
    assert detect(path, resolve_source("auto")).name == "dingtalk"
    events, _ = parse("dingtalk", path, config)
    assert events[0]["content_text"] == "大家周三前提交周报"


def test_channel_event_json(config):
    events, _ = parse("events", ROOT / "fixtures" / "events" / "01_email.json", config)
    assert events[0]["id"] == "email:demo-001"


def test_ids_are_stable_and_do_not_leak_numbers(config):
    a, _ = parse("wechat_txt", EXPORTS / "wechat" / "老王.txt", config)
    b, _ = parse("wechat_txt", EXPORTS / "wechat" / "老王.txt", config)
    assert [e["id"] for e in a] == [e["id"] for e in b]
    assert len({e["id"] for e in a}) == len(a)


def test_iter_files_skips_hidden(tmp_path):
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "a.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("x")
    (tmp_path / "c.txt").write_text("x")
    assert [p.name for p in iter_files(tmp_path)] == ["c.txt"]
    assert sorted(p.name for p in iter_files(tmp_path, recursive=True)) == ["b.txt", "c.txt"]
