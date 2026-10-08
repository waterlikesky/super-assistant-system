"""可选 LLM 后端。默认 none：所有功能用离线规则完成。

- ollama：本机 HTTP（默认 http://127.0.0.1:11434），视为本地
- llm：simonw/llm 库；模型可能是云端，除非模型名以 ollama/ gguf/ mlx/ 等本地插件前缀开头
任何云端调用都要求 SAS_ALLOW_CLOUD_LLM=true，并且只发送脱敏后的片段（privacy.prepare_for_model）。
"""

from __future__ import annotations

import json
import urllib.request

from sas.config import Config
from sas.privacy import PrivacyError, is_local_url, prepare_for_model

LOCAL_LLM_PREFIXES = ("ollama", "gguf", "mlx", "llamafile", "gpt4all")
SYSTEM_PROMPT = (
    "你是用户的个人助理。只根据给出的聊天片段回答，用中文，简洁；"
    "每个结论后标注片段编号如 [1]；片段里没有的信息就说不知道，不要编造。"
)


class LLMUnavailable(RuntimeError):
    pass


class LLMBackend:
    name = "base"
    cloud = False

    def complete(self, prompt: str, system: str = SYSTEM_PROMPT) -> str:
        raise NotImplementedError


class OllamaBackend(LLMBackend):
    name = "ollama"

    def __init__(self, url: str, model: str) -> None:
        self.url = url.rstrip("/")
        self.model = model or "qwen2.5:7b"
        self.cloud = not is_local_url(self.url)

    def complete(self, prompt: str, system: str = SYSTEM_PROMPT) -> str:
        body = json.dumps({"model": self.model, "prompt": prompt, "system": system, "stream": False}).encode()
        req = urllib.request.Request(f"{self.url}/api/generate", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode()).get("response", "").strip()
        except OSError as exc:
            raise LLMUnavailable(f"连不上 Ollama（{self.url}）：{exc}") from exc


class LlmLibBackend(LLMBackend):
    name = "llm"

    def __init__(self, model: str) -> None:
        try:
            import llm  # type: ignore
        except ImportError as exc:
            raise LLMUnavailable("未安装 llm：pip install 'super-assistant-system[llm]'") from exc
        self.model = llm.get_model(model) if model else llm.get_model()
        model_id = getattr(self.model, "model_id", model or "")
        self.cloud = not str(model_id).lower().startswith(LOCAL_LLM_PREFIXES)

    def complete(self, prompt: str, system: str = SYSTEM_PROMPT) -> str:
        return self.model.prompt(prompt, system=system).text().strip()


def get_llm(config: Config) -> LLMBackend | None:
    """返回已通过隐私检查的后端；backend=none 时返回 None。"""
    if config.llm_backend == "none":
        return None
    if config.llm_backend == "ollama":
        backend: LLMBackend = OllamaBackend(config.ollama_url, config.llm_model)
    else:
        backend = LlmLibBackend(config.llm_model)
    if backend.cloud and not config.allow_cloud_llm:
        raise PrivacyError(
            f"{backend.name} 后端会把内容发到云端；如确需使用，请显式设置 SAS_ALLOW_CLOUD_LLM=true（只发送脱敏片段）"
        )
    return backend


def answer_with_llm(backend: LLMBackend, question: str, snippets: list[str], allow_cloud: bool) -> str:
    safe = prepare_for_model(snippets + [question], cloud=backend.cloud, allow_cloud=allow_cloud)
    *context, q = safe
    numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(context, start=1))
    return backend.complete(f"聊天片段：\n{numbered}\n\n问题：{q}")
