"""CLI 端到端：ingest → ask / people / person / todos / digest / stats；隐私开关。"""

import subprocess
import sys

import pytest

from sas.cli import main
from sas.config import Config
from sas.llm import OllamaBackend, answer_with_llm, get_llm
from sas.privacy import PrivacyError, refuse_outbound

from .conftest import EXPORTS, ROOT


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.delenv("SAS_DB_PATH", raising=False)
    path = tmp_path / "sas.db"
    assert main(["--db", str(path), "ingest", str(EXPORTS), "-r"]) == 0
    return path


def run(db, *args) -> str:
    return main(["--db", str(db), *args])


def test_ingest_reports_and_is_incremental(db, capsys):
    capsys.readouterr()
    assert run(db, "ingest", str(EXPORTS), "-r") == 0
    out = capsys.readouterr().out
    assert "新增 0 条消息" in out and "未变化跳过" in out


def test_ingest_missing_path_fails(tmp_path, capsys):
    assert main(["--db", str(tmp_path / "x.db"), "ingest", str(tmp_path / "nope")]) == 1
    assert "路径不存在" in capsys.readouterr().err


def test_ask_last_conversation_with_sources(db, capsys):
    capsys.readouterr()
    run(db, "ask", "上次和老王聊了什么")
    out = capsys.readouterr().out
    assert "与 老王 最近的交流" in out
    assert "报名表" in out and "── 出处" in out and "wechat:" in out
    assert "不吃香菜" in out  # 记忆命中


def test_ask_promises_and_replies(db, capsys):
    capsys.readouterr()
    run(db, "ask", "我答应过谁什么")
    out = capsys.readouterr().out
    assert "预算表" in out and "接口文档" in out
    assert "报价单" not in out  # 已被后续消息关闭
    run(db, "ask", "今天该回谁")
    out = capsys.readouterr().out
    assert "老王" in out and "妈妈" in out and "赵经理" in out
    assert "95588" not in out  # 服务号不进待回复


def test_ask_keyword_and_unknown(db, capsys):
    capsys.readouterr()
    run(db, "ask", "急救包")
    assert "Lisa" in capsys.readouterr().out
    run(db, "ask", "火星移民计划")
    assert "不知道" in capsys.readouterr().out


def test_people_person_todos(db, capsys):
    capsys.readouterr()
    run(db, "people")
    out = capsys.readouterr().out
    assert "老王" in out and "赵经理" in out and "95588" not in out
    run(db, "person", "老王")
    out = capsys.readouterr().out
    assert "不吃香菜" in out and "下个月搬到杭州" in out and "合同我发你邮箱" in out
    run(db, "todos")
    out = capsys.readouterr().out
    for title in ("我答应别人的", "别人找我办的", "别人答应我的", "待回复"):
        assert title in out
    assert run(db, "person", "不存在的人") == 1


def test_done_command(db, capsys):
    from sas.store import Store

    item_id = Store(db).query("select id from memories where kind='commitment' and status='open' and subject='我' limit 1")[0]["id"]
    assert run(db, "done", f"#{item_id}") == 0
    assert Store(db).query("select status from memories where id = ?", [item_id])[0]["status"] == "done"


def test_digest_to_obsidian_markdown(db, tmp_path, capsys):
    vault = tmp_path / "vault"
    assert run(db, "digest", "--date", "2026-10-06", "--out", str(vault)) == 0
    md = (vault / "2026-10-06.md").read_text(encoding="utf-8")
    assert md.startswith("---\ndate: 2026-10-06")
    for part in ("## 待回复", "## 我答应的", "## 别人找我", "## 约定 / 日程", "## 会话", "[[老王]]", "- [x]"):
        assert part in md, part
    assert "482913" not in md
    capsys.readouterr()
    run(db, "digest", "--date", "2020-01-01")
    assert "这一天没有消息" in capsys.readouterr().out


def test_stats_json(db, capsys):
    capsys.readouterr()
    run(db, "stats", "--json")
    out = capsys.readouterr().out
    assert '"events": 28' in out and '"allow_cloud_llm": false' in out


def test_python_dash_m_entrypoint(tmp_path):
    res = subprocess.run([sys.executable, "-m", "sas", "connectors"], cwd=ROOT, capture_output=True, text=True, check=False)
    assert res.returncode == 0 and "wechat_txt" in res.stdout


# ---------- 隐私护栏 ----------

def test_outbound_cannot_be_enabled(tmp_path, capsys):
    with pytest.raises(PrivacyError):
        Config.load(env={"SAS_OUTBOUND_ENABLED": "true"})
    with pytest.raises(PrivacyError):
        refuse_outbound("老王", "hi")


def test_cli_rejects_outbound_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SAS_OUTBOUND_ENABLED", "true")
    assert main(["--db", str(tmp_path / "x.db"), "stats"]) == 2
    assert "出站" in capsys.readouterr().err


def test_cloud_llm_requires_explicit_opt_in():
    cfg = Config.load(env={"SAS_LLM_BACKEND": "ollama", "SAS_OLLAMA_URL": "https://ollama.example.com"})
    with pytest.raises(PrivacyError):
        get_llm(cfg)
    local = Config.load(env={"SAS_LLM_BACKEND": "ollama"})
    assert get_llm(local).cloud is False
    assert get_llm(Config.load(env={})) is None


def test_llm_only_sees_redacted_snippets():
    seen = {}

    class Fake(OllamaBackend):
        def complete(self, prompt, system=""):
            seen["prompt"] = prompt
            return "ok"

    backend = Fake("http://127.0.0.1:11434", "m")
    assert answer_with_llm(backend, "他电话多少？", ["老王：我手机 13912345678"], allow_cloud=False) == "ok"
    assert "13912345678" not in seen["prompt"] and "[PHONE]" in seen["prompt"]
    backend.cloud = True
    with pytest.raises(PrivacyError):
        answer_with_llm(backend, "q", ["x"], allow_cloud=False)


def test_ask_llm_without_backend_falls_back_offline(db, capsys):
    capsys.readouterr()
    run(db, "ask", "上次和老王聊了什么", "--llm")
    out = capsys.readouterr().out
    assert "未配置 LLM" in out and "与 老王 最近的交流" in out
