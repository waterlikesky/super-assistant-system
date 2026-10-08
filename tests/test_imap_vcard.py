"""通用 IMAP（只读，假服务器）与 vCard 人物别名合并。"""

import imaplib
from email.message import EmailMessage

import pytest

from sas.connectors import ParseContext, SkipRecord
from sas.connectors.imap import ImapAccount, ReadOnlyIMAP, ReadOnlyViolation, fetch_events, get_password
from sas.connectors.vcard import parse_vcards
from sas.ingest import ingest_path

from .conftest import EXPORTS, NOW

PASSWORD = "imap-auth-code-123"


def mail(uid: int, *, sender="Lisa <lisa@example.com>", to="me@qq.com", body="周五前能把方案发我吗？"):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, to, f"测试 {uid}"
    m["Date"] = f"Tue, 06 Oct 2026 1{uid}:00:00 +0800"
    m["Message-ID"] = f"<imap-{uid}@example.com>"
    m.set_content(body + "\n电话 13912345678")
    return m.as_bytes()


class FakeIMAP:
    """模拟 imaplib.IMAP4_SSL：记录全部调用，任何写命令都会让测试失败。"""

    mailbox: dict[int, bytes] = {}
    validity = 1700
    calls: list = []

    def __init__(self, host, port):
        self.calls.append(("connect", host, port))

    def login(self, user, password):
        self.calls.append(("login", user))
        if password != PASSWORD:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        return "OK", [b"ok"]

    def _simple_command(self, name, *args):
        self.calls.append(("cmd", name))
        return "OK", [b"ID done"]

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return "OK", [str(len(self.mailbox)).encode()]

    def response(self, code):
        return code, [str(self.validity).encode()]

    def uid(self, command, *args):
        self.calls.append(("uid", command, args))
        if command == "SEARCH":
            start = int(args[-1].split()[1].split(":")[0])
            hits = [u for u in sorted(self.mailbox) if u >= start] or [max(self.mailbox)]  # 真服务器对 n:* 至少回最后一封
            return "OK", [" ".join(map(str, hits)).encode()]
        if command == "FETCH":
            raw = self.mailbox[int(args[0])]
            return "OK", [(f"{args[0]} (UID {args[0]} BODY[] {{{len(raw)}}}".encode(), raw), b")"]
        raise AssertionError(command)

    def logout(self):
        self.calls.append(("logout",))

    def __getattr__(self, name):  # store / expunge / copy ... 都不该被调用
        raise AssertionError(f"写操作被调用：{name}")


@pytest.fixture
def fake_imap(monkeypatch):
    FakeIMAP.mailbox = {1: mail(1), 2: mail(2, body="好的"), 3: mail(3, sender="Me <me@qq.com>", to="lisa@example.com", body="我明天把方案发你")}
    FakeIMAP.validity = 1700
    FakeIMAP.calls = []
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setenv("SAS_IMAP_PASSWORD", PASSWORD)
    return FakeIMAP


def test_imap_is_read_only_and_incremental(fake_imap, config):
    account = ImapAccount.from_args("me@qq.com", provider="qq")
    ctx = ParseContext(config=config, consent_tag="t")
    events, state = fetch_events(account, ctx, state=None, password=PASSWORD)
    assert len(events) == 3 and state == {"uidvalidity": 1700, "last_uid": 3}
    assert ("connect", "imap.qq.com", 993) in fake_imap.calls
    assert ("select", "INBOX", True) in fake_imap.calls  # EXAMINE
    fetches = [c for c in fake_imap.calls if c[:2] == ("uid", "FETCH")]
    assert fetches and all("BODY.PEEK[]" in c[2][-1] for c in fetches)
    assert [e["direction"] for e in events] == ["inbound", "inbound", "outbound"]  # 登录账号即「我」
    assert config.me_emails == ()  # 没有改动共享配置
    assert events[0]["raw_ref"].startswith("imap://imap.qq.com/INBOX;UIDVALIDITY=1700;UID=1")
    assert "me@qq.com" not in events[0]["raw_ref"]

    fake_imap.mailbox[4] = mail(4, body="收到")
    fake_imap.calls.clear()
    events, state = fetch_events(account, ctx, state=state, password=PASSWORD)
    assert [e["id"] for e in events] == ["email:imap-4@example.com"] and state["last_uid"] == 4
    events, _ = fetch_events(account, ctx, state=state, password=PASSWORD)
    assert events == []  # 没有新信（服务器回的 UID 4 被过滤）


def test_uidvalidity_change_resyncs(fake_imap, config):
    account = ImapAccount.from_args("me@qq.com", provider="qq")
    ctx = ParseContext(config=config, consent_tag="t")
    _, state = fetch_events(account, ctx, state=None, password=PASSWORD)
    fake_imap.validity = 1800
    events, state = fetch_events(account, ctx, state=state, password=PASSWORD)
    assert len(events) == 3 and state["uidvalidity"] == 1800  # 重新同步，入库时靠 Message-ID 去重


def test_netease_sends_imap_id(fake_imap, config):
    fetch_events(ImapAccount.from_args("me@163.com", provider="163"), ParseContext(config=config, consent_tag="t"),
                 state=None, password=PASSWORD)
    assert ("cmd", "ID") in fake_imap.calls


