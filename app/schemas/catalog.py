"""Pydantic input schemas + validators for catalog admin endpoints.

Tight validation here keeps invalid data from reaching SQL. The service
layer trusts the parsed inputs, so any rule we don't encode here must be
enforced again in the service.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.utils.slug import SLUG_REGEX, make_slug

# Reusable field types
NameField = Annotated[str, Field(min_length=1, max_length=255)]
ShortNameField = Annotated[str, Field(min_length=1, max_length=128)]
SlugField = Annotated[str, Field(min_length=1, max_length=64, pattern=SLUG_REGEX.pattern)]
OptionalSlugField = Annotated[str | None, Field(default=None, max_length=64)]
DescriptionField = Annotated[str | None, Field(default=None, max_length=4000)]
LogoUrlField = Annotated[HttpUrl | None, Field(default=None)]


CourseLevel = Literal["beginner", "associate", "professional", "expert"]


def _resolve_slug(slug: str | None, *, fallback: str) -> str:
    """If admin left slug blank, derive it from `fallback` (e.g. the name)."""
    if slug:
        return slug.strip().lower()
    return make_slug(fallback)


class ProviderCreate(BaseModel):
    name: NameField
    slug: OptionalSlugField = None
    description: DescriptionField = None
    logo_url: LogoUrlField = None

    @model_validator(mode="after")
    def _fill_slug(self):
        self.slug = _resolve_slug(self.slug, fallback=self.name)
        return self


class ProviderUpdate(BaseModel):
    name: NameField | None = None
    slug: SlugField | None = None
    description: DescriptionField = None
    logo_url: LogoUrlField = None


class ProductVersionCreate(BaseModel):
    provider_id: int = Field(ge=1)
    product_name: ShortNameField
    product_version: Annotated[str, Field(min_length=1, max_length=64)]
    documentation_base_url: Annotated[HttpUrl | None, Field(default=None)] = None
    release_date: date | None = None


class ProductVersionUpdate(BaseModel):
    product_name: ShortNameField | None = None
    product_version: Annotated[str | None, Field(default=None, max_length=64)] = None
    documentation_base_url: Annotated[HttpUrl | None, Field(default=None)] = None
    release_date: date | None = None


class CourseCreate(BaseModel):
    provider_id: int = Field(ge=1)
    name: NameField
    slug: OptionalSlugField = None
    description: DescriptionField = None
    level: CourseLevel | None = None
    status: Annotated[str | None, Field(default=None, max_length=32)] = None

    @model_validator(mode="after")
    def _fill_slug(self):
        self.slug = _resolve_slug(self.slug, fallback=self.name)
        return self


class CourseUpdate(BaseModel):
    name: NameField | None = None
    slug: SlugField | None = None
    description: DescriptionField = None
    level: CourseLevel | None = None
    status: Annotated[str | None, Field(default=None, max_length=32)] = None


class ExamCreate(BaseModel):
    course_id: int = Field(ge=1)
    name: NameField
    slug: OptionalSlugField = None
    code: Annotated[str | None, Field(default=None, max_length=64)] = None
    description: DescriptionField = None
    vendor_exam_code: Annotated[str | None, Field(default=None, max_length=64)] = None
    valid_from: date | None = None
    valid_until: date | None = None
    time_limit_seconds: Annotated[int | None, Field(default=None, ge=60, le=86_400)] = None
    passing_score_percent: Annotated[
        Decimal | None, Field(default=None, ge=0, le=100, decimal_places=2)
    ] = None

    @model_validator(mode="after")
    def _check_dates_and_slug(self):
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must be on/after valid_from")
        self.slug = _resolve_slug(self.slug, fallback=self.name)
        return self


class ExamUpdate(BaseModel):
    name: NameField | None = None
    slug: SlugField | None = None
    code: Annotated[str | None, Field(default=None, max_length=64)] = None
    description: DescriptionField = None
    vendor_exam_code: Annotated[str | None, Field(default=None, max_length=64)] = None
    valid_from: date | None = None
    valid_until: date | None = None
    time_limit_seconds: Annotated[int | None, Field(default=None, ge=60, le=86_400)] = None
    passing_score_percent: Annotated[
        Decimal | None, Field(default=None, ge=0, le=100, decimal_places=2)
    ] = None

    @model_validator(mode="after")
    def _check_dates(self):
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must be on/after valid_from")
        return self


class TopicCreate(BaseModel):
    exam_id: int = Field(ge=1)
    name: NameField
    slug: OptionalSlugField = None
    description: DescriptionField = None
    weight: Annotated[Decimal | None, Field(default=None, ge=0, le=100, decimal_places=2)] = None

    @model_validator(mode="after")
    def _fill_slug(self):
        self.slug = _resolve_slug(self.slug, fallback=self.name)
        return self


class TopicUpdate(BaseModel):
    name: NameField | None = None
    slug: SlugField | None = None
    description: DescriptionField = None
    weight: Annotated[Decimal | None, Field(default=None, ge=0, le=100, decimal_places=2)] = None


__all__ = [
    "CourseCreate",
    "CourseLevel",
    "CourseUpdate",
    "ExamCreate",
    "ExamUpdate",
    "ProductVersionCreate",
    "ProductVersionUpdate",
    "ProviderCreate",
    "ProviderUpdate",
    "TopicCreate",
    "TopicUpdate",
]
