"""可选语义检索钩子：simonw/llm 的 embedding 模型 + sqlite-vec，向量存在同一个 sas.db 里。

默认关闭（embed_model 为空）。缺包、SQLite 不支持加载扩展、或云端模型未授权时，
get_vector_index() 返回 None 并给出原因，其余功能不受影响。只对脱敏后、非 confidential 的消息做向量。
"""

from __future__ import annotations

from sas.config import Config
from sas.llm import LOCAL_LLM_PREFIXES
from sas.privacy import PrivacyError, prepare_for_model
from sas.store import Store


class EmbeddingUnavailable(RuntimeError):
    pass


class VectorIndex:
    def __init__(self, store: Store, model, *, cloud: bool, allow_cloud: bool) -> None:
        try:
            import sqlite_vec  # type: ignore
        except ImportError as exc:
            raise EmbeddingUnavailable("未安装 sqlite-vec：pip install 'super-assistant-system[vec]'") from exc
        conn = store.db.conn
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        except (AttributeError, Exception) as exc:  # noqa: BLE001 — 某些 Python 编译时关闭了扩展加载
            raise EmbeddingUnavailable(f"当前 Python 的 sqlite3 不能加载扩展：{exc}") from exc
        self.serialize = sqlite_vec.serialize_float32
        self.store, self.model, self.cloud, self.allow_cloud = store, model, cloud, allow_cloud
        self._ready = "vec_events" in store.db.table_names()

    def _embed(self, texts: list[str]) -> list[list[float]]:
        safe = prepare_for_model(texts, cloud=self.cloud, allow_cloud=self.allow_cloud)
        return [list(v) for v in self.model.embed_multi(safe)]

    def add(self, rows: list[dict]) -> int:
        rows = [r for r in rows if r["sensitivity"] != "confidential" and r["content_text"].strip()]
        if not rows:
            return 0
        vectors = self._embed([r["content_text"] for r in rows])
        if not self._ready:
            self.store.db.execute(f"create virtual table if not exists vec_events using vec0(embedding float[{len(vectors[0])}])")
            self._ready = True
        for row, vec in zip(rows, vectors):
            rowid = self.store.query("select rowid from events where id = ?", [row["id"]])[0]["rowid"]
            self.store.db.execute("insert or replace into vec_events(rowid, embedding) values (?, ?)", [rowid, self.serialize(vec)])
        return len(rows)

    def search(self, query: str, k: int = 5) -> list[dict]:
        if not self._ready:
            return []
        (vec,) = self._embed([query])
        hits = self.store.db.execute(
            "select rowid from vec_events where embedding match ? and k = ? order by distance", [self.serialize(vec), k]
        ).fetchall()
        ids = [h[0] for h in hits]
        if not ids:
            return []
        rows = {r["rowid"]: r for r in self.store.query(f"select rowid, * from events where rowid in ({','.join(map(str, ids))})")}
        return [rows[i] for i in ids if i in rows]


def get_vector_index(config: Config, store: Store) -> tuple[VectorIndex | None, str]:
    """返回 (索引, 说明)。索引为 None 时说明里写原因。"""
    if not config.embed_model:
        return None, "未启用（设置 SAS_EMBED_MODEL 开启语义检索）"
    try:
        import llm  # type: ignore
    except ImportError:
        return None, "未安装 llm：pip install 'super-assistant-system[llm]'"
    try:
        model = llm.get_embedding_model(config.embed_model)
        cloud = not config.embed_model.lower().startswith(LOCAL_LLM_PREFIXES + ("sentence-transformers",))
        if cloud and not config.allow_cloud_llm:
            raise PrivacyError("embedding 模型在云端，需 SAS_ALLOW_CLOUD_LLM=true")
        return VectorIndex(store, model, cloud=cloud, allow_cloud=config.allow_cloud_llm), "已启用"
    except (EmbeddingUnavailable, PrivacyError) as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 — llm 找不到模型等
        return None, f"embedding 模型不可用：{exc}"
