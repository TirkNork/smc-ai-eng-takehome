"""Build the 10-K vector index from the source PDFs, chunked by SEC section.

The provided fixture (data/pinecone_vectors.jsonl.gz) cuts every ~1000
characters regardless of content. This splits on the Form 10-K item structure
instead -- fixed by regulation, identical across all four filings -- then
chunks *within* a section, so no chunk spans two topics.

The result is a drop-in replacement for the fixture index; see
doc/vector-ingest.md for the contract that guarantees that.

Usage:
    uv sync --extra ingest
    uv run python scripts/build_vectors.py --dry-run
    uv run python scripts/build_vectors.py --index tenk-filings-v2
"""
import argparse
import bisect
import hashlib
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
FILINGS_DIR = ROOT / "10k_filings"

load_dotenv()
# Take the embedding model and dimension from the settings object the query
# path uses. A drift between what we embed with and what vector.py queries
# with does not raise -- it returns quietly useless matches -- so the two
# must share one source.
sys.path.insert(0, str(ROOT))
from app.config import settings  # noqa: E402

# PDF file -> (company, metadata.title). The titles are load-bearing: vector.py
# filters on them and check_grounding maps them back to a company. They cannot
# be derived from the filename -- "Alphabet_10K_FY2025.pdf" holds the filing
# titled "goog-20251231" -- so they are pinned here.
FILINGS = [
    ("Apple_10K_FY2025.pdf", "Apple", "aapl-20250927"),
    ("Amazon_10K_FY2025.pdf", "Amazon", "amzn-20251231"),
    ("Alphabet_10K_FY2025.pdf", "Google", "goog-20251231"),
    ("Meta_10K_FY2025.pdf", "Meta", "meta-20251231"),
]

# Canonical item titles in regulation order. Doubles as the ordering key for
# heading selection and as the `section` metadata value.
ITEM_TITLES = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures",
    "5": "Market for Registrant's Common Equity",
    "6": "[Reserved]",
    "7": "Management's Discussion and Analysis",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9": "Changes in and Disagreements with Accountants",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "9C": "Foreign Jurisdictions that Prevent Inspections",
    "10": "Directors, Executive Officers and Corporate Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership of Certain Beneficial Owners and Management",
    "13": "Certain Relationships and Related Transactions",
    "14": "Principal Accountant Fees and Services",
    "15": "Exhibits and Financial Statement Schedules",
    "16": "Form 10-K Summary",
}

ITEM_RE = re.compile(r"^[ \t]*Item[ \t]+(\d{1,2}[A-C]?)[.\s]", re.MULTILINE | re.IGNORECASE)

# A page carrying this many item headings is the table of contents, not body
# text. Every filing's TOC lists all 23 at once; no body page comes close.
TOC_HEADING_THRESHOLD = 8

# Drop a line whose digit-normalised form appears on more than this share of
# pages -- that is running header/footer furniture, not filing text.
BOILERPLATE_PAGE_SHARE = 0.2

TARGET_CHARS = 900
OVERLAP_CHARS = 130
MIN_CHUNK_CHARS = 100
EMBED_BATCH = 100
UPSERT_BATCH = 100


def _digit_normalised(line: str) -> str:
    # The running footer differs per page only by its page number ("Apple Inc.
    # | 2025 Form 10-K | 7"), so counting raw lines finds just one of the three
    # boilerplate families in these files. Normalising digits collapses all
    # three to a single repeated form.
    return re.sub(r"\d+", "#", line)


def _boilerplate_patterns(pages: list[str]) -> set[str]:
    counts: Counter[str] = Counter()
    for text in pages:
        # Per *page* presence -- a line repeated twice on one page is not
        # thereby boilerplate.
        seen = {line.strip() for line in text.splitlines() if line.strip()}
        counts.update(_digit_normalised(line) for line in seen)

    threshold = len(pages) * BOILERPLATE_PAGE_SHARE
    return {pattern for pattern, n in counts.items() if n > threshold}


def _clean_page(text: str, boilerplate: set[str]) -> str:
    kept = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(line for line in kept if _digit_normalised(line) not in boilerplate)


def _read_pages(path: Path) -> list[str]:
    # NFKD: these PDFs are browser prints carrying ligature codepoints, so
    # "significant" is stored as "signiﬁcant" and "file:///" as "ﬁle:///".
    # Left alone they embed as characters no query will ever contain.
    reader = PdfReader(str(path))
    return [unicodedata.normalize("NFKD", page.extract_text() or "") for page in reader.pages]


def _item_key(item: str) -> tuple[int, str]:
    match = re.match(r"(\d+)([A-C]?)", item)
    return int(match.group(1)), match.group(2)


