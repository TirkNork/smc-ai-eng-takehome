"""Upsert the provided pinecone_vectors.jsonl.gz fixture into pinecone-local.

Usage:
    uv run python scripts/load_vectors.py            # upsert (idempotent by id)
    uv run python scripts/load_vectors.py --clear    # wipe existing vectors first, then load

Idempotent: upserting an existing vector id overwrites it, so re-running is safe.
--clear empties every namespace currently in the index before loading -- use
this for a clean reload instead of `docker compose down -v`, which would
also wipe Postgres.
"""
import argparse
import gzip
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "data" / "pinecone_vectors.jsonl.gz"

PINECONE_HOST = os.environ.get("PINECONE_HOST", "http://localhost:5080")
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY", "pclocal")
INDEX_NAME = os.environ.get("PINECONE_INDEX", "tenk-filings")
DIMENSION = int(os.environ.get("OPENAI_EMBEDDING_DIM", "512"))
BATCH_SIZE = 100


def get_index():
    pc = Pinecone(api_key=PINECONE_API_KEY, host=PINECONE_HOST)

    existing = {i["name"] for i in pc.list_indexes()}
    if INDEX_NAME not in existing:
        print(f"creating index '{INDEX_NAME}' (dim={DIMENSION}, metric=cosine)")
        pc.create_index(
            name=INDEX_NAME,
            dimension=DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )

    desc = pc.describe_index(INDEX_NAME)
    # pinecone-local advertises https in describe_index but only serves plain
    # HTTP on the per-index port -> force http or the client's TLS handshake fails.
    host = desc.host.replace("https://", "http://")
    return pc.Index(host=host)


def iter_records(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def batched(iterable, size):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def clear_index(index):
    stats = index.describe_index_stats()
    namespaces = list(stats.namespaces.keys()) if stats.namespaces else []
    if not namespaces:
        print("index already empty, nothing to clear")
        return
    for namespace in namespaces:
        index.delete(delete_all=True, namespace=namespace)
        print(f"cleared namespace '{namespace}'")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clear", action="store_true", help="delete all existing vectors before loading"
    )
    args = parser.parse_args()

    if not FIXTURE.exists():
        raise SystemExit(f"fixture not found: {FIXTURE}")

    index = get_index()

    if args.clear:
        print("clearing existing vectors...")
        clear_index(index)

    total = 0
    for batch in batched(iter_records(FIXTURE), BATCH_SIZE):
        by_namespace: dict[str, list] = {}
        for record in batch:
            by_namespace.setdefault(record["namespace"], []).append(
                {"id": record["id"], "values": record["values"], "metadata": record["metadata"]}
            )
        for namespace, vectors in by_namespace.items():
            index.upsert(vectors=vectors, namespace=namespace)
        total += len(batch)
        print(f"upserted {total} vectors...")

    stats = index.describe_index_stats()
    print("done.")
    print(stats)


if __name__ == "__main__":
    main()
