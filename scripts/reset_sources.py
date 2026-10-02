"""
Remove every source — vectors, texts, uploaded originals and their records — keeping users,
website settings and statistics. For a fresh start, or when the disk is so full that deleting
from the dashboard fails.

    python scripts/reset_sources.py --yes

On Railway: open a shell in the database service (`railway ssh`), run the command above, then
restart the service (Deployments → ⋯ → Restart): the running service still holds the old
vector files open, and their space is only released when it stops. It starts with an empty
vector database.

Works on a full disk: the vector database's files and the originals are deleted first, which
frees the space SQLite needs to update its own tables.
"""

import argparse
import re
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # allow `python scripts/...` from any folder
# Windows consoles default to a legacy code page that cannot print Arabic.
sys.stdout.reconfigure(encoding="utf-8")

from app.config import get_settings  # noqa: E402

# ChromaDB's files: its database and one folder per vector index, named by a UUID.
_CHROMA_FILES = re.compile(r"^chroma\.sqlite3(-wal|-shm|-journal)?$")
_INDEX_FOLDER = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def size_of(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def delete_vector_files(chroma_dir: Path) -> int:
    """Delete ChromaDB's files only; the app database may live in the same folder."""
    freed = 0
    if not chroma_dir.exists():
        return 0
    for entry in chroma_dir.iterdir():
        if (entry.is_file() and _CHROMA_FILES.match(entry.name)) or (entry.is_dir() and _INDEX_FOLDER.match(entry.name)):
            freed += size_of(entry)
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    return freed


def delete_originals(uploads_dir: Path) -> int:
    freed = 0
    if uploads_dir.exists():
        for entry in uploads_dir.iterdir():
            freed += size_of(entry)
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    return freed


def clear_records(sqlite_path: Path) -> int:
    """Forget the sources and their texts; users, settings and statistics stay."""
    if not sqlite_path.exists():
        return 0
    conn = sqlite3.connect(sqlite_path, timeout=30, isolation_level=None)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table')")}
        removed = 0
        for table in ("sources", "passages_fts", "passages"):
            if table in tables:
                # Fixed table names from the tuple above; nothing from outside is joined in.
                removed += conn.execute(f"DELETE FROM {table}").rowcount  # noqa: S608  # nosec B608
        try:
            conn.execute("VACUUM")
        except sqlite3.OperationalError as exc:  # needs some free space; the deletes are done
            print(f"  (compaction skipped: {exc})")
        return removed
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove every source, keeping users, settings and statistics")
    parser.add_argument("--yes", action="store_true", help="confirm: delete all sources")
    args = parser.parse_args()
    if not args.yes:
        parser.error("this deletes every uploaded source — add --yes to confirm")

    settings = get_settings()
    freed = delete_vector_files(Path(settings.chroma_dir))
    freed += delete_originals(Path(settings.uploads_dir))
    rows = clear_records(Path(settings.sqlite_path))
    print(f"Done: {freed / 2**20:.0f} MB of vectors and originals deleted, {rows} records cleared.")
    print("Users, website settings and statistics are kept. Restart the service now.")


if __name__ == "__main__":
    main()