def _longest_increasing_chain(candidates: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Pick the real heading sequence out of the regex's candidates.

    Filings cross-reference items in body text ("as discussed in Item 8") and
    the regex cannot tell a reference from a heading. Real headings are the
    longest run appearing in regulation order, so an LIS over the item key
    selects them.

    Taking each next-larger item greedily instead would be wrong: Meta's
    Item 8 is cross-referenced on page 117, before the genuine Item 7A heading
    on page 132, so a greedy pass locks onto the reference and must then
    discard both the real 7A and the real Item 8 on page 135.
    """
    if not candidates:
        return []

    n = len(candidates)
    length = [1] * n
    previous = [-1] * n
    for i in range(n):
        for j in range(i):
            if _item_key(candidates[j][1]) < _item_key(candidates[i][1]) and length[j] + 1 > length[i]:
                length[i] = length[j] + 1
                previous[i] = j

    index = max(range(n), key=lambda i: length[i])
    chain = []
    while index != -1:
        chain.append(candidates[index])
        index = previous[index]
    return chain[::-1]


def _page_of(offset: int, page_starts: list[int]) -> int:
    return bisect.bisect_right(page_starts, offset) - 1


@dataclass
class Section:
    item: str
    title: str
    start: int
    end: int


def _find_sections(document: str, page_starts: list[int], toc_pages: set[int]) -> list[Section]:
    candidates = [
        (match.start(), match.group(1).upper())
        for match in ITEM_RE.finditer(document)
        if _page_of(match.start(), page_starts) not in toc_pages
    ]
    chain = _longest_increasing_chain(candidates)

    return [
        Section(
            item=item,
            title=ITEM_TITLES.get(item, "Unknown"),
            start=offset,
            end=chain[i + 1][0] if i + 1 < len(chain) else len(document),
        )
        for i, (offset, item) in enumerate(chain)
    ]


# Note the absence of ":". In a 10-K a colon almost always introduces a table
# or list -- "net sales by category for 2025, 2024 and 2023 were as follows
# (dollars in millions):" -- so breaking there files the caption in one chunk
# and the figures it names in the next, leaving a block of bare numbers that
# no longer says what it is a table of.
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


def _split_at_sentence(text: str, target: int) -> int:
    """Cut at the last sentence boundary before `target`, else at `target`."""
    if len(text) <= target:
        return len(text)

    boundaries = [m.end() for m in _SENTENCE_END.finditer(text, int(target * 0.6), target)]
    return boundaries[-1] if boundaries else target


def _snap_to_sentence_start(text: str, position: int) -> int:
    """Move `position` forward to just after the next sentence end.

    Stepping back OVERLAP_CHARS to build the overlap lands mid-clause, so
    without this every chunk after the first opens on a fragment ("d not be
    considered a complete statement..."). Keeps the raw position if no
    boundary is near, rather than skipping real text.
    """
    match = _SENTENCE_END.search(text, position, position + OVERLAP_CHARS * 2)
    return match.end() if match else position


def _chunk_section(text: str) -> list[str]:
    chunks = []
    position = 0
    while position < len(text):
        remainder = text[position:]
        cut = _split_at_sentence(remainder, TARGET_CHARS)
        chunk = remainder[:cut].strip()
        if len(chunk) >= MIN_CHUNK_CHARS:
            chunks.append(chunk)
        if position + cut >= len(text):
            break
        position = _snap_to_sentence_start(text, position + max(cut - OVERLAP_CHARS, 1))
    return chunks


@dataclass
class Chunk:
    id: str
    text: str
    page: int
    company: str
    title: str
    item: str
    section: str


def build_chunks(pdf_path: Path, company: str, title: str) -> tuple[list[Chunk], dict]:
    raw_pages = _read_pages(pdf_path)
    boilerplate = _boilerplate_patterns(raw_pages)
    toc_pages = {
        i for i, text in enumerate(raw_pages)
        if len(ITEM_RE.findall(text)) >= TOC_HEADING_THRESHOLD
    }

    page_starts = []
    offset = 0
    cleaned = []
    for text in raw_pages:
        page_starts.append(offset)
        page = _clean_page(text, boilerplate)
        cleaned.append(page)
        offset += len(page) + 1  # +1 for the "\n" join below
    document = "\n".join(cleaned)

    chunks: list[Chunk] = []
    seen: set[str] = set()
    duplicates = 0
    for section in _find_sections(document, page_starts, toc_pages):
        body = document[section.start:section.end]
        for text in _chunk_section(body):
            fingerprint = hashlib.sha1(" ".join(text.split()).lower().encode()).hexdigest()
            if fingerprint in seen:
                duplicates += 1
                continue
            seen.add(fingerprint)

            local = body.find(text[:60])
            chunks.append(
                Chunk(
                    # Deterministic, so a re-run upserts over the same ids
                    # instead of accumulating a second copy of every chunk --
                    # the failure mode that put duplicates in the fixture.
                    id=f"{title}-{section.item}-{len(chunks):04d}",
                    text=text,
                    page=_page_of(section.start + max(local, 0), page_starts),
                    company=company,
                    title=title,
                    item=section.item,
                    section=section.title,
                )
            )

    return chunks, {"pages": len(raw_pages), "duplicates": duplicates}


def _batched(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def embed(chunks: list[Chunk]) -> list[list[float]]:
    client = OpenAI(api_key=settings.openai_api_key)
    vectors = []
    for batch in _batched(chunks, EMBED_BATCH):
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=[c.text for c in batch],
            dimensions=settings.openai_embedding_dim,
        )
        vectors.extend(item.embedding for item in response.data)
        print(f"  embedded {len(vectors)}/{len(chunks)}")
    return vectors


def get_index(name: str):
    client = Pinecone(api_key=settings.pinecone_api_key, host=settings.pinecone_host)

    if name not in {i["name"] for i in client.list_indexes()}:
        print(f"creating index '{name}' (dim={settings.openai_embedding_dim}, metric=cosine)")
        client.create_index(
            name=name,
            dimension=settings.openai_embedding_dim,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )

    # pinecone-local advertises https but serves plain HTTP on the per-index
    # port -- same workaround as scripts/load_vectors.py.
    described = client.describe_index(name)
    return client.Index(host=described.host.replace("https://", "http://"))


def upsert(index, chunks: list[Chunk], vectors: list[list[float]]) -> None:
    payload = [
        {
            "id": chunk.id,
            "values": vector,
            # title/text/page are the contract; company/item/section are extra,
            # projected away by vector.py, and exist so section filtering and
            # richer citations can be added without another re-ingest.
            "metadata": {
                "title": chunk.title,
                "text": chunk.text,
                "page": chunk.page,
                "company": chunk.company,
                "item": chunk.item,
                "section": chunk.section,
            },
        }
        for chunk, vector in zip(chunks, vectors)
    ]
    done = 0
    for batch in _batched(payload, UPSERT_BATCH):
        index.upsert(vectors=batch, namespace="__default__")
        done += len(batch)
        print(f"  upserted {done}/{len(payload)}")


def report(company: str, title: str, chunks: list[Chunk], stats: dict) -> None:
    per_item = Counter(c.item for c in chunks)
    lengths = sorted(len(c.text) for c in chunks)
    print(f"\n{company:8s} {title:16s} {len(chunks):4d} chunks   "
          f"{stats['pages']}p, {len(per_item)} sections with text, "
          f"{stats['duplicates']} dups dropped, median {lengths[len(lengths) // 2]} chars")
    print("         " + "  ".join(f"{item}:{n}" for item, n in per_item.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", default=settings.pinecone_index,
                        help="target index name (default: PINECONE_INDEX)")
    parser.add_argument("--dry-run", action="store_true",
                        help="parse and report only -- no embedding calls, no writes")
    parser.add_argument("--clear", action="store_true",
                        help="empty the index first. Required when rebuilding after a chunking "
                             "change: ids carry a per-section running number, so a build "
                             "producing fewer chunks leaves the surplus ids behind.")
    args = parser.parse_args()

    all_chunks: list[Chunk] = []
    for filename, company, title in FILINGS:
        path = FILINGS_DIR / filename
        if not path.exists():
            raise SystemExit(f"filing not found: {path}")
        chunks, stats = build_chunks(path, company, title)
        report(company, title, chunks, stats)
        all_chunks.extend(chunks)

    print(f"\ntotal {len(all_chunks)} chunks")
    if args.dry_run:
        print("dry run -- nothing embedded or written")
        return

    print(f"\nembedding with {settings.openai_embedding_model} "
          f"(dim={settings.openai_embedding_dim})")
    vectors = embed(all_chunks)

    print(f"\nupserting into '{args.index}' namespace '__default__'")
    index = get_index(args.index)
    if args.clear:
        for namespace in (index.describe_index_stats().namespaces or {}):
            index.delete(delete_all=True, namespace=namespace)
            print(f"  cleared namespace '{namespace}'")
    upsert(index, all_chunks, vectors)

    print("\ndone.")
    print(index.describe_index_stats())


if __name__ == "__main__":
    main()
