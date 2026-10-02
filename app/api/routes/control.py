"""Main website controls and system status — admins only."""

from fastapi import APIRouter, Depends

from app.api.deps import get_embedder, get_vector_store, require_admin
from app.models.schemas import SiteSettings, SystemStatus
from app.services import status as system_status
from app.services.embeddings import EmbeddingService
from app.services.site_settings import get_site_settings, save_site_settings
from app.services.vector_store import VectorStore

router = APIRouter(tags=["control"], dependencies=[Depends(require_admin)])


@router.get("/site-settings", response_model=SiteSettings)
def read_site_settings() -> SiteSettings:
    return get_site_settings()


@router.put("/site-settings", response_model=SiteSettings)
def update_site_settings(settings: SiteSettings) -> SiteSettings:
    """Takes effect on the main website at its next page load."""
    return save_site_settings(settings)


@router.get("/status", response_model=SystemStatus)
def read_status(
    embedder: EmbeddingService = Depends(get_embedder),
    store: VectorStore = Depends(get_vector_store),
) -> SystemStatus:
    """Check the databases, the model, OCR, the API keys and the main website."""
    return system_status.check_all(embedder, store)
