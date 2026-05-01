"""Admin CRUD for product_versions.

Per Phase 04 plan: product_versions table is wired now (Phase 2 AI verifier
will use `documentation_base_url`). Admin CRUD only — no public surface.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy import select

from app.auth.permissions import RequireAdmin
from app.deps import SessionDep
from app.middleware import REQUEST_ID_HEADER
from app.models.catalog import ProductVersion, Provider
from app.routers.admin._common import flash_error, render_with_csrf, require_csrf, templates
from app.schemas.catalog import ProductVersionCreate, ProductVersionUpdate
from app.services import catalog_service

router = APIRouter(prefix="/admin/product-versions", tags=["admin", "catalog"])


@router.get("", response_class=HTMLResponse)
def list_product_versions(
    request: Request, user: RequireAdmin, session: SessionDep
) -> HTMLResponse:
    rows = session.execute(
        select(ProductVersion, Provider)
        .join(Provider, ProductVersion.provider_id == Provider.id)
        .order_by(Provider.name, ProductVersion.product_name, ProductVersion.product_version)
    ).all()
    providers = session.scalars(select(Provider).order_by(Provider.name)).all()
    return render_with_csrf(
        request,
        "admin/catalog/product_versions/list.html",
        {"rows": rows, "providers": providers, "current_user": user},
    )


@router.post("", response_class=HTMLResponse)
def create_product_version(
    request: Request,
    user: RequireAdmin,
    session: SessionDep,
    provider_id: int = Form(...),
    product_name: str = Form(...),
    product_version: str = Form(...),
    documentation_base_url: str = Form(""),
    release_date: str = Form(""),
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        payload = ProductVersionCreate.model_validate(
            {
                "provider_id": provider_id,
                "product_name": product_name,
                "product_version": product_version,
                "documentation_base_url": documentation_base_url or None,
                "release_date": date.fromisoformat(release_date) if release_date else None,
            }
        )
    except (ValidationError, ValueError) as exc:
        return flash_error(request, _first_message(exc))
    try:
        pv = catalog_service.create_product_version(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            provider_id=payload.provider_id,
            product_name=payload.product_name,
            product_version=payload.product_version,
            documentation_base_url=(
                str(payload.documentation_base_url) if payload.documentation_base_url else None
            ),
            release_date=payload.release_date,
        )
    except catalog_service.DuplicateSlugError as exc:
        return flash_error(request, str(exc))
    session.commit()
    provider = session.get(Provider, pv.provider_id)
    return templates.TemplateResponse(
        request,
        "admin/catalog/product_versions/_row.html",
        {"row": (pv, provider)},
    )


@router.post("/{product_version_id}/edit", response_class=HTMLResponse)
def update_product_version(
    request: Request,
    product_version_id: int,
    user: RequireAdmin,
    session: SessionDep,
    product_name: str = Form(...),
    product_version: str = Form(...),
    documentation_base_url: str = Form(""),
    release_date: str = Form(""),
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        payload = ProductVersionUpdate.model_validate(
            {
                "product_name": product_name,
                "product_version": product_version,
                "documentation_base_url": documentation_base_url or None,
                "release_date": date.fromisoformat(release_date) if release_date else None,
            }
        )
    except (ValidationError, ValueError) as exc:
        return flash_error(request, _first_message(exc))
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "documentation_base_url" in changes and changes["documentation_base_url"] is not None:
        changes["documentation_base_url"] = str(changes["documentation_base_url"])
    try:
        pv = catalog_service.update_product_version(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            product_version_id=product_version_id,
            **changes,
        )
    except catalog_service.DuplicateSlugError as exc:
        return flash_error(request, str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session.commit()
    provider = session.get(Provider, pv.provider_id)
    return templates.TemplateResponse(
        request,
        "admin/catalog/product_versions/_row.html",
        {"row": (pv, provider)},
    )


@router.post("/{product_version_id}/delete", response_class=HTMLResponse)
def soft_delete_product_version(
    request: Request,
    product_version_id: int,
    user: RequireAdmin,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        catalog_service.soft_delete_product_version(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            product_version_id=product_version_id,
        )
    except ValueError as exc:
        return flash_error(request, str(exc))
    session.commit()
    return HTMLResponse("")


def _first_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return str(exc.errors()[0]["msg"])
    return str(exc)
