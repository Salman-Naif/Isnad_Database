"""Admin account management — admins only."""

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import require_admin, require_owner
from app.models.schemas import AdminCreate, AdminInfo
from app.services import auth

router = APIRouter(prefix="/admins", tags=["admins"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[AdminInfo])
def list_admins() -> list[AdminInfo]:
    owner = auth.owner_id()
    return [AdminInfo(**a.__dict__, is_owner=a.id == owner) for a in auth.list_admins()]


@router.post("", response_model=AdminInfo, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_owner)])
def create_admin(payload: AdminCreate) -> AdminInfo:
    try:
        admin = auth.create_admin(payload.username, payload.password)
    except auth.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return AdminInfo(id=admin.id, username=admin.username)


@router.delete("/{admin_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_admin(admin_id: int, current: auth.Admin = Depends(require_owner)) -> Response:
    if admin_id == current.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="لا يمكنك حذف حسابك الحالي"
        )
    try:
        deleted = auth.delete_admin(admin_id)
    except auth.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المشرف غير موجود")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
