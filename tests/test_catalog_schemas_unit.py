"""Hermetic unit tests for Pydantic catalog schemas — no DB needed."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.catalog import (
    CourseCreate,
    ExamCreate,
    ProductVersionCreate,
    ProviderCreate,
    ProviderUpdate,
    TopicCreate,
)
from app.utils.slug import is_valid_slug, make_slug


def test_provider_blank_slug_derived_from_name() -> None:
    p = ProviderCreate(name="Fortinet")
    assert p.slug == "fortinet"


def test_provider_explicit_slug_overrides_auto() -> None:
    p = ProviderCreate(name="Fortinet Inc.", slug="ftnt")
    assert p.slug == "ftnt"


def test_provider_slug_is_lowercased_when_blank() -> None:
    p = ProviderCreate(name="Cisco Systems")
    assert p.slug == "cisco-systems"


@pytest.mark.parametrize(
    "bad",
    [
        "Foo-Bar",  # uppercase
        "-leading",  # leading hyphen
        "trailing-",  # trailing hyphen
        "with spaces",
        "with_underscore",
        "",
    ],
)
def test_invalid_slug_format_rejected_on_update(bad: str) -> None:
    with pytest.raises(ValidationError):
        ProviderUpdate(slug=bad)


def test_course_slug_auto_from_name_under_max_length() -> None:
    c = CourseCreate(provider_id=1, name="NSE 4 Network Security Professional")
    assert c.slug == "nse-4-network-security-professional"
    assert is_valid_slug(c.slug)


def test_exam_dates_validate_order() -> None:
    from datetime import date

    with pytest.raises(ValidationError):
        ExamCreate(
            course_id=1,
            name="Foo",
            valid_from=date(2026, 6, 1),
            valid_until=date(2026, 1, 1),
        )


def test_exam_passing_score_within_range() -> None:
    e = ExamCreate(course_id=1, name="X", passing_score_percent=Decimal("70.50"))
    assert e.passing_score_percent == Decimal("70.50")


def test_topic_optional_weight_and_slug_autoderive() -> None:
    t = TopicCreate(exam_id=1, name="VPN")
    assert t.slug == "vpn"
    assert t.weight is None


def test_product_version_provider_required() -> None:
    pv = ProductVersionCreate(provider_id=1, product_name="FortiGate", product_version="7.4.3")
    assert pv.provider_id == 1


def test_make_slug_strips_unsafe_chars() -> None:
    assert make_slug("Hello, World!") == "hello-world"
    assert make_slug("$$") == "n-a"
