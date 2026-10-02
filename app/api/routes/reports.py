"""Statistics and report exports (Excel / PDF) — admins only."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import require_admin
from app.models.schemas import ReportSummary
from app.services import reports, sources

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(require_admin)])

EXPORT_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


def _summary(date_from: date | None, date_to: date | None) -> ReportSummary:
    default_from, default_to = reports.default_range()
    try:
        return reports.build_summary(date_from or default_from, date_to or default_to)
    except reports.ReportError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/summary", response_model=ReportSummary)
def summary(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> ReportSummary:
    """Statistics for a date range (default: the last 30 days)."""
    return _summary(date_from, date_to)


@router.get("/export")
def export(
    format: Literal["xlsx", "pdf"],
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> Response:
    report = _summary(date_from, date_to)
    files = sources.list_sources(ready_only=True)
    try:
        content = reports.to_excel(report, files) if format == "xlsx" else reports.to_pdf(report, files)
    except reports.ReportError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    filename = f"isnad-report-{report.date_from}-to-{report.date_to}.{format}"
    return Response(
        content,
        media_type=EXPORT_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
