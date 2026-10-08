"""配置：默认值 → ./sas.toml（或 --config）→ 环境变量 SAS_*，后者覆盖前者。

所有隐私相关开关默认最保守：不调用模型、不允许云模型、没有出站。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from datetime import timedelta, timezone, tzinfo
from pathlib import Path
from typing import Mapping

DEFAULT_DB = Path("data") / "sas.db"
DEFAULT_ME = ("我", "me", "Me", "自己")


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    db_path: Path = DEFAULT_DB
    # 导出文件里代表「我」的昵称 / 邮箱；用来判断消息方向（谁答应了谁）
    me: tuple[str, ...] = DEFAULT_ME
    me_emails: tuple[str, ...] = ()
    tz: str = "Asia/Shanghai"
    # LLM：none（默认，纯离线规则）| ollama（本机 HTTP）| llm（simonw/llm 库）
    llm_backend: str = "none"
    llm_model: str = ""
    ollama_url: str = "http://127.0.0.1:11434"
    # 云模型开关：即使打开也只发送脱敏片段，confidential 消息永不外发
    allow_cloud_llm: bool = False
    # 出站：没有实现，置为 true 会被 check() 拒绝
    outbound_enabled: bool = False
    # 记忆镜像：local（只用本地）| openviking | tdam | mem0，可逗号组合；本地 SQLite 永远是真源
    memory_backend: str = "local"
    # OpenViking（ADR 0001 主推）：API key 只从环境变量 OPENVIKING_API_KEY 读取
    openviking_url: str = ""
    openviking_root: str = "viking://resources/sas"
    # server 用的模型：local（Ollama / 本地 GGUF）| cloud。cloud 需要 allow_cloud_llm
    openviking_models: str = "cloud"
    # TencentDB-Agent-Memory（可选）：API key 只从环境变量 TDAM_API_KEY 读取
    tdam_url: str = ""
    tdam_service_id: str = "default"
    tdam_models: str = "cloud"
    # 语义检索（可选）：simonw/llm 的 embedding 模型名，空 = 关闭
    embed_model: str = ""
    reply_window_days: int = 7
    extra: dict = field(default_factory=dict)

    def tzinfo(self) -> tzinfo:
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(self.tz)
        except Exception:
            # Windows 无 tzdata 时退回固定东八区
            return timezone(timedelta(hours=8))

    def is_me(self, name: str | None) -> bool:
        if not name:
            return False
        value = name.strip()
        return value in self.me or value.lower() in {m.lower() for m in self.me_emails}

    def memory_backends(self) -> list[str]:
        return [b.strip() for b in self.memory_backend.split(",") if b.strip()] or ["local"]

    def check(self) -> "Config":
        from sas.privacy import PrivacyError

        if self.outbound_enabled:
            raise PrivacyError("出站（自动回复/代发）没有实现，也不允许开启：请把 outbound_enabled 设回 false")
        if self.llm_backend not in {"none", "ollama", "llm"}:
            raise ConfigError(f"未知 llm_backend: {self.llm_backend}")
        unknown = set(self.memory_backends()) - {"local", "openviking", "tdam", "mem0"}
        if unknown:
            raise ConfigError(f"未知 memory_backend: {', '.join(sorted(unknown))}")
        for name in ("openviking_models", "tdam_models"):
            if getattr(self, name) not in {"local", "cloud"}:
                raise ConfigError(f"{name} 只能是 local 或 cloud")
        return self

    @classmethod
    def load(
        cls,
        path: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        **overrides,
    ) -> "Config":
        env = os.environ if env is None else env
        values: dict = {}
        toml_path = Path(path) if path else Path(env.get("SAS_CONFIG", "sas.toml"))
        if toml_path.is_file():
            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            values.update(data.get("sas", data))
        elif path:
            raise ConfigError(f"配置文件不存在: {path}")
        for f in fields(cls):
            key = f"SAS_{f.name.upper()}"
            if key in env:
                values[f.name] = env[key]
        # 与官方 SDK 一致的环境变量名也认
        for field_name, alias in (("openviking_url", "OPENVIKING_URL"), ("tdam_url", "TDAM_URL")):
            if alias in env and field_name not in values:
                values[field_name] = env[alias]
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls._from_values(values).check()

    @classmethod
    def _from_values(cls, values: dict) -> "Config":
        known = {f.name: f for f in fields(cls)}
        cfg = cls()
        for key, raw in values.items():
            if key not in known:
                cfg.extra[key] = raw
                continue
            default = getattr(cfg, key)
            if isinstance(default, bool):
                value = raw if isinstance(raw, bool) else str(raw).strip().lower() in {"1", "true", "yes", "on"}
            elif isinstance(default, tuple):
                items = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
                value = tuple(str(i).strip() for i in items if str(i).strip())
            elif isinstance(default, Path):
                value = Path(raw).expanduser()
            elif isinstance(default, int):
                value = int(raw)
            else:
                value = raw
            setattr(cfg, key, value)
        if "me" in values:
            # 用户追加的昵称不覆盖「我」这些通用写法
            cfg.me = tuple(dict.fromkeys(cfg.me + DEFAULT_ME))
        return cfg
