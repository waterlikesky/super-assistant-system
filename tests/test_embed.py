"""可选语义检索钩子：默认关闭；缺包时降级并说明原因，不影响其余功能。"""

import importlib.util

import pytest

from sas.embed import EmbeddingUnavailable, VectorIndex, get_vector_index


def test_disabled_by_default(config, store):
    index, note = get_vector_index(config, store)
    assert index is None and "未启用" in note


@pytest.mark.skipif(importlib.util.find_spec("llm") is not None, reason="llm 已安装")
def test_missing_llm_degrades(config, store):
    config.embed_model = "sentence-transformers/all-MiniLM-L6-v2"
    index, note = get_vector_index(config, store)
    assert index is None and "llm" in note


@pytest.mark.skipif(importlib.util.find_spec("sqlite_vec") is not None, reason="sqlite-vec 已安装")
def test_missing_sqlite_vec_degrades(store):
    with pytest.raises(EmbeddingUnavailable, match="sqlite-vec"):
        VectorIndex(store, model=None, cloud=False, allow_cloud=False)


def test_semantic_search_when_installed(ingested, store):
    pytest.importorskip("sqlite_vec")

    class FakeModel:
        def embed_multi(self, texts):
            return [[float("香菜" in t), float("合同" in t), 1.0] for t in texts]

    try:
        index = VectorIndex(store, FakeModel(), cloud=False, allow_cloud=False)
    except EmbeddingUnavailable as exc:
        pytest.skip(str(exc))
    index.add(store.query("select * from events"))
    assert "香菜" in index.search("香菜", k=1)[0]["content_text"]
