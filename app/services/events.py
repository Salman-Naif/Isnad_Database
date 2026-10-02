"""
Visits, searches and chat questions reported by the main website.

These feed the dashboard statistics and the exported reports. The visitor id
the site sends is hashed with a private salt before storage, so the database
can count unique visitors without holding anything that identifies them.
"""

import hashlib
from datetime import UTC, datetime

from app.db.sqlite import connection
from app.models.schemas import EventIn
from app.services.site_settings import visitor_salt


def record_event(event: EventIn) -> None:
    visitor_hash = None
    if event.visitor_id:
        digest = hashlib.sha256(f"{visitor_salt()}:{event.visitor_id}".encode())
        visitor_hash = digest.hexdigest()[:32]

    with connection() as conn:
        conn.execute(
            """INSERT INTO events (type, visitor_hash, query, result, latency_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                event.type,
                visitor_hash,
                event.query.strip() or None,
                event.result.strip() or None,
                event.latency_ms,
                datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
