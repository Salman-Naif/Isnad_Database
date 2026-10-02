"""
Import hadith collections from JSON or CSV files (e.g. the public sunnah.com datasets).

    # Convert to Isnad's format (data/structured/<name>.json), ready to upload from the dashboard:
    python scripts/import_hadiths.py bukhari.json "Sahih Bukhari.csv"

    # What indexing them would cost, measured on a sample with the real embedding model:
    python scripts/import_hadiths.py bukhari.json muslim.json --estimate

    # Name the book, and set a ruling the team has decided for every hadith in it
    # (only used for hadiths the file gives no ruling of its own):
    python scripts/import_hadiths.py bukhari.json --source "صحيح البخاري" --hukm صحيح --mohaddith البخاري

    # Index straight into this service's database (same pipeline as a dashboard upload):
    python scripts/import_hadiths.py bukhari.json --index

Folders are searched for .json and .csv files. Formats: see app/services/hadith_import.py.
Built and tested on https://github.com/abdelrahmaan/Hadith-Data-Sets (CSV) and
https://github.com/AhmedBaset/hadith-json (JSON) — credits in docs/DATA_SOURCES.md.
"""

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # allow `python scripts/...` from any folder
# Windows consoles default to a legacy code page that cannot print Arabic.
sys.stdout.reconfigure(encoding="utf-8")

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services.extraction import ExtractionError  # noqa: E402
from app.services.hadith_import import (  # noqa: E402
    COLLECTION_EXTENSIONS,
    Collection,
    read_collection,
    to_isnad_json,
)
from app.services.text_processing import clean  # noqa: E402

OUT_DIR = ROOT / "data" / "structured"
SAMPLE_SIZE = 200


@dataclass
class Estimate:
    hadiths: int
    characters: int
    tokens: int
    cost: float
    sample_cost: float


def embedded_texts(collection: Collection) -> list[str]:
    """Exactly what indexing sends to the embedding model."""
    limit = get_settings().embedding_max_input_chars
    return [clean(r.text)[:limit] for r in collection.records]


def estimate(texts: list[str], sample_size: int = SAMPLE_SIZE, client: httpx.Client | None = None) -> Estimate:
    """Embed a random sample with EMBEDDING_MODEL, read the tokens and cost OpenRouter reports
    for it, and scale up by characters. Costs a tiny fraction of the full run."""
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise SystemExit("OPENROUTER_API_KEY is needed to measure the cost")
    # A fixed seed, so repeated estimates measure the same sample (not used for security).
    sample = random.Random(7).sample(texts, min(sample_size, len(texts)))  # noqa: S311  # nosec B311
    client = client or httpx.Client(timeout=60)
    res = client.post(
        f"{settings.openrouter_base_url}/embeddings",
        headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
        json={"model": settings.embedding_model, "input": sample},
    )
    res.raise_for_status()
    usage = res.json().get("usage") or {}
    sample_chars = sum(len(t) for t in sample) or 1
    sample_tokens = int(usage.get("prompt_tokens") or 0)
    sample_cost = float(usage.get("cost") or 0)
    total_chars = sum(len(t) for t in texts)
    scale = total_chars / sample_chars
    return Estimate(len(texts), total_chars, round(sample_tokens * scale), sample_cost * scale, sample_cost)


def find_files(paths: list[Path]) -> list[Path]:
    files = []
    for path in paths:
        if path.is_dir():
            files += sorted(p for p in path.rglob("*") if p.suffix.lower() in COLLECTION_EXTENSIONS)
        else:
            files.append(path)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description="Import hadith collections from JSON or CSV files")
    parser.add_argument("paths", nargs="+", type=Path, help="JSON/CSV files or folders")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="where converted files are written")
    parser.add_argument("--source", default="", help="book name shown with each hadith (default: from the file)")
    parser.add_argument("--hukm", default="", help="ruling for hadiths that have none in the file")
    parser.add_argument("--mohaddith", default="", help="who gave that ruling")
    parser.add_argument("--estimate", action="store_true", help="measure what indexing would cost")
    parser.add_argument("--index", action="store_true", help="index into this service's database")
    args = parser.parse_args()
    if args.mohaddith and not args.hukm:
        parser.error("--mohaddith goes with --hukm")

    files = find_files(args.paths)
    if not files:
        sys.exit("No .json or .csv files found")

    totals = Estimate(0, 0, 0, 0.0, 0.0)
    failed = 0
    for path in files:
        try:
            collection = read_collection(
                path.read_bytes(), path.name,
                source=args.source, default_hukm=args.hukm, default_mohaddith=args.mohaddith,
            )
        except ExtractionError as exc:
            failed += 1
            print(f"✗ {path.name}: {exc}")
            continue

        book = collection.records[0].source
        ruled = sum(bool(r.hukm) for r in collection.records)
        print(f"✓ {path.name}: {len(collection.records)} hadiths of «{book}»"
              f" — {ruled} with a ruling ({collection.graded} from the file)"
              + (f", {collection.skipped} empty rows skipped" if collection.skipped else ""))

        converted = to_isnad_json(collection)
        args.out.mkdir(parents=True, exist_ok=True)
        target = args.out / f"{path.stem}.json"
        target.write_bytes(converted)
        print(f"  → {target}")

        if args.estimate:
            e = estimate(embedded_texts(collection))
            totals = Estimate(totals.hadiths + e.hadiths, totals.characters + e.characters,
                              totals.tokens + e.tokens, totals.cost + e.cost, totals.sample_cost + e.sample_cost)
            print(f"  cost: {e.tokens:,} tokens ≈ ${e.cost:.4f} with {get_settings().embedding_model}")

        if args.index:
            from app.api.deps import get_embedder, get_vector_store
            from app.db.sqlite import init_db
            from app.services.sources import add_source

            init_db()
            source = add_source(converted, target.name, "command line", get_embedder(), get_vector_store())
            print(f"  indexed: {source.status} — {source.chunks} hadiths" + (f" ({source.error})" if source.error else ""))
            failed += source.status != "ready"

    if args.estimate and totals.hadiths:
        print(f"\nTotal: {totals.hadiths:,} hadiths, {totals.characters:,} characters, "
              f"{totals.tokens:,} tokens ≈ ${totals.cost:.4f} "
              f"(measuring cost ${totals.sample_cost:.6f})")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
