"""记忆闭环：抽取 → 合并 → 衰减 → 矛盾 → 自动关闭；mem0 适配器缺包降级。"""

from datetime import date, datetime, timedelta, timezone

import pytest

from sas.memory import ME, LocalMemory, MemoryItem, decayed, get_backend
from sas.memory.rules import EventView, extract
from sas.memory.timeparse import resolve_due

from .conftest import NOW

TUE = date(2026, 10, 6)


def ev(text, *, me=False, sender="老王", group=False, conv=None, when=None, eid="e1"):
    return EventView(
        id=eid, channel="wechat", when=when or datetime(2026, 10, 6, 10, tzinfo=timezone.utc), text=text,
        sender=ME if me else sender, is_me=me, counterparts=[conv or sender] if me else [ME], is_group=group,
        is_service=False, conversation=conv or sender, sensitivity="personal",
    )


def kinds(text, **kw):
    return [(i.kind, i.subject, i.counterpart, i.text) for i in extract(ev(text, **kw))]


@pytest.mark.parametrize(
    "text, due",
    [("明天", "2026-10-07"), ("周五前", "2026-10-09"), ("周一", "2026-10-12"), ("下周三上午", "2026-10-14"),
     ("这周二", "2026-10-06"), ("10月15日发布", "2026-10-15"), ("20号", "2026-10-20"), ("月底", "2026-10-31"),
     ("next friday", "2026-10-16"), ("随便聊聊", None)],
)
def test_resolve_due(text, due):
    assert resolve_due(text, TUE) == due


def test_extract_my_commitment():
    assert kinds("好的，我明天把报价单发你", me=True) == [("commitment", ME, "老王", "我明天把报价单发你")]


def test_extract_request_preference_fact_plan():
    assert kinds("你周四前能帮我看下合同吗？")[0][:3] == ("request", "老王", ME)
    assert kinds("对了我不吃香菜") == [("preference", "老王", "", "不吃香菜")]
    assert kinds("我下个月搬到杭州了") == [("fact", "老王", "", "下个月搬到杭州了")]
    assert kinds("明天上午十点开会")[0][0] == "plan"
    assert kinds("I'll send the deck tomorrow", me=True)[0][0] == "commitment"


def test_extract_is_conservative():
    assert kinds("我不会去的", me=True) == []  # 否定
    assert kinds("我明天去吗？", me=True) == []  # 问句
    assert kinds("哈哈好的") == []
    assert kinds("你能帮小张看下吗？", group=True, conv="群") == []  # 群里点别人
    assert kinds("大家周三前提交周报", group=True, conv="群")[0][:3] == ("request", "老王", ME)


def test_confidential_and_service_messages_are_not_learned():
    e = ev("我明天把验证码发你", me=True)
    e.sensitivity = "confidential"
    assert extract(e) == []


def _item(text="不吃香菜", kind="preference", eid="e1", when="2026-10-01T00:00:00+00:00", conf=0.6):
    return MemoryItem(kind=kind, subject="老王", text=text, confidence=conf, source_event_ids=[eid], observed_at=when)


def test_merge_raises_confidence_and_dedupes_same_source(store):
    mem = LocalMemory(store)
    assert mem.write([_item()]) == 1
    assert mem.write([_item()]) == 0  # 同一条消息重复抽取：不加分
    assert mem.list()[0].evidence == 1
    assert mem.write([_item("不吃香菜的", eid="e2", when="2026-10-03T00:00:00+00:00")]) == 0
    (item,) = mem.list(now=NOW)
    assert item.evidence == 2
    assert item.confidence == pytest.approx(1 - 0.4 * 0.4)
    assert item.last_seen == "2026-10-03T00:00:00+00:00"


def test_decay_by_half_life():
    seen = "2026-01-01T00:00:00+00:00"
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert decayed(0.8, "preference", seen, now) == 0.8
    assert decayed(0.8, "preference", seen, now + timedelta(days=180)) == pytest.approx(0.4)
    assert decayed(0.8, "commitment", seen, now + timedelta(days=60)) == pytest.approx(0.2)


def test_old_memories_fade_out_of_listing(store):
    mem = LocalMemory(store)
    mem.write([_item(when="2025-01-01T00:00:00+00:00")])
    assert mem.list(now=NOW, min_confidence=0.3) == []
    assert mem.list(now=NOW)[0].effective_confidence < 0.2


def test_contradicting_preference_lowers_old_one(store):
    mem = LocalMemory(store)
    mem.write([_item("喜欢咖啡")])
    mem.write([_item("不喜欢咖啡", eid="e2", when="2026-10-05T00:00:00+00:00")])
    items = {i.text: i.confidence for i in mem.list(now=NOW)}
    assert items["喜欢咖啡"] == pytest.approx(0.18)
    assert items["不喜欢咖啡"] == 0.6


def test_commitment_closed_by_later_message(assistant):
    mine = assistant.memory.list(kind="commitment", subject=ME, now=NOW)
    quote = next(i for i in mine if "报价单" in i.text)
    assert quote.status == "done"
    assert len(quote.source_event_ids) == 2  # 承诺 + 关闭它的那条消息
    budget = next(i for i in mine if "预算表" in i.text)
    assert budget.status == "open"


def test_manual_close(assistant):
    item = assistant.todos()["mine"][0]
    assert assistant.memory.close(item.id[:5])
    assert item.id not in {i.id for i in assistant.todos()["mine"]}


def test_mem0_missing_falls_back_to_local(config, store, capsys):
    pytest.importorskip("sqlite3")
    try:
        import mem0  # noqa: F401
        pytest.skip("mem0ai 已安装，降级路径不适用")
    except ImportError:
        pass
    config.memory_backend = "mem0"
    backend = get_backend(config, store)
    assert backend.name == "local"
    assert "mem0ai" in capsys.readouterr().err


def test_mem0_adapter_when_installed(config):
    pytest.importorskip("mem0")
    from sas.memory import Mem0Memory
    from sas.privacy import PrivacyError

    with pytest.raises(PrivacyError):
        Mem0Memory(config)  # 默认配置会用云端模型，未授权必须拒绝
