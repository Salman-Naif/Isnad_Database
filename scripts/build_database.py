"""
Bulk-load sources from local folders (same pipeline as the dashboard upload).

    python scripts/build_database.py                 # data/raw + data/structured
    python scripts/build_database.py --raw-dir books # a different documents folder

Indexes:
  - every supported file in data/raw (PDF, Word, text, scanned images)
  - every JSON file in data/structured (structured hadiths with ruling and sanad)

Files loaded here appear in the dashboard's file list like any upload.
Safe to re-run: each file replaces what was previously indexed from it.
"""

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # allow `python scripts/...` from any folder
# Windows consoles default to a legacy code page that cannot print Arabic.
sys.stdout.reconfigure(encoding="utf-8")

from app.api.deps import get_embedder, get_vector_store  # noqa: E402
from app.db.sqlite import init_db  # noqa: E402
from app.services.extraction import SUPPORTED_EXTENSIONS, ExtractionError  # noqa: E402
from app.services.sources import SourceBusyError, add_source  # noqa: E402

RAW_DIR = ROOT / "data" / "raw"
STRUCTURED_DIR = ROOT / "data" / "structured"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--structured-dir", type=Path, default=STRUCTURED_DIR)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    init_db()
    embedder, store = get_embedder(), get_vector_store()

    paths = [
        path
        for path in sorted(args.raw_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ] + sorted(args.structured_dir.glob("*.json"))

    if not paths:
        print(f"No files found in {args.raw_dir} or {args.structured_dir}")
        return

    failed = 0
    for path in paths:
        try:
            source = add_source(path.read_bytes(), path.name, "command line", embedder, store)
        except (ExtractionError, SourceBusyError) as exc:
            failed += 1
            print(f"✗ {path.name}: {exc}")
            continue
        if source.status != "ready" or source.error:
            failed += 1
            print(f"✗ {path.name}: {source.error}")
            continue
        ocr = f", {source.ocr_pages} OCR pages" if source.ocr_pages else ""
        print(f"✓ {path.name}: {source.chunks} chunks ({source.kind}{ocr})")

    print(f"\nDone: {len(paths) - failed}/{len(paths)} files, {store.count()} items in the database")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
