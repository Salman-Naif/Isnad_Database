"""
Preview extraction: read every supported file in data/raw and save the cleaned
text to data/processed/<name>.txt — useful for checking OCR quality before indexing.

    python scripts/extract_text.py

This step is optional; build_database.py reads data/raw directly.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # allow `python scripts/...` from any folder
# Windows consoles default to a legacy code page that cannot print Arabic.
sys.stdout.reconfigure(encoding="utf-8")

from app.services.extraction import SUPPORTED_EXTENSIONS, ExtractionError, extract_text  # noqa: E402
from app.services.text_processing import clean  # noqa: E402

RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    files = [
        p for p in sorted(RAW_DIR.rglob("*"))
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    if not files:
        print(f"No supported files in {RAW_DIR}")
        return

    for path in files:
        try:
            extracted = extract_text(
                path.read_bytes(), path.name, lambda line: print(f"  {line}", end="\r", flush=True)
            )
        except ExtractionError as exc:
            print(f"✗ {path.name}: {exc}")
            continue
        text = clean(extracted.text)
        out = PROCESSED_DIR / f"{path.stem}.txt"
        out.write_text(text, encoding="utf-8")
        ocr = f", {extracted.ocr_pages} OCR pages" if extracted.ocr_pages else ""
        print(f"✓ {path.name} → {out.name} ({len(text)} chars{ocr})")
        if extracted.note:
            print(f"  ! {extracted.note}")


if __name__ == "__main__":
    main()
