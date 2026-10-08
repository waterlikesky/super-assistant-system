"""通用 IMAP（只读）：QQ 邮箱 / 163 / Gmail / 任意 IMAP 服务器。

只读保证（代码层面，而不是约定）：
- 邮箱用 SELECT readonly=True（即 IMAP EXAMINE）打开；
- 取信只用 UID FETCH BODY.PEEK[]，不会设置 \\Seen；
- ReadOnlyIMAP 包装只放行 login / select(readonly) / uid SEARCH|FETCH / logout / ID，
  STORE、COPY、MOVE、EXPUNGE、APPEND、DELETE 等任何写操作一律抛错。
凭据：密码（QQ/163 授权码、Gmail 应用专用密码）只从环境变量 SAS_IMAP_PASSWORD 或系统 keyring
（service = "sas-imap"，username = 邮箱地址）读取，不写进仓库、配置文件或数据库。
增量：按 (UIDVALIDITY, 最大 UID) 记在 imap_state 表；账号只存哈希。
"""

from __future__ import annotations

import imaplib
import os
from dataclasses import dataclass, replace
from email import policy
from email.parser import BytesParser

from .base import ParseContext, SkipRecord, short_hash
from .email import message_to_event

PROVIDERS = {
    "qq": ("imap.qq.com", 993),
    "163": ("imap.163.com", 993),
    "126": ("imap.126.com", 993),
    "gmail": ("imap.gmail.com", 993),
    "outlook": ("outlook.office365.com", 993),  # 微软已停用基本认证，个人号通常需 OAuth，见 DATA_SOURCES.md
}
NETEASE = {"imap.163.com", "imap.126.com", "imap.yeah.net"}
imaplib.Commands.setdefault("ID", ("AUTH", "NONAUTH", "SELECTED"))


class ReadOnlyViolation(RuntimeError):
    pass


class ReadOnlyIMAP:
    """只暴露只读命令的 imaplib 包装。"""

    def __init__(self, conn) -> None:
        self._conn = conn

    def login(self, user: str, password: str):
        return self._conn.login(user, password)

    def client_id(self):
        # 网易邮箱要求登录后先发 IMAP ID，否则 SELECT 报 "Unsafe Login"
        return self._conn._simple_command("ID", '("name" "sas" "version" "0.2" "vendor" "sas")')

    def select(self, mailbox: str = "INBOX", readonly: bool = True):
        if readonly is not True:
            raise ReadOnlyViolation("sas 只以只读方式（EXAMINE）打开邮箱")
        typ, data = self._conn.select(mailbox, readonly=True)
        if typ != "OK":
            raise SkipRecord(f"无法打开邮箱文件夹 {mailbox}：{data!r}")
        return typ, data

    def uidvalidity(self) -> int:
        _, data = self._conn.response("UIDVALIDITY")
        value = data[0] if data and data[0] else b"0"
        return int(value)

    def uid(self, command: str, *args):
        cmd = command.upper()
        if cmd == "SEARCH":
            return self._conn.uid("SEARCH", *args)
        if cmd == "FETCH":
            if "PEEK" not in str(args[-1]).upper():
                raise ReadOnlyViolation("取信必须用 BODY.PEEK[]，避免标记已读")
            return self._conn.uid("FETCH", *args)
        raise ReadOnlyViolation(f"禁止的 IMAP 命令：UID {command}")

    def logout(self):
        try:
            return self._conn.logout()
        except (imaplib.IMAP4.error, OSError):
            return None

    def __getattr__(self, name):
        raise ReadOnlyViolation(f"禁止的 IMAP 操作：{name}")


def get_password(user: str, env=os.environ) -> str:
    password = env.get("SAS_IMAP_PASSWORD")
    if password:
        return password
    try:
        import keyring  # type: ignore

        password = keyring.get_password("sas-imap", user)
    except Exception:  # noqa: BLE001 — 没装 keyring 或无可用后端
        password = None
    if not password:
        raise SkipRecord(
            "缺少 IMAP 密码：设置环境变量 SAS_IMAP_PASSWORD（QQ/163 用授权码，Gmail 用应用专用密码），"
            "或 `keyring set sas-imap <邮箱>`"
        )
    return password


