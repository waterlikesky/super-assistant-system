from datetime import datetime, timezone
from pathlib import Path

import pytest

from sas.assistant import Assistant
from sas.config import Config
from sas.ingest import ingest_path
from sas.memory import get_backend
from sas.store import Store

ROOT = Path(__file__).resolve().parents[1]
EXPORTS = ROOT / "fixtures" / "exports"
EML_CASES = ROOT / "fixtures" / "eml_cases"
# 夹具里的「今天」是 2026-10-06（周二）；测试固定一个「现在」，衰减结果可复现
NOW = datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc)


@pytest.fixture
def config(tmp_path) -> Config:
    return Config.load(env={}, db_path=tmp_path / "sas.db")


@pytest.fixture
def store(config) -> Store:
    return Store(config.db_path)


@pytest.fixture
def memory(config, store):
    return get_backend(config, store)


@pytest.fixture
def ingested(config, store, memory):
    report = ingest_path(EXPORTS, store=store, memory=memory, config=config, recursive=True)
    return report


@pytest.fixture
def assistant(ingested, store, memory) -> Assistant:
    return Assistant(store, memory, now=NOW)
