"""
API for the main Isnad website (/api/v1). Server-to-server only.

The website authenticates with SITE_API_KEY in the X-API-Key header. The key must
stay on the website's server — never put it in browser JavaScript.

  GET  /api/v1/site-config        controls set from the dashboard (maintenance, features...)
  POST /api/v1/search             closest stored texts to a query, with ruling, sanad and isnad tree
  GET  /api/v1/topics             topics of the structured hadiths
  POST /api/v1/events             report a visit, a search or a chat question (for statistics)
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import get_embedder, get_vector_store, require_site_key
from app.models.schemas import (
    EventIn,
    SanadNode,
    SiteMatch,
    SiteSearchRequest,
    SiteSearchResponse,
    SiteSettings,
)
from app.services import books, chapter_titles, isnad_tree, sanad, text_index
from app.services.embeddings import EmbeddingError, EmbeddingService
from app.services.events import record_event
from app.services.site_settings import get_site_settings
from app.services.text_processing import clean
from app.services.vector_store import VectorStore, VectorStoreError

# A subject («فضل الأم»): this many closest texts are reordered by the share of its words in the
# hadith's own words, worth up to SUBJECT_WEIGHT of similarity (text_index.subject_overlap). The
# similarity shown is not changed.
SUBJECT_POOL = 60
SUBJECT_WEIGHT = 0.15
# A search by title: more texts, ranked by how close their chapter's title is to it
# (chapter_titles), and every one holding the title's words before any that doesn't.
TITLE_POOL = 100
TITLE_WEIGHT = 1.0
CHAPTER_WEIGHT = 0.8

router = APIRouter(prefix="/v1", tags=["site api"], dependencies=[Depends(require_site_key)])


@router.get("/site-config", response_model=SiteSettings)
def site_config() -> SiteSettings:
    return get_site_settings()


@router.post("/search", response_model=SiteSearchResponse)
def search(
    payload: SiteSearchRequest,
    embedder: EmbeddingService = Depends(get_embedder),
    store: VectorStore = Depends(get_vector_store),
) -> SiteSearchResponse:
    # Cleaned exactly like the indexed texts, so the vectors are comparable.
    query = clean(payload.query)
    if not query:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Empty query")

    try:
        # Word-for-word quotes first (similarity 1.0), then the closest meanings. A hadith can
        # come back through both, or through both of its vectors (narration, matn): once only.
        exact = [{**hit, "similarity": 1.0} for hit in store.get(text_index.find_quote(payload.query))]
        # A quote found word for word in several books: listed in the books' order (al-Bukhari,
        # Muslim, then the Sunan…), not in the order the files were uploaded.
        exact.sort(key=lambda hit: books.rank(hit["metadata"].get("reference") or hit["metadata"].get("source") or ""))
        # Extra candidates, since a hadith's two vectors often both rank near the top; more for a
        # subject («فضل الأم»), whose closest texts are reordered below.
        subject = payload.by_title or text_index.is_subject(payload.query)
        pool = payload.top_k * 3
        if subject:
            pool = max(pool, TITLE_POOL if payload.by_title else SUBJECT_POOL)
        close = store.query(embedder.encode_query(query), top_k=pool)
    except (EmbeddingError, VectorStoreError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    # Texts are stored once, beside the literal index; the vector store holds vectors only.
    stored = text_index.texts([hit["id"] for hit in exact + close])
    for hit in exact + close:
        hit["text"] = stored.get(hit["id"]) or hit["text"]
    if subject:
        weight = TITLE_WEIGHT if payload.by_title else SUBJECT_WEIGHT

        def share(hit: dict) -> float:
            found = text_index.subject_overlap(payload.query, hit["text"])
            if payload.by_title:  # the book's chapter («كتاب الصوم») names it too
                found = max(found, text_index.subject_overlap(payload.query, hit["metadata"].get("topic") or "",
                                                              whole=True))
            return found

        chapters: dict[str, float] = {}
        if payload.by_title:
            try:
                chapters = chapter_titles.closeness(
                    embedder, payload.query, [hit["metadata"].get("topic") or "" for hit in close])
            except EmbeddingError:
                chapters = {}  # the texts keep their order by meaning and words

        def score(hit: dict) -> float:
            chapter = chapters.get(hit["metadata"].get("topic") or "", 0.0)
            return hit["similarity"] + weight * share(hit) + CHAPTER_WEIGHT * chapter

        # A stable sort: texts with as many of the subject's words keep their order by meaning.
        close.sort(key=lambda hit: -score(hit))

    matches: list[SiteMatch] = []
    seen: set[str] = set()
    for hit in exact + close:
        key = _text_key(hit)
        # A vector whose text isn't stored (a write cut off by a restart) has nothing to show.
        if key in seen or not (hit["text"] or "").strip():
            continue
        seen.add(key)
        matches.append(_site_match(hit, payload.query))
        if len(matches) == payload.top_k:
            break
    return SiteSearchResponse(matches=matches)


def _text_key(hit: dict) -> str:
    """The same stored text, whichever of its vectors matched."""
    meta = hit["metadata"]
    if meta.get("type") == "structured_hadith":
        return f"{meta.get('source')}#{meta.get('record_id')}"
    return hit["id"]


def _site_match(hit: dict, query: str) -> SiteMatch:
    meta = hit["metadata"]
    narrators = sanad.parse(meta.get("sanad", ""))
    tree, extracted = None, False
    source = meta.get("reference") or meta.get("source") or None
    book = None
    if meta.get("type") == "structured_hadith":  # a page of a book is not one narration
        tree, extracted = isnad_tree.tree_for(hit["text"], narrators, meta.get("reference") or "")
        # Its published title, whatever name it was uploaded under (texts indexed earlier too).
        book = books.find(source or "")
        source = book.title if book else source
    return SiteMatch(
        id=hit["id"],
        text=hit["text"],
        similarity=round(min(1.0, max(0.0, hit["similarity"])), 4),
        word_overlap=text_index.word_overlap(query, hit["text"]),
        kind=meta.get("type", "document"),
        hukm=meta.get("hukm") or None,
        mohaddith=meta.get("mohaddith") or None,
        sanad=narrators,
        sanad_tree=SanadNode.model_validate(tree.as_dict()) if tree else None,
        sanad_extracted=extracted,
        topic=meta.get("topic") or None,
        source=source,
        compiler=book.credit if book else None,
    )


@router.get("/topics")
def topics(store: VectorStore = Depends(get_vector_store)) -> list[dict]:
    return store.list_topics()


@router.post("/events", status_code=status.HTTP_204_NO_CONTENT)
def events(event: EventIn) -> Response:
    record_event(event)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
