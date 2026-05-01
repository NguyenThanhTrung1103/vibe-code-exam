"""Phase 08 hermetic unit tests — scoring helpers + recommendation logic."""

from __future__ import annotations

from app.services.scoring_service import (
    TopicBreakdown,
    _parse_selected_set,
    weak_topic_recommendations,
)


def test_parse_selected_set_handles_none() -> None:
    assert _parse_selected_set(None) == set()
    assert _parse_selected_set("") == set()


def test_parse_selected_set_uppercases_and_dedupes() -> None:
    assert _parse_selected_set("a,c,a") == {"A", "C"}


def test_parse_selected_set_strips_whitespace() -> None:
    assert _parse_selected_set(" b , c ") == {"B", "C"}


def test_recommendation_filters_low_question_count() -> None:
    breakdown = [
        TopicBreakdown(topic_id=1, topic_name="VPN", weight=None, total=2, correct=0),
    ]
    # Only 2 questions in topic — does not qualify.
    assert weak_topic_recommendations(breakdown, overall_percent=80.0) == []


def test_recommendation_filters_small_gap() -> None:
    breakdown = [
        TopicBreakdown(topic_id=1, topic_name="VPN", weight=None, total=10, correct=8),
    ]
    # 80%; overall 85% → 5 pp gap → not recommended (need ≥10).
    assert weak_topic_recommendations(breakdown, overall_percent=85.0) == []


def test_recommendation_caps_at_two() -> None:
    breakdown = [
        TopicBreakdown(topic_id=1, topic_name="A", weight=None, total=10, correct=2),  # 20%
        TopicBreakdown(topic_id=2, topic_name="B", weight=None, total=10, correct=4),  # 40%
        TopicBreakdown(topic_id=3, topic_name="C", weight=None, total=10, correct=5),  # 50%
        TopicBreakdown(topic_id=4, topic_name="D", weight=None, total=10, correct=6),  # 60%
    ]
    recs = weak_topic_recommendations(breakdown, overall_percent=80.0)
    assert len(recs) == 2
    assert recs[0].topic_name == "A"  # widest gap first
    assert recs[1].topic_name == "B"


def test_topic_breakdown_percent() -> None:
    b = TopicBreakdown(topic_id=1, topic_name="x", weight=None, total=10, correct=7)
    assert b.percent == 70.0
    z = TopicBreakdown(topic_id=2, topic_name="empty", weight=None, total=0, correct=0)
    assert z.percent == 0.0