def test_read_only_wrapper_blocks_writes():
    conn = ReadOnlyIMAP(object())
    for bad in (lambda: conn.store("1", "+FLAGS", "\\Seen"), lambda: conn.expunge(), lambda: conn.copy("1", "Trash"),
                lambda: conn.select("INBOX", readonly=False), lambda: conn.uid("STORE", "1", "+FLAGS", "\\Deleted"),
                lambda: conn.uid("FETCH", "1", "(RFC822)")):
        with pytest.raises(ReadOnlyViolation):
            bad()


def test_password_only_from_env_or_keyring(monkeypatch):
    with pytest.raises(SkipRecord, match="SAS_IMAP_PASSWORD"):
        get_password("me@qq.com", env={})
    assert get_password("me@qq.com", env={"SAS_IMAP_PASSWORD": "x"}) == "x"


def test_cli_imap_end_to_end(fake_imap, tmp_path, capsys):
    from sas.cli import main
    from sas.store import Store

    db = tmp_path / "sas.db"
    assert main(["--db", str(db), "imap", "--user", "me@qq.com", "--provider", "qq"]) == 0
    assert "新增 3 条" in capsys.readouterr().out
    assert main(["--db", str(db), "imap", "--user", "me@qq.com", "--provider", "qq"]) == 0
    assert "取到 0 封" in capsys.readouterr().out
    store = Store(db)
    store.db.conn.commit()
    raw = db.read_bytes().decode("utf-8", errors="ignore")
    assert PASSWORD not in raw and "me@qq.com" not in raw and "13912345678" not in raw
    kinds = {r["kind"] for r in store.query("select kind from memories")}
    assert {"request", "commitment"} <= kinds
    assert main(["--db", str(db), "imap", "--user", "me@qq.com", "--provider", "qq"]) == 0
    fake_imap.calls.clear()


def test_cli_imap_bad_password(fake_imap, tmp_path, monkeypatch, capsys):
    from sas.cli import main

    monkeypatch.setenv("SAS_IMAP_PASSWORD", "wrong")
    assert main(["--db", str(tmp_path / "x.db"), "imap", "--user", "me@qq.com", "--provider", "qq"]) == 1
    err = capsys.readouterr().err
    assert "登录失败" in err and "wrong" not in err


# ---------- vCard ----------

def test_parse_vcards_including_quoted_printable():
    contacts = {c.name: c for c in parse_vcards((EXPORTS / "contacts" / "contacts.vcf").read_text(encoding="utf-8"))}
    assert set(contacts) == {"王建国", "张伟", "Alice Chen", "妈妈", "陈不相干"}
    assert "老王" in contacts["王建国"].aliases
    assert contacts["张伟"].org == "示例科技"
    assert "林妈妈" in contacts["妈妈"].aliases  # vCard 2.1 QUOTED-PRINTABLE 中文
    handles = contacts["张伟"].handles
    assert any(h.startswith("tel:") for h in handles) and "zh***@example.com" in handles
    assert not any("13500003333" in h for h in handles)


def test_contacts_merge_aliases_into_people(assistant, store):
    people = {p["name"]: p for p in store.query("select * from people")}
    assert "王建国" in people["老王"]["aliases"]  # 昵称匹配
    assert people["张伟"]["org"] == "示例科技"  # 电话哈希匹配
    assert "陈不相干" not in people and "王建国" not in people  # 通讯录不整体灌入人物列表
    prof = assistant.profile("王建国")
    assert prof["person"]["name"] == "老王" and prof["about"]
    assert assistant.mentioned_people("上次和王建国聊了什么") == ["老王"]
    assert assistant.ask("上次和王建国聊了什么").sections[0][0].startswith("与 老王 最近的交流")


def test_contacts_merge_two_people(tmp_path, config, store, memory):
    a = tmp_path / "Tom.txt"
    a.write_text("2026-10-01 09:00:00 Tom\n我喜欢爬山\n", encoding="utf-8")
    b = tmp_path / "汤姆.txt"
    b.write_text("2026-10-02 09:00:00 汤姆\n我明天把照片发你\n\n2026-10-02 09:05:00 汤姆\n在吗\n", encoding="utf-8")
    ingest_path(tmp_path, store=store, memory=memory, config=config)
    assert {p["name"] for p in store.query("select name from people")} == {"Tom", "汤姆"}
    vcf = tmp_path / "c.vcf"
    vcf.write_text("BEGIN:VCARD\nVERSION:3.0\nFN:Tom Lee\nNICKNAME:Tom,汤姆\nEND:VCARD\n", encoding="utf-8")
    ingest_path(vcf, store=store, memory=memory, config=config)
    (person,) = store.query("select * from people")
    assert person["name"] == "汤姆" and person["msg_in"] == 3  # 消息多的名字做显示名，计数相加
    assert {"Tom", "Tom Lee"} <= set(__import__("json").loads(person["aliases"]))
    assert {i.subject for i in memory.list()} == {"汤姆"}  # 记忆主体也合并
    # 合并后再来的消息直接落到同一个人
    a.write_text("2026-10-01 09:00:00 Tom\n我喜欢爬山\n\n2026-10-03 09:00:00 Tom\n周末见\n", encoding="utf-8")
    ingest_path(a, store=store, memory=memory, config=config)
    assert store.count("people") == 1
