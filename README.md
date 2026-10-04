# Isnad Database (قاعدة بيانات إسناد)

> The standalone database service of **Isnad** — an intelligent conversational system for
> verifying the authenticity of hadiths and Islamic quotes.

This service holds Isnad's sources and runs on its own URL, separate from the main website.
Only authorized users can open it, with a username and password. From its dashboard the team:

- uploads approved sources — **PDF, Word, text and scanned files, up to 100 MB each** — which
  are read (with OCR for scans), split into passages and converted into embeddings the chat
  model can search. Files are processed in the background with live progress;
- sees every uploaded file with its name, type, size, passages, uploader and date;
- controls the main website (maintenance mode, search/chat on or off, announcement banner);
- checks the health of the main website, the API keys, the embedding model and the databases;
- follows visits, visitors, searches and chat questions, and exports reports to **Excel** or **PDF**.

The main website — public search, verification and chat with the model — is a separate project,
**Isnad_Website**, deployed as its own service. It connects to this database through a small API
protected by `SITE_API_KEY`; this repository contains the database only.

**Team:** فريق إسناد (Isnad) — سلمان نايف المحيسن (almuhaysins@outlook.sa) ·
نوت عبدالعزيز الجهني (noota123db@gmail.com)

Isnad is the team's entry in **تحدي الذكاء الاصطناعي في خدمة المحتوى الإسلامي** (The AI
Challenge in Serving Islamic Content, مؤسسة باذل الأهلية, 2026). The entry's overview, the
judging criteria and their evidence, the chat's safety work and evaluation, and the running costs
are documented in the website repository: [Isnad_Website `docs/`](https://github.com/Salman-Naif/Isnad_Website/tree/main/docs).

## Documentation

| Document | What it covers |
| --- | --- |
| [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) | The books (published titles, compilers), the eight Shamela editions on the live service, the rulings and who gave them, rights, how the data is used and checked |
| [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) | Every component, service and model, with its license |
| Isnad_Website [`docs/AI.md`](https://github.com/Salman-Naif/Isnad_Website/blob/main/docs/AI.md) | الذكاء الاصطناعي في البناء وفي المنتج: أدوات التطوير، والخوارزميات والنماذج (بالعربية) |
| This README | The dashboard, uploads, search, isnad trees, security, deployment, every setting |

## License

The team's code is under the [MIT License](LICENSE). Third-party components, models, services
and data keep their own licenses: [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) and
[`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md). The converted hadith books are not redistributed here.

---

## Dashboard

| Tab                         | What it does                                                                         |
| --------------------------- | ------------------------------------------------------------------------------------ |
| الحالة — Status             | Last-30-day figures and a live check of every part of the system                     |
| المصادر — Sources           | Drag-and-drop upload; list of uploaded files with download and delete                |
| التحكم بالموقع — Site       | Maintenance mode and message, search/chat switches, announcement, main website URL   |
| الإحصائيات والتقارير — Reports | Visits, unique visitors, searches, questions, daily chart, top queries; Excel/PDF export |
| المستخدمون — Users          | Authorized users; the system manager adds and removes them                           |

### System checks

App database · vector database · embedding model · OCR (vision model, Tesseract fallback) ·
free disk space · `SITE_API_KEY` · OpenRouter key (valid, usage, remaining credit) ·
main website (`<url>/health`).

## Tech stack

| Layer           | Technology                                                      |
| --------------- | --------------------------------------------------------------- |
| Language        | Python 3.11.9                                                   |
| Server + UI     | FastAPI + Jinja2                                                |
| Embeddings      | OpenRouter API — `qwen/qwen3-embedding-4b` (no local model)       |
| Vector database | ChromaDB                                                        |
| Text extraction | PDFium (pypdfium2) · python-docx                                |
| OCR             | Vision models on OpenRouter (Gemini) · Tesseract fallback       |
| App database    | SQLite (users, sessions, file registry, site settings, stats)   |
| Reports         | openpyxl (Excel) · reportlab + arabic-reshaper + python-bidi (PDF) |
| Deployment      | Docker on Railway                                               |

## Project structure

```
isnad/
├── app/
│   ├── main.py                 # Entry point, security headers, route registration
│   ├── config.py               # Settings and API keys from environment variables
│   ├── api/
│   │   ├── deps.py             # Shared dependencies, admin login and SITE_API_KEY checks
│   │   └── routes/
│   │       ├── pages.py        # /login and the dashboard (/)
│   │       ├── auth.py         # Login / logout
│   │       ├── admins.py       # Authorized users
│   │       ├── sources.py      # Upload, list, download, delete sources
│   │       ├── control.py      # Main website controls and system status
│   │       ├── reports.py      # Statistics and Excel/PDF export
│   │       ├── site_api.py     # /api/v1 — API for the main website
│   │       └── health.py       # /health for Railway
│   ├── core/
│   │   ├── security.py         # Password hashing and session tokens
│   │   ├── rate_limit.py       # Login attempt limiting
│   │   └── logging.py
│   ├── db/sqlite.py            # App database schema
│   ├── models/schemas.py       # Request and response models
│   ├── services/
│   │   ├── extraction.py       # PDF / Word / text / scanned → text
│   │   ├── ocr.py              # Page layout, vision-model OCR with cross-check, Tesseract
│   │   ├── text_processing.py  # Arabic cleaning and chunking
│   │   ├── hadith_import.py    # Hadith collections in JSON / CSV → records; matn; titles
│   │   ├── books.py            # The nine books: published titles, compilers
│   │   ├── text_index.py       # Literal index (SQLite FTS5) for word-for-word quotes
│   │   ├── embeddings.py       # Text → vector
│   │   ├── vector_store.py     # ChromaDB storage and search
│   │   ├── ingestion.py        # file → chunks → embeddings → ChromaDB
│   │   ├── sources.py          # File registry and stored originals
│   │   ├── sanad.py            # Sanad chain formatting
│   │   ├── isnad_tree.py       # Chains read from a narration's wording → isnad tree
│   │   ├── auth.py             # Accounts and sessions
│   │   ├── site_settings.py    # Main website controls
│   │   ├── events.py           # Visits and questions reported by the website
│   │   ├── status.py           # System checks
│   │   └── reports.py          # Statistics, Excel and PDF
│   ├── templates/              # base · login · dashboard
│   └── static/                 # CSS · JS
├── scripts/
│   ├── manage_admins.py        # Create / list / delete users, reset passwords
│   ├── build_database.py       # Bulk-load files from data/raw and data/structured
│   ├── extract_text.py         # Preview extracted / OCR'd text
│   ├── import_shamela.py       # Convert Shamela editions: text, chain, matn, recorded ruling
│   ├── shamela/ShamelaExport.java  # Reads a book's pages from Shamela's Lucene index
│   ├── import_hadiths.py       # Convert / index / measure the cost of hadith collections (JSON, CSV)
│   └── reset_sources.py        # Remove every source, keep users/settings/stats (full disk)
├── data/                       # Local folders for bulk loading (not committed)
├── docs/
│   ├── hadith_format.example.json  # JSON format for structured hadith uploads
│   └── DATA_SOURCES.md         # The Shamela editions, rulings, rights and credits
├── tests/
│   ├── unit/ · integration/ · api/ · security/ · system/   # one folder per test level
│   └── conftest.py             # fakes and fixtures shared by the tests
├── .github/workflows/ci.yml    # lint, scans, tests, Docker build on every push
├── Dockerfile
├── railway.json
├── pyproject.toml              # pytest, coverage, ruff and bandit settings
├── requirements.txt            # what the service needs to run
└── requirements-dev.txt        # + test, lint and security-scan tools
```

## Default user

On the very first start (while the database has no users) the service creates:

| Username | Password |
| -------- | -------- |
| `salman` | `123456` |

After signing in, a banner asks you to change the password: **المستخدمون → حسابي — تغيير كلمة المرور**.
Do it right after the first deploy — until then anyone with the URL and this password can sign in.
New passwords need at least 8 characters. To use other defaults, set `ADMIN_USERNAME` /
`ADMIN_PASSWORD` before the first deploy.

This user (`ADMIN_USERNAME`) is the **system manager**: the only one who can add and delete
users, and no one — not even from `scripts/manage_admins.py` — can delete it. Other users can
upload, control the site and read reports, and change their own password.

## Running locally (optional)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env — then fill in the keys
uvicorn app.main:app --reload
```

Open `http://localhost:8000` and sign in with the default user. Uploads and searches need
`OPENROUTER_API_KEY` (embeddings and OCR come from the API). Tesseract is only the OCR
fallback; to have it locally, install it from https://github.com/UB-Mannheim/tesseract/wiki
with "Arabic" ticked.

## Development and testing

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt   # the app's requirements + test, lint and scan tools
```

The tests are grouped by level, one folder each, and each level can be run on its own:

| Level         | Folder               | What it checks                                                        |
| ------------- | -------------------- | --------------------------------------------------------------------- |
| Unit          | `tests/unit`         | One function or class alone, no database or network                  |
| Integration   | `tests/integration`  | Components together: SQLite, ChromaDB, files, the upload pipeline, scripts                  |
| API           | `tests/api`          | Every endpoint's status codes, response shape and input validation    |
| Security      | `tests/security`     | Access to every route, injection, uploads, sessions, headers, secrets |
| System        | `tests/system`       | The real server as a process over real HTTP, end to end; restart keeps the data |

```bash
pytest                      # everything
pytest -m unit              # one level: unit | integration | api | security | system
pytest --cov                # with coverage (must stay at 90% or more)
ruff check .                # lint
bandit -c pyproject.toml -r app scripts   # code security scan
pip-audit -r requirements-dev.txt --ignore-vuln PYSEC-2026-3813 --ignore-vuln PYSEC-2026-3814 --ignore-vuln PYSEC-2026-3815   # known vulnerabilities in dependencies
```

The tests never read your `.env` and never call OpenRouter: the model provider is replaced by
fakes, and in the system tests by a local stub server. The system tests also run the Postman
collection in `docs/postman` with Newman when Node.js is installed.

**CI** (`.github/workflows/ci.yml`) runs all of this on every push to `main` and every pull
request, then builds the Docker image and checks that it starts and answers `/health`.

## Supported sources

| Input                          | How it's read                                               | Stored as                                       |
| ------------------------------ | ----------------------------------------------------------- | ----------------------------------------------- |
| PDF (text)                     | PDFium text layer                                           | passages, no ruling/sanad                       |
| PDF (scanned)                  | pages rendered at 300 DPI and OCR'd (JBIG2 scans included)  | passages, no ruling/sanad                       |
| Word `.docx`                   | paragraphs and tables; pasted page scans are OCR'd          | passages, no ruling/sanad                       |
| Text `.txt` / `.md`            | UTF-8, UTF-8 BOM, UTF-16 or Windows-1256                    | passages, no ruling/sanad                       |
| Images (`.png` `.jpg` `.tif`…) | OCR, every page of a multi-page TIFF                        | passages, no ruling/sanad                       |
| JSON (structured hadiths)      | array of records like `docs/hadith_format.example.json`     | one item per hadith with ruling, scholar, sanad |
| JSON (collection per book)     | one book per file: `metadata`, `chapters`, `hadiths`        | one item per hadith; chapter → topic; scholars' grades → ruling |
| CSV (hadith collections)       | one hadith per row; the longest column is the text          | one item per hadith (ruling only if the team sets one) |

### Scanned books (OCR)

PDFs are opened with **PDFium**, Chrome's PDF engine: it reads every PDF, including scans
compressed with JBIG2, JPX or CCITT that pure-Python readers cannot decode (the four hadith
books this was tuned on — Bukhari, Muslim, Tirmidhi, Ibn Majah — are all JBIG2 scans). A
page's text layer is used when it is real text; a page without one, or with an unusable one
(garbled automatic OCR, letters split apart, Arabic stored backwards), is rendered at 300 DPI
and read with OCR:

1. **Layout.** The page is straightened if it was scanned at an angle, the running header is
   cut off, and a two-column page is split at its gutter. Every image sent for reading is one
   column, read top to bottom; text that runs across both columns (titles, footnotes) stays
   whole, in its place.
2. **Reading.** A vision model on OpenRouter (`OCR_MODEL`, default Gemini 3 Flash) transcribes
   each column letter for letter, diacritics included.
3. **Cross-check.** A second model (`OCR_CHECK_MODEL`) reads the same column independently. If
   the readings differ by more than a couple of words, or one of them lacks a phrase the other
   has (a skipped line), a third model (`OCR_REFEREE_MODEL`) reads it too and the majority wins.
4. **Review note.** Pages where no two readings agree are listed next to the file in the
   sources table, with page numbers, so the team can check them against the book. Pages read by
   the Tesseract fallback (vision model unreachable) are listed the same way.

On a sample of 24 random pages from the four books, the two independent readings matched on
41 of 46 columns; the referee settled the rest, and the differences left between models are
spelling variants such as إسحٰق / إسحاق and footnotes in small print.

Cost and time (one-time, per upload): about **$0.01 per page** with the cross-check
(~$0.006 without it, `OCR_CHECK_MODEL=`), ~3 seconds per page with 12 pages read in parallel.
The four books (5,316 pages) take about 4 hours and about $50. Without `OPENROUTER_API_KEY`, or
with `OCR_ENGINE=tesseract`, Tesseract's Arabic `tessdata_best` model is used instead — free,
but noticeably less accurate on dense, fully vowelled pages.

No OCR is literally perfect: marginal numbers and small-print footnotes are where the remaining
differences are. When a book is available as text (Word, txt — e.g. an export from a digital
library), upload that instead of a scan: it is exact and much faster to index.

### Hadith collections as text (JSON / CSV)

Besides Isnad's own JSON format, the importer reads hadith collections published as JSON (one
book per file, with `metadata`, `chapters` and `hadiths`) or CSV (one hadith per row) —
`app/services/hadith_import.py`, `scripts/import_hadiths.py`. Every book is stored and shown under
its published title with its compiler (`app/services/books.py`), whatever name its file uses.
Isnad's own sources are the Shamela editions below ([docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)).

### Hadith books from المكتبة الشاملة (Shamela)

The edited printed editions in an installed [Shamela](https://shamela.ws) desktop library — the
reference platform the challenge's reference pack names for the books of the Sunnah — can be
converted to Isnad's format with `scripts/import_shamela.py` (needs a JDK 21+, `javac`):

```
python scripts/import_shamela.py --list            # the hadith books installed (id, name)
python scripts/import_shamela.py 1681              # صحيح البخاري - ط السلطانية
python scripts/import_hadiths.py "data/structured/صحيح البخاري - ط السلطانية.json" --estimate
```

Shamela keeps each book's pages in a Lucene index; they are read with Shamela's own Lucene jars
(`scripts/shamela/ShamelaExport.java`). Its markup gives each hadith's number, **every narrator
of the chain as linked to Shamela's narrators database** (so the sanad is the edition's, not
read from the wording), the **matn** exactly as the edition marks it, the chapter, and the
**ruling the edition records**, with its author — al-Tirmidhi's own words («هذا حديث حسن صحيح»),
al-Albani's in Sunan Abi Dawud and Sunan Ibn Majah, the editors' in Musnad Ahmad ط الرسالة (the
phrase only). Nothing else of the footnotes is taken, and no ruling is ever made up (`--hukm` is
for one the team decides). A narration with several chains («ح») is left to the database.

The eight editions converted (all but Sunan al-Darimi, not installed yet): 63,815 hadiths, 25,486
with the edition's chain, 37,451 with a recorded ruling; embedding them all costs $0.25. The
files are written to `data/structured/`, which is never committed. Editions and rights:
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

### Disk space

Everything lives on the Volume (`/app/chroma_db`): the vectors (ChromaDB), the texts with their
literal index and the app data (SQLite), and the uploaded originals. Each text is stored once,
in SQLite; ChromaDB keeps only vectors and metadata. Measured: about **14 KB per hadith**
(narration + matn vectors at 1024 dimensions, text, index, original file) — the eight Shamela
editions (63,815 hadiths, 114,941 vectors) take **about 0.9 GB**: ~650 MB of vectors, ~130 MB of
texts and literal index, ~100 MB of original files. Indexing them took about 15 minutes.

- Before indexing a file, the service checks it will fit and refuses it up front with the space
  needed and available — never halfway through.
- Deleting a source gives its space back: SQLite files never shrink on their own, so after a
  delete the background worker compacts both databases (Chroma's own vacuum, then SQLite's).
- A full disk is reported as such ("مساحة التخزين ممتلئة …"), and the dashboard status shows the
  free space.
- If the disk is so full that even deleting fails (SQLite needs a little space to record a delete),
  grow the Volume, or run `python scripts/reset_sources.py --yes` in the service's shell
  (`railway ssh`) and restart the service: it deletes the vector files and originals first,
  then the sources' records — users, website settings and statistics are kept.

Railway's Volume is 0.5 GB on the free/trial plan and 5 GB on Hobby. A Volume created on the
free plan keeps its size after an upgrade: open it and use **Live Resize**.

### Background processing

An upload is streamed to disk and answered immediately; the file is then indexed in the
background, one file at a time, and the file list shows its progress ("reading pages 45/300",
"embeddings 640/1213"). You can close the page meanwhile. Scanned books take longer (see OCR
above).

Files are indexed in windows of 1,000 items — embed, store, next — so memory stays flat
whatever the file's size, and embedding requests are sent 8 at a time. Measured on Sunan Ibn
Majah (4,332 hadiths, 8,274 vectors): 232 s and +539 MB before, about 100 s and +93 MB now.
A re-upload is written as a new version; the previous one is removed only when the new one
is complete, so if a re-upload fails, the previous version stays searchable. A restart or redeploy interrupts running jobs — those files show a message asking
to upload them again.

Every source goes through: extract → clean (diacritics, tatweel, whitespace) → split into
~400-character passages → embed (OpenRouter API) → store in ChromaDB. Page numbers and other
extraction leftovers are dropped; short hadiths such as "الدين النصيحة" are kept. The original
file is kept so it can be downloaded again. Re-uploading a file with the same name replaces it.

### Embeddings

Passages and queries are converted to vectors by `EMBEDDING_MODEL` on OpenRouter — nothing
runs locally, so the service uses ~150 MB of memory. `qwen/qwen3-embedding-4b` was chosen
after comparing 17 embedding models on OpenRouter with hadiths from Bukhari, Muslim, Tirmidhi
and Ibn Majah, asked in a visitor's own words: it found every one of them first, with the
widest gap to the closest wrong passage. Running the same open model on the server would give
the same vectors, only much slower on a CPU. Cost: $0.02 per million tokens (about $0.25 for
the eight Shamela editions; a search costs ~$0.0000004). Uploaded texts and search queries are sent to
OpenRouter to be embedded.

**Dimensions.** Every vector has `EMBEDDING_DIMENSIONS` numbers: 1024, asked of
`qwen3-embedding-4b` (which can give up to 2560). On hadith search 1024 matched 2560 — the right
hadith first for 80/80 exact and 79/80 altered quotes — with 2.5× less memory and storage.
Vectors come back as base64 float32 (a quarter of the size of JSON numbers). The API is asked
for exactly that size, every returned vector is checked, and the vector database records both the model and the size it was built with — so
indexed passages and search queries always match, and anything else is refused with a clear
message (the dashboard status shows the dimensions and whether they match the database).
Passages sent for embedding are ~400 characters, far below the model's input limit;
anything longer than `EMBEDDING_MAX_INPUT_CHARS` is cut for embedding only (the stored text stays
whole).

The chat model on the main website doesn't read vectors: it receives the **text** of the passages
the search found (a few thousand tokens for `top_k` = 5–20, well inside its context window).

Changing `EMBEDDING_MODEL` or `EMBEDDING_DIMENSIONS` later requires deleting and re-uploading
all sources — the dashboard status flags a mismatch. Once every source is deleted, the empty
vector database is recreated for the new model on the next upload.

## API for the main website

Base URL: `https://<database-service>/api/v1`. Every request carries `X-API-Key: <SITE_API_KEY>`.
Call it from the website's **server** — never from browser JavaScript, or the key leaks.

| Endpoint             | Method | Body / response                                                                  |
| -------------------- | ------ | -------------------------------------------------------------------------------- |
| `/site-config`       | GET    | `{maintenance_mode, maintenance_message, search_enabled, chat_enabled, announcement}` |
| `/search`            | POST   | `{"query": "...", "top_k": 5}` → closest passages with similarity, word overlap, ruling, sanad, isnad tree, source |
| `/topics`            | GET    | Topics of the structured hadiths with counts                                     |
| `/events`            | POST   | `{"type": "visit" \| "search" \| "chat", "visitor_id", "query", "result", "latency_ms"}` |

`visitor_id` is any stable anonymous id (e.g. a random cookie value). It is hashed before
storage; never send an IP address or a name. Events feed the dashboard statistics and reports.

### Isnad tree

Each structured hadith in a search result carries `sanad_tree`: its chain as a tree, from the
Prophet ﷺ (or, for a saying of a companion or a later narrator, the earliest narrator named) down
to the book's compiler — `{"name", "grade", "children": [...]}`. When the hadith was uploaded
with a `sanad`, the tree is that sanad. Otherwise it is read from the narration's own wording
(`app/services/isnad_tree.py`) and `sanad_extracted` is `true`:

- The chain is the part before the Prophet ﷺ is named; narrators sit between the words of
  transmission (حدثنا، أخبرنا، عن، سمعت …) and are told from the story by the shape of a name
  (كنية، «بن»، نسبة، «مولى»).
- «ح» starts another chain of the same hadith; it joins the main one at the narrator they share,
  so the tree branches there (Jami' at-Tirmidhi #1 branches at «سماك»).
- «يعني ابن محمد» is kept beside the name it clarifies; «عن أبيه» becomes «والد …» the narrator
  before it; narrators who heard it together («قتيبة وأحمد بن عبدة») share one node.

It is read automatically, not taken from an isnad database: the website says so under the tree.
Checked on all eight Shamela editions (`docs/DATA_SOURCES.md`): 62,919 of the 63,815 hadiths get
a tree, none with a «ح» or a stray number read as a narrator; the rest are sayings and opinions
without a chain (Malik's «قال مالك», al-Tirmidhi's «وفي الباب») and parts of a narration the
edition numbers apart.

**Similarity scale** (measured on 21,000 hadiths of Muslim, Tirmidhi and Ibn Majah): a quote
found word for word = 1.0 (literal index) · two words missing or one word changed ≈ 0.58–0.85 ·
the first five words only ≈ 0.53–0.79 · text not in the sources (modern sentences, proverbs,
sayings wrongly attributed) ≈ 0.42–0.61. The website's "verified / reworded / no match"
thresholds (0.90 / 0.60) are set on this scale.

```bash
curl -X POST https://<database-service>/api/v1/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SITE_API_KEY" \
  -d '{"query": "إنما الأعمال بالنيات", "top_k": 5}'
```

## Security

- No public content: every page and dashboard endpoint requires a signed-in user; `/health`
  returns only `{"status": "ok"}`.
- Passwords are hashed with scrypt and a per-password salt. Sessions are stored server-side
  (SHA-256 of the token only), so logging out or deleting a user takes effect immediately.
- The session cookie is `HttpOnly`, `SameSite=Strict` and `Secure` over HTTPS.
- Login attempts are limited to 10 per 15 minutes per IP.
- The website API only accepts `SITE_API_KEY` (constant-time comparison); a user session
  does not open it, and the key does not open the dashboard.
- Every response is `noindex`, `no-store`, cannot be framed, and sends no referrer;
  `robots.txt` disallows everything; the interactive API docs are off by default.
- A Content-Security-Policy lets the dashboard run only its own scripts and styles (no inline
  code, nothing from other sites), and HSTS keeps browsers on HTTPS.
- Database queries are fixed statements with bound parameters; uploaded file names are reduced
  to a bare name, so an upload can't be written outside the uploads folder.
- Dependencies are pinned and checked for known vulnerabilities in CI. The three chromadb
  advisories (PYSEC-2026-3813/3814/3815) concern Chroma's own HTTP server — tenants, RBAC and
  loading remote model code; this service embeds Chroma in-process and exposes no Chroma
  server, so they don't apply and are ignored in the scan.
- The default password `123456` is public (it's in this README). Until it is changed, the
  account can sign in and change its password, nothing else: every other admin endpoint
  answers 403. Change it right after the first deploy, or set `ADMIN_PASSWORD` in Railway
  before the first deploy.
- Sign-in is limited per client IP and per account (`LOGIN_ATTEMPTS_PER_ACCOUNT_PER_15_MINUTES`):
  the IP comes from `X-Forwarded-For`, to which a client can add made-up addresses before
  Railway's proxy appends the real one, so the per-IP limit alone can be dodged.
- The reports hold what visitors typed. In Excel it stays text (a search starting with `=` is
  not a formula); in the PDF it is escaped, so it can't load images or break the report.

## Deploying to Railway

Railway builds the `Dockerfile` (Python, Tesseract with Arabic as the OCR fallback, and an
Arabic font for PDF reports). There is no local model, so the image is small and the build takes a few minutes.

1. **Plan:** the service uses ~150 MB of memory at rest (more briefly while reading large or
   scanned files), so a small instance is enough.
2. **New project:** railway.com → **New Project** → **Deploy from GitHub repo** →
   `Salman-Naif/Isnad_Database` (allow Railway to access the repository if asked).
3. **Volume — before anything else is saved:** open the service → right-click / **⋯** →
   **Attach Volume** → mount path **`/app/chroma_db`**. It holds the vector database, users,
   stats, settings and uploaded originals. Without it, everything is wiped on every deploy.
   The free plan's 0.5 GB can't hold the eight editions (~0.9 GB); on Hobby, grow it with **Live Resize**
   (see "Disk space").
4. **Variables** (service → **Variables**):

   | Variable             | Value                                                   |
   | -------------------- | ------------------------------------------------------- |
   | `SITE_API_KEY`       | a long random key — give the same value to the main website |
   | `OPENROUTER_API_KEY` | your OpenRouter key                                     |
   | `PORT`               | `8000`                                                  |

   Generate `SITE_API_KEY` with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
   `PORT` is pinned so it matches the port you give the domain in the next step.
5. **Public URL:** service → **Settings** → **Networking** → **Generate Domain**, target port
   **`8000`**. This is the database's own link, e.g. `https://<database-service>.up.railway.app`.
6. **Deploy** and wait until the deployment is **Active** (the healthcheck on `/health` passes).
7. Open the URL, sign in as `salman` / `123456`, and **change the password immediately**.
8. Upload your approved sources from the **المصادر** tab.

Every push to `main` redeploys automatically; the Volume keeps all data between deploys.
Keep the service at **one replica** — the app database is SQLite on the Volume.

## Environment variables

| Variable                        | Required     | Default                                                       |
| ------------------------------- | ------------ | ------------------------------------------------------------- |
| `SITE_API_KEY`                  | Yes          | —                                                             |
| `OPENROUTER_API_KEY`            | Yes          | — (embeddings and OCR here + chat model on the main website)  |
| `OPENROUTER_BASE_URL`           | No           | `https://openrouter.ai/api/v1`                                |
| `ADMIN_USERNAME`                | No           | `salman` (default user, first start only)                     |
| `ADMIN_PASSWORD`                | No           | `123456` (must be changed after signing in)                   |
| `SESSION_HOURS`                 | No           | `12`                                                          |
| `LOGIN_ATTEMPTS_PER_15_MINUTES` | No           | `10`                                                          |
| `LOGIN_ATTEMPTS_PER_ACCOUNT_PER_15_MINUTES` | No | `20`                                                          |
| `ENABLE_API_DOCS`               | No           | `false`                                                       |
| `CHROMA_DIR`                    | No           | `./chroma_db`                                                 |
| `SQLITE_PATH`                   | No           | `./chroma_db/isnad.db`                                        |
| `UPLOADS_DIR`                   | No           | `./chroma_db/uploads`                                         |
| `COLLECTION_NAME`               | No           | `isnad_hadiths`                                               |
| `EMBEDDING_MODEL`               | No           | `qwen/qwen3-embedding-4b`                                     |
| `EMBEDDING_DIMENSIONS`          | No           | `1024` (must match the model's vectors)                       |
| `EMBEDDING_MAX_INPUT_CHARS`     | No           | `6000`                                                        |
| `EMBEDDING_QUERY_INSTRUCTION`   | No           | *(Qwen3's search instruction; `-` = none)*                    |
| `EMBEDDING_BATCH_SIZE`          | No           | `64`                                                          |
| `EMBEDDING_CONCURRENCY`         | No           | `8` (requests at the same time)                               |
| `EMBEDDING_TIMEOUT_SECONDS`     | No           | `60`                                                          |
| `CHUNK_MAX_CHARS`               | No           | `400`                                                         |
| `CHUNK_OVERLAP_CHARS`           | No           | `60`                                                          |
| `CHUNK_MIN_LETTERS`             | No           | `8`                                                           |
| `MAX_UPLOAD_MB`                 | No           | `100`                                                         |
| `OCR_ENGINE`                    | No           | `vision` (or `tesseract`)                                     |
| `OCR_MODEL`                     | No           | `google/gemini-3-flash-preview`                               |
| `OCR_CHECK_MODEL`               | No           | `google/gemini-3.1-flash-lite` (empty = no cross-check)       |
| `OCR_REFEREE_MODEL`             | No           | `google/gemini-3.8-flash`                                     |
| `OCR_CONCURRENCY`               | No           | `12` (pages read at the same time)                            |
| `OCR_TIMEOUT_SECONDS`           | No           | `180`                                                         |
| `OCR_DPI`                       | No           | `300`                                                         |
| `TESSERACT_CMD`                 | No           | *(tesseract on PATH)*                                         |
| `OCR_LANGUAGES`                 | No           | `ara`                                                         |
| `REPORT_FONT_PATH`              | No           | *(auto-detected Arabic font)*                                 |
| `REPORT_UTC_OFFSET_HOURS`       | No           | `3` (Saudi time)                                              |
| `LOG_LEVEL`                     | No           | `INFO`                                                        |
