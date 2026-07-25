"""Remove duplicate vectors from the already-loaded pinecone-local index.

Background: the provided data/pinecone_vectors.jsonl.gz fixture contains
each real 10-K chunk TWICE under different random UUIDs (~2x duplication
in every one of the 4 filings). See scripts/note.txt for how this was
found and confirmed. This script does not touch the fixture or
load_vectors.py -- it reads the fixture only to know which ids are
duplicates, then deletes the extras from the live index, keeping exactly
one id per unique (namespace, title, text) chunk.

Usage:
    uv run python scripts/dedupe_vectors.py --dry-run   # report only
    uv run python scripts/dedupe_vectors.py              # actually delete

Caveat: if you ever wipe the index and re-run load_vectors.py against the
raw fixture, the duplicates come back -- re-run this script afterward.
"""
import argparse
import gzip
import json
import os
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from pinecone import Pinecone

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "data" / "pinecone_vectors.jsonl.gz"

PINECONE_HOST = os.environ.get("PINECONE_HOST", "http://localhost:5080")
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY", "pclocal")
INDEX_NAME = os.environ.get("PINECONE_INDEX", "tenk-filings")
DELETE_BATCH_SIZE = 1000


def get_index():
    pc = Pinecone(api_key=PINECONE_API_KEY, host=PINECONE_HOST)
    desc = pc.describe_index(INDEX_NAME)
    # same https-vs-http fix as load_vectors.py -- pinecone-local advertises
    # https in describe_index but only serves plain HTTP on the index port.
    host = desc.host.replace("https://", "http://")
    return pc.Index(host=host)


def find_duplicate_ids(path: Path) -> tuple[dict[str, list[str]], int, int]:
    """Scan the fixture and return (ids_to_delete_by_namespace, total_records,
    unique_count). Keeps the first-seen id per (namespace, title, text) group;
    every later id with the same key is marked for deletion."""
    seen: dict[tuple, str] = {}
    to_delete: dict[str, list[str]] = defaultdict(list)
    total = 0

    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            record = json.loads(line)
            namespace = record["namespace"]
            key = (namespace, record["metadata"].get("title"), record["metadata"]["text"])
            if key in seen:
                to_delete[namespace].append(record["id"])
            else:
                seen[key] = record["id"]

    return to_delete, total, len(seen)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report counts only, delete nothing")
    args = parser.parse_args()

    to_delete, total, unique_count = find_duplicate_ids(FIXTURE)
    dup_count = sum(len(ids) for ids in to_delete.values())

    print(f"total records in fixture:      {total}")
    print(f"unique (title, text) chunks:   {unique_count}")
    print(f"duplicate ids to delete:       {dup_count}")

    if args.dry_run:
        print("\n--dry-run: nothing deleted")
        return

    if dup_count == 0:
        print("\nnothing to delete")
        return

    index = get_index()
    before = index.describe_index_stats().total_vector_count
    print(f"\nindex count before: {before}")

    deleted = 0
    for namespace, ids in to_delete.items():
        for i in range(0, len(ids), DELETE_BATCH_SIZE):
            batch = ids[i : i + DELETE_BATCH_SIZE]
            index.delete(ids=batch, namespace=namespace)
            deleted += len(batch)
            print(f"deleted {deleted}/{dup_count}")

    after = index.describe_index_stats().total_vector_count
    print(f"index count after:  {after}")


if __name__ == "__main__":
    main()
