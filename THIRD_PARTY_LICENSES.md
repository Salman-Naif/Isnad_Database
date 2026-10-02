# Third-party components, services, models and data

The Isnad team's own code and documentation are under the MIT License (`LICENSE`). Everything
below belongs to its authors and keeps its own license or terms. Nothing listed here is copied
into this repository except where said; Python packages are installed from PyPI at build time.

Versions are the ones pinned in `requirements.txt` / `requirements-dev.txt`; licenses are read
from each package's metadata (checked 2026-10-02).

## Python packages (runtime)

| Package | Version | License | Used for |
| --- | --- | --- | --- |
| [FastAPI](https://github.com/fastapi/fastapi) | 0.141.1 | MIT | Web framework (dashboard, admin API, website API) |
| [Uvicorn](https://uvicorn.dev/) | 0.54.0 | BSD-3-Clause | ASGI server |
| [Jinja2](https://github.com/pallets/jinja/) | 3.1.6 | BSD-3-Clause | HTML templates |
| [python-multipart](https://github.com/Kludex/python-multipart) | 0.0.32 | Apache-2.0 | File uploads |
| [Pydantic](https://github.com/pydantic/pydantic) | 2.13.5 | MIT | Data validation |
| [pydantic-settings](https://github.com/pydantic/pydantic-settings) | 2.15.0 | MIT | Settings from environment variables |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | 1.2.3 | BSD-3-Clause | Local `.env` files |
| [ChromaDB](https://github.com/chroma-core/chroma) | 0.6.3 | Apache-2.0 | Vector database (embedded) |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) (PDFium) | 4.30.0 | Apache-2.0 OR BSD-3-Clause; PDFium BSD-3-Clause | Reading PDFs |
| [python-docx](https://github.com/python-openxml/python-docx) | 1.1.2 | MIT | Reading Word files |
| [Pillow](https://python-pillow.github.io) | 12.3.0 | MIT-CMU (HPND) | Images for OCR |
| [pytesseract](https://github.com/madmaze/pytesseract) | 0.3.13 | Apache-2.0 | Fallback OCR |
| [openpyxl](https://openpyxl.readthedocs.io) | 3.1.5 | MIT | Excel reports |
| [ReportLab](https://www.reportlab.com/) | 4.2.5 | BSD-3-Clause | PDF reports |
| [arabic-reshaper](https://github.com/mpcabd/python-arabic-reshaper/) | 3.0.0 | MIT | Arabic letters in PDF reports |
| [python-bidi](https://github.com/MeirKriheli/python-bidi) | 0.6.3 | LGPL-3.0 | Right-to-left text in PDF reports (used unmodified, as an installed library) |
| [HTTPX](https://github.com/encode/httpx) | 0.28.1 | BSD-3-Clause | Calls to OpenRouter |
| [NumPy](https://numpy.org) | 2.4.6 | BSD-3-Clause | Vectors |

## Development and testing tools (not in the image)

| Package | License |
| --- | --- |
| pytest 9.1.1, pytest-cov 7.1.0, Ruff 0.16.9 | MIT |
| Bandit 1.9.4, pip-audit 2.10.1 | Apache-2.0 |
| [Newman](https://github.com/postmanlabs/newman) 6 (run through `npx` by the system tests) | Apache-2.0 |

## In the Docker image

| Component | License | Used for |
| --- | --- | --- |
| Python 3.11.9 (`python:3.11.9-slim`, Debian) | PSF License; Debian packages under their own licenses | Runtime |
| [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) (Debian package) | Apache-2.0 | Fallback OCR when the vision model can't be reached |
| [tessdata_best `ara.traineddata`](https://github.com/tesseract-ocr/tessdata_best) (downloaded at build) | Apache-2.0 | Arabic OCR model |
| [Noto fonts](https://github.com/notofonts) (`fonts-noto-core`, Noto Naskh Arabic) | SIL Open Font License 1.1 | Arabic in PDF reports |

## Services and AI models (called through APIs, never redistributed)

| Service / model | Terms | Used for |
| --- | --- | --- |
| [OpenRouter](https://openrouter.ai) | [OpenRouter Terms](https://openrouter.ai/terms) and each provider's terms | Gateway to the models below |
| [`qwen/qwen3-embedding-4b`](https://huggingface.co/Qwen/Qwen3-Embedding-4B) (Alibaba Qwen) | Apache-2.0 model; served under the provider's terms | Embeddings of texts and queries |
| `google/gemini-3-flash-preview`, `google/gemini-3.1-flash-lite` (Google) | Google's API terms (proprietary models) | Reading scanned pages (OCR) and cross-checking them |
| [Railway](https://railway.com) | Railway's terms | Hosting and the storage Volume |

Uploaded texts, scanned pages and search queries are sent to OpenRouter to be processed.

## Data

The hadith collections are not part of this repository; the team uploads them to the running
service. Their origin, licenses and how they are used are in
[`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md). In short: the texts of the hadiths are classical
works in the public domain; the two datasets that digitised them (Hadith-Data-Sets, hadith-json)
publish **no license**, so the files are not redistributed here, they are credited wherever used,
and only short excerpts of classical text appear in the tests.

## Icons

The dashboard's icons are drawn inline in `app/templates/base.html` after the paths of
[Feather Icons](https://github.com/feathericons/feather) (MIT, © Cole Bemis).
