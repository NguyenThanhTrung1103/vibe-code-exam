"""Admin CRUD for providers."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy import select

from app.auth.permissions import RequireAdmin
from app.deps import SessionDep
from app.middleware import REQUEST_ID_HEADER
from app.models.catalog import Provider
from app.routers.admin._common import (
    flash_error,
    render_with_csrf,
    require_csrf,
    templates,
)
from app.schemas.catalog import ProviderCreate, ProviderUpdate
from app.services import catalog_service

router = APIRouter(prefix="/admin/providers", tags=["admin", "catalog"])


@router.get("", response_class=HTMLResponse)
def list_providers(request: Request, user: RequireAdmin, session: SessionDep) -> HTMLResponse:
    rows = session.scalars(select(Provider).order_by(Provider.name)).all()
    return render_with_csrf(
        request,
        "admin/catalog/providers/list.html",
        {"rows": rows, "current_user": user},
    )


@router.post("", response_class=HTMLResponse)
def create_provider(
    request: Request,
    user: RequireAdmin,
    session: SessionDep,
    name: str = Form(...),
    slug: str = Form(""),
    description: str = Form(""),
    logo_url: str = Form(""),
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        payload = ProviderCreate.model_validate(
            {
                "name": name,
                "slug": slug or None,
                "description": description or None,
                "logo_url": logo_url or None,
            }
        )
    except ValidationError as exc:
        return flash_error(request, str(exc.errors()[0]["msg"]))
    assert payload.slug is not None  # set by _fill_slug validator
    try:
        provider = catalog_service.create_provider(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            name=payload.name,
            slug=payload.slug,
            description=payload.description,
            logo_url=str(payload.logo_url) if payload.logo_url else None,
        )
    except catalog_service.DuplicateSlugError as exc:
        return flash_error(request, str(exc))
    session.commit()
    return templates.TemplateResponse(
        request, "admin/catalog/providers/_row.html", {"row": provider}
    )


@router.post("/{provider_id}/edit", response_class=HTMLResponse)
def update_provider(
    request: Request,
    provider_id: int,
    user: RequireAdmin,
    session: SessionDep,
    name: str = Form(...),
    slug: str = Form(...),
    description: str = Form(""),
    logo_url: str = Form(""),
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        payload = ProviderUpdate.model_validate(
            {
                "name": name,
                "slug": slug,
                "description": description or None,
                "logo_url": logo_url or None,
            }
        )
    except ValidationError as exc:
        return flash_error(request, str(exc.errors()[0]["msg"]))
    try:
        provider = catalog_service.update_provider(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            provider_id=provider_id,
            **payload.model_dump(exclude_unset=True, exclude_none=True),
        )
    except catalog_service.DuplicateSlugError as exc:
        return flash_error(request, str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session.commit()
    return templates.TemplateResponse(
        request, "admin/catalog/providers/_row.html", {"row": provider}
    )


@router.post("/{provider_id}/delete", response_class=HTMLResponse)
def soft_delete_provider(
    request: Request,
    provider_id: int,
    user: RequireAdmin,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        catalog_service.soft_delete_provider(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            provider_id=provider_id,
        )
    except ValueError as exc:
        return flash_error(request, str(exc))
    session.commit()
    return HTMLResponse("")
