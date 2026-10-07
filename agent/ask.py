"""M3 placeholder: retrieve then answer. M0 only prints memory hits."""

from __future__ import annotations

import argparse

from memory.store import InMemoryStore


def main() -> None:
    parser = argparse.ArgumentParser(description="M0/M3 agent ask stub")
    parser.add_argument("query")
    args = parser.parse_args()
    store = InMemoryStore()
    hits = store.search(args.query)
    if not hits:
        print("不知道（记忆层为空或未命中）。请先运行 python -m ingest.demo_run")
        return
    print(hits)


if __name__ == "__main__":
    main()