@dataclass
class ImapAccount:
    host: str
    user: str
    port: int = 993
    folder: str = "INBOX"
    ssl: bool = True

    @property
    def key(self) -> str:
        return short_hash(self.host.lower(), self.user.lower(), self.folder, n=16)

    @classmethod
    def from_args(cls, user: str, provider: str | None = None, host: str | None = None, port: int | None = None,
                  folder: str = "INBOX") -> "ImapAccount":
        if provider:
            if provider not in PROVIDERS:
                raise SkipRecord(f"未知 provider：{provider}（可选 {', '.join(PROVIDERS)}）")
            h, p = PROVIDERS[provider]
            host, port = host or h, port or p
        if not host:
            raise SkipRecord("需要 --provider 或 --host")
        return cls(host=host, user=user, port=port or 993, folder=folder)


def fetch_events(
    account: ImapAccount,
    ctx: ParseContext,
    *,
    state: dict | None,
    password: str,
    limit: int | None = None,
    connect=None,
) -> tuple[list[dict], dict]:
    """返回 (事件, 新状态)。state = {"uidvalidity": int, "last_uid": int} 或 None。"""
    connect = connect or (imaplib.IMAP4_SSL if account.ssl else imaplib.IMAP4)
    try:
        conn = ReadOnlyIMAP(connect(account.host, account.port))
    except OSError as exc:
        raise SkipRecord(f"连不上 {account.host}:{account.port}：{exc}") from exc
    try:
        try:
            conn.login(account.user, password)
        except imaplib.IMAP4.error as exc:
            raise SkipRecord(f"登录失败（检查授权码 / 应用专用密码，且邮箱已开启 IMAP）：{exc}") from exc
        if account.host in NETEASE:
            conn.client_id()
        conn.select(account.folder, readonly=True)
        validity = conn.uidvalidity()
        last = state["last_uid"] if state and state.get("uidvalidity") == validity else 0
        typ, data = conn.uid("SEARCH", None, f"UID {last + 1}:*")
        uids = sorted(int(u) for u in (data[0] or b"").split() if int(u) > last) if typ == "OK" else []
        if limit:
            uids = uids[-limit:]
        events: list[dict] = []
        parser = BytesParser(policy=policy.default)
        # 登录账号本身就是「我」：从它发出的信记为 outbound（只改本次解析用的副本）
        ctx.config = replace(ctx.config, me_emails=tuple(dict.fromkeys((*ctx.config.me_emails, account.user))))
        for uid in uids:
            typ, parts = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
            raw = next((p[1] for p in parts or [] if isinstance(p, tuple) and len(p) > 1), None)
            if typ != "OK" or raw is None:
                ctx.skip(f"UID {uid}", "取信失败")
                continue
            msg = parser.parsebytes(raw)
            try:
                event = message_to_event(msg, ctx=ctx, path=None, via="imap", fallback_key=f"{account.key}:{validity}:{uid}")
            except SkipRecord as exc:
                ctx.skip(f"UID {uid}", exc.reason)
                continue
            event["raw_ref"] = f"imap://{account.host}/{account.folder};UIDVALIDITY={validity};UID={uid}"
            events.append(event)
        new_last = max([last, *uids])
        return events, {"uidvalidity": validity, "last_uid": new_last}
    finally:
        conn.logout()


def iter_state(store, account: ImapAccount) -> dict | None:
    if "imap_state" not in store.db.table_names():
        return None
    rows = store.query("select * from imap_state where key = ?", [account.key])
    return rows[0] if rows else None


def save_state(store, account: ImapAccount, state: dict, count: int) -> None:
    from datetime import datetime

    store.db["imap_state"].upsert(
        {"key": account.key, "host": account.host, "folder": account.folder, **state,
         "fetched": count, "last_run": datetime.now().isoformat(timespec="seconds")},
        pk="key",
    )
