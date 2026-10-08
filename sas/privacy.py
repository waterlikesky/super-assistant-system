"""隐私护栏：出站永远拒绝；发往模型的文本必须先脱敏，云模型需显式开关。"""

from __future__ import annotations

from urllib.parse import urlparse

from sas.redact import redact_text

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class PrivacyError(RuntimeError):
    pass


def refuse_outbound(*_args, **_kwargs):
    """任何「发送」都走到这里。本项目没有出站实现。"""
    raise PrivacyError("sas 是只读系统：没有发送消息的能力，出站默认且永久关闭")


def is_local_url(url: str) -> bool:
    return (urlparse(url).hostname or "") in LOCAL_HOSTS


def prepare_for_model(texts: list[str], *, cloud: bool, allow_cloud: bool) -> list[str]:
    """把要交给模型的片段再脱敏一遍；云模型未授权时拒绝。"""
    if cloud and not allow_cloud:
        raise PrivacyError(
            "要把内容发给云模型，需显式设置 SAS_ALLOW_CLOUD_LLM=true（只会发送脱敏后的片段）"
        )
    return [redact_text(t) for t in texts]
