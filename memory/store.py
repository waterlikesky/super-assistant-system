from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Fact:
    subject: str
    predicate: str
    object: str
    source_event_ids: list[str] = field(default_factory=list)
    confidence: float = 0.5


class InMemoryStore:
    """M0 stub. Replace with SQLite/vector or self-hosted Mem0 in M2."""

    def __init__(self) -> None:
        self.chunks: list[dict] = []
        self.facts: list[Fact] = []

    def upsert_chunk(self, chunk: dict) -> None:
        self.chunks.append(chunk)

    def upsert_fact(self, fact: Fact) -> None:
        for existing in self.facts:
            if (
                existing.subject == fact.subject
                and existing.predicate == fact.predicate
            ):
                existing.object = fact.object
                existing.source_event_ids = list(
                    dict.fromkeys(existing.source_event_ids + fact.source_event_ids)
                )
                existing.confidence = max(existing.confidence, fact.confidence)
                return
        self.facts.append(fact)

    def search(self, query: str, k: int = 5) -> list[dict]:
        q = query.lower()
        hits: list[dict] = []
        for fact in self.facts:
            blob = f"{fact.subject} {fact.predicate} {fact.object}".lower()
            if q in blob or any(tok and tok in blob for tok in q.split()):
                hits.append(
                    {
                        "type": "fact",
                        "subject": fact.subject,
                        "predicate": fact.predicate,
                        "object": fact.object,
                        "source_event_ids": fact.source_event_ids,
                    }
                )
        for chunk in self.chunks:
            text = str(chunk.get("text", "")).lower()
            if q in text:
                hits.append({"type": "chunk", **chunk})
        return hits[:k]
