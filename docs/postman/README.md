# Postman tests — database

Tests for the database service API (`/api/v1`): is it up, does the key work, does searching
the uploaded sources return the right passages, and are bad requests refused.
The chat-model tests live in the **Isnad_app** repository.

| File                              | What it is                                              |
| --------------------------------- | ------------------------------------------------------- |
| `Isnad.postman_collection.json`   | All requests, with automatic checks                     |
| `Isnad.postman_environment.json`  | Variables (URL, key, query) — the key is left empty     |
| `search-tests.csv`                | Template for testing many queries at once (Runner)      |

## Setup

1. Postman → **Import** → the collection file, then the environment file.
2. Top-right environment selector → **Isnad**.
3. Environments → Isnad → fill the **Current value** column (never *Initial value*, which syncs
   to Postman's cloud):
   - `base_url` — the database service URL, no trailing slash
   - `site_key` — `SITE_API_KEY` from Railway → Variables
   - `query` — a text from your uploaded sources
4. **Save**.

## Folders

- **A — run in order.** 1 health · 2 site config (checks the key) · 3 search the sources
  (results printed in the Console, bottom-left).
- **B — must be rejected:** wrong key / no key → 401, empty query / bad event → 422.
- **C — statistics:** records a visit, a search and a question; they appear in the dashboard's
  reports.

## Many queries at once

Fill `search-tests.csv` from your own sources (`query`, `expected_source` = file name as shown
in the dashboard, `min_similarity`; leave `expected_source` empty for text that should match
nothing). Collection → **Run** → select only "3 — البحث في المصادر" → **Select File** → the CSV
→ **Run**.

Similarity: a word-for-word quote = 1.0 · two words missing or one changed ≈ 0.58–0.85 · not in the sources ≈ 0.42–0.61 (the website's thresholds are 0.90 / 0.60).
