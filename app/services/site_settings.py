"""
Controls for the main website, edited from the dashboard and read by the site
through /api/v1/site-config.
"""

import json
import secrets

from app.db.sqlite import connection
from app.models.schemas import SiteSettings

_SETTINGS_KEY = "site"
_VISITOR_SALT_KEY = "visitor_salt"


def get_site_settings() -> SiteSettings:
    with connection() as conn:
        row = conn.execute(
            "SELECT value FROM site_settings WHERE key = ?", (_SETTINGS_KEY,)
        ).fetchone()
    # Unknown or missing keys fall back to the defaults in SiteSettings.
    return SiteSettings(**json.loads(row["value"])) if row else SiteSettings()


def save_site_settings(settings: SiteSettings) -> SiteSettings:
    with connection() as conn:
        conn.execute(
            """INSERT INTO site_settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (_SETTINGS_KEY, settings.model_dump_json()),
        )
    return settings


def visitor_salt() -> str:
    """Random salt for hashing visitor ids, created once and kept in the database.

    Stored rather than derived from a key, so rotating SITE_API_KEY doesn't make
    returning visitors look new in the reports.
    """
    with connection() as conn:
        row = conn.execute(
            "SELECT value FROM site_settings WHERE key = ?", (_VISITOR_SALT_KEY,)
        ).fetchone()
        if row:
            return row["value"]
        salt = secrets.token_hex(16)
        conn.execute(
            "INSERT OR IGNORE INTO site_settings (key, value) VALUES (?, ?)",
            (_VISITOR_SALT_KEY, salt),
        )
        return conn.execute(
            "SELECT value FROM site_settings WHERE key = ?", (_VISITOR_SALT_KEY,)
        ).fetchone()["value"]
