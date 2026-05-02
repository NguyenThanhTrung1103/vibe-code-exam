"""Phase 13 — import-pipeline community-signal tests.

Hermetic-only this file. Covers:
  * `excel_parser` exposes the new community canonical fields + aliases.
  * `import_validator` accepts rows with no community fields unchanged.
  * `import_validator` builds `canonical['community']` for valid rows.
  * `import_validator` downgrades to warning + drops bad URL.
  * `import_validator` downgrades to warning on bad vote distribution.
  * `import_community.extract_community_payload` returns None when no signal.
  * `import_community.upsert_community_source` short-circuits without URL.
  * `import_community.upsert_community_source` round-trips via a fake
    `Session` capturing add/select calls — CREATE / IDEMPOTENT-NOOP /
    TEXT-CHANGED / RELINK paths.

Real-DB integration (table existence, FK constraints, JSONB serialization)
is deferred to Step D after the migration is applied to an ephemeral DB.
This file does NOT touch any real or shared database.
"""

from __future__ import annotations

from typing import Any

from app.audit.events import AuditAction
from app.models.community import (
    CommunityDiscussionSource,
    CommunityFetchStatus,
    CommunitySourceName,
)
from app.models.enums import ActorType, ImportItemStatus
from app.services.excel_parser import CANONICAL_FIELDS, auto_map
from app.services.import_community import (
    extract_community_payload,
    upsert_community_source,
)
from app.services.import_validator import validate_row

# ---------------------------------------------------------------------------
# excel_parser canonical surface
# ---------------------------------------------------------------------------


def test_excel_parser_canonical_fields_include_community() -> None:
    for f in (
        "discussion_url",
        "external_question_id",
        "discussion_count",
        "vote_a",
        "vote_b",
        "vote_c",
        "vote_d",
        "vote_e",
        "vote_f",
    ):
        assert f in CANONICAL_FIELDS


def test_excel_parser_auto_map_aliases_community_headers() -> None:
    headers = [
        "Discussion URL",
        "External Question ID",
        "Discussion Count",
        "Vote A",
        "Vote F",
        "Comments",
    ]
    m = auto_map(headers)
    assert m["Discussion URL"] == "discussion_url"
    assert m["External Question ID"] == "external_question_id"
    assert m["Discussion Count"] == "discussion_count"
    assert m["Vote A"] == "vote_a"
    assert m["Vote F"] == "vote_f"
    assert m["Comments"] == "discussion_count"


# ---------------------------------------------------------------------------
# Validator backwards-compat
# ---------------------------------------------------------------------------


def _good_row_no_community() -> dict[str, Any]:
    return {
        "question_text": "What does VPN stand for?",
        "option_a": "Virtual Private Network",
        "option_b": "Voice Packet Node",
        "correct_answer": "A",
    }


def test_existing_import_without_community_fields_still_works() -> None:
    """No community columns → no `canonical['community']` key, status `ok`."""
    r = validate_row(_good_row_no_community())
    assert r.status == ImportItemStatus.ok
    assert "community" not in r.canonical


# ---------------------------------------------------------------------------
# Validator with valid community signal
# ---------------------------------------------------------------------------


def test_import_row_with_discussion_url_creates_normalized_community() -> None:
    row = _good_row_no_community()
    row["discussion_url"] = "https://www.examtopics.com/discussions/fortinet/view/x"
    row["external_question_id"] = "EXT-001"
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    community = r.canonical["community"]
    assert community["discussion_url"] == row["discussion_url"]
    assert community["external_question_id"] == "EXT-001"
    assert community["vote_distribution"] is None
    assert community["discussion_count"] is None


def test_import_row_with_vote_distribution_creates_normalized_community() -> None:
    row = _good_row_no_community()
    row["external_question_id"] = "EXT-002"
    row["vote_a"] = 21
    row["vote_d"] = 6
    row["discussion_count"] = 12
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    community = r.canonical["community"]
    assert community["vote_distribution"] == {"A": 21, "D": 6}
    assert community["discussion_count"] == 12


def test_vote_distribution_accepts_six_options_dynamic_labels() -> None:
    """Red-team #10 — 6-option Cisco/Fortinet questions."""
    row = _good_row_no_community()
    row["external_question_id"] = "EXT-005"
    row["vote_a"] = 5
    row["vote_b"] = 3
    row["vote_f"] = 12
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    assert r.canonical["community"]["vote_distribution"] == {"A": 5, "B": 3, "F": 12}


# ---------------------------------------------------------------------------
# Validator: bad community data → warning, never error
# ---------------------------------------------------------------------------


def test_invalid_discussion_url_marks_row_warning_and_drops_url() -> None:
    row = _good_row_no_community()
    row["discussion_url"] = "https://127.0.0.1/internal"
    row["external_question_id"] = "EXT-001"
    r = validate_row(row)
    # Core question is fine — community data is optional; row is `warning`.
    assert r.status == ImportItemStatus.warning
    assert "discussion_url rejected" in (r.warning_message or "")
    # URL dropped from the canonical community payload.
    community = r.canonical["community"]
    assert community["discussion_url"] is None
    # External id still preserved so admins can debug upstream link.
    assert community["external_question_id"] == "EXT-001"


def test_url_with_non_https_scheme_warns_and_drops() -> None:
    row = _good_row_no_community()
    row["discussion_url"] = "http://www.examtopics.com/x"
    row["external_question_id"] = "EXT-X"
    r = validate_row(row)
    assert r.status == ImportItemStatus.warning
    assert r.canonical["community"]["discussion_url"] is None


def test_invalid_external_question_id_warns_and_drops_payload() -> None:
    """Pydantic regex blocks `<script>` etc. → row keeps 'warning' status,
    community signal dropped entirely.
    """
    row = _good_row_no_community()
    row["external_question_id"] = "<script>"
    row["vote_a"] = 1
    r = validate_row(row)
    assert r.status == ImportItemStatus.warning
    # When the inner Pydantic validation fails, the whole community block
    # is dropped (returns None from extract_community_payload).
    assert "community" not in r.canonical
    assert "community_signal invalid" in (r.warning_message or "")


def test_negative_vote_count_silently_dropped_from_distribution() -> None:
    """A single bad vote cell drops just that label; row stays ok if the
    rest of the distribution survives.
    """
    row = _good_row_no_community()
    row["external_question_id"] = "EXT-NEG"
    row["vote_a"] = 5
    row["vote_b"] = -3  # dropped
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    assert r.canonical["community"]["vote_distribution"] == {"A": 5}


def test_bool_vote_count_rejected_via_isinstance_guard() -> None:
    """`bool` is a subclass of `int`; the helper rejects it explicitly so
    `True` doesn't sneak into a vote distribution as `1`.
    """
    row = _good_row_no_community()
    row["external_question_id"] = "EXT-BOOL"
    row["vote_a"] = True
    row["vote_b"] = 4
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    # vote_a is dropped (bool); vote_b survives.
    assert r.canonical["community"]["vote_distribution"] == {"B": 4}


def test_string_numeric_vote_count_coerced_safely() -> None:
    row = _good_row_no_community()
    row["external_question_id"] = "EXT-STR"
    row["vote_a"] = "5"  # admin XLSX cell that arrived as text
    r = validate_row(row)
    assert r.canonical["community"]["vote_distribution"] == {"A": 5}


# ---------------------------------------------------------------------------
# extract_community_payload purity
# ---------------------------------------------------------------------------


def test_extract_returns_none_when_no_signal_columns_set() -> None:
    warnings: list[str] = []
    out = extract_community_payload(_good_row_no_community(), warnings=warnings)
    assert out is None
    assert warnings == []


def test_extract_returns_payload_when_only_external_id_present() -> None:
    warnings: list[str] = []
    out = extract_community_payload({"external_question_id": "EXT-OK"}, warnings=warnings)
    assert out is not None
    assert out["external_question_id"] == "EXT-OK"
    assert warnings == []


# ---------------------------------------------------------------------------
# upsert_community_source orchestration via fake Session
# ---------------------------------------------------------------------------


class _FakeScalarsResult:
    """Mimics SA 2.0 `session.scalars(stmt)` first()/scalars iter."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    """Hermetic stand-in for `Session`. Captures `.add(...)` calls and
    routes `.scalars(...)` to a caller-controlled lookup queue.
    """

    def __init__(self, lookup_results: list[list[Any]] | None = None) -> None:
        self.added: list[Any] = []
        self._lookup_queue = lookup_results or []
        self._next_id = 1000

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        # Assign auto-ids to anything missing one (mimics the real flush).
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                try:
                    obj.id = self._next_id  # type: ignore[attr-defined]
                    self._next_id += 1
                except (AttributeError, TypeError):
                    pass

    def scalars(self, _stmt: Any) -> _FakeScalarsResult:
        if self._lookup_queue:
            return _FakeScalarsResult(self._lookup_queue.pop(0))
        return _FakeScalarsResult([])


def _audit_actions(session: _FakeSession) -> list[str]:
    return [getattr(o, "action", None) for o in session.added if o.__class__.__name__ == "AuditLog"]


def _cds_rows(session: _FakeSession) -> list[CommunityDiscussionSource]:
    return [o for o in session.added if isinstance(o, CommunityDiscussionSource)]


def test_upsert_skipped_when_payload_has_no_url() -> None:
    """Without source_url the CDS UNIQUE-key tuple cannot be built; skip."""
    s = _FakeSession()
    out = upsert_community_source(
        s,
        question_id=42,
        payload={
            "discussion_url": None,
            "external_question_id": "EXT-NO-URL",
            "discussion_count": 5,
            "vote_distribution": {"A": 1},
        },
        request_id="11111111-1111-1111-1111-111111111111",
    )
    assert out is None
    assert _cds_rows(s) == []
    assert _audit_actions(s) == []


def test_upsert_creates_new_cds_and_emits_candidate_created_audit() -> None:
    s = _FakeSession()  # no existing rows
    out = upsert_community_source(
        s,
        question_id=42,
        payload={
            "discussion_url": "https://www.examtopics.com/discussions/x",
            "external_question_id": "EXT-001",
            "discussion_count": 12,
            "vote_distribution": {"A": 21, "D": 6},
        },
        request_id="11111111-1111-1111-1111-111111111111",
    )
    rows = _cds_rows(s)
    assert len(rows) == 1
    cds = rows[0]
    assert cds.question_id == 42
    assert cds.source_name == CommunitySourceName.examtopics
    assert cds.source_url == "https://www.examtopics.com/discussions/x"
    assert cds.external_question_id == "EXT-001"
    assert cds.discussion_count == 12
    assert cds.vote_distribution == {"A": 21, "D": 6}
    assert cds.total_votes == 27
    assert cds.fetch_status == CommunityFetchStatus.pending
    assert out is cds
    assert AuditAction.COMMUNITY_SOURCE_CANDIDATE_CREATED.value in _audit_actions(s)


def test_upsert_audit_uses_system_actor_with_request_id() -> None:
    s = _FakeSession()
    upsert_community_source(
        s,
        question_id=1,
        payload={
            "discussion_url": "https://www.examtopics.com/discussions/y",
            "external_question_id": "EXT-002",
            "discussion_count": None,
            "vote_distribution": None,
        },
        request_id="22222222-2222-2222-2222-222222222222",
    )
    audits = [o for o in s.added if o.__class__.__name__ == "AuditLog"]
    assert len(audits) == 1
    a = audits[0]
    assert a.actor_type == ActorType.system
    assert a.actor_id is None
    # request_id was coerced to UUID by the audit writer.
    assert str(a.request_id) == "22222222-2222-2222-2222-222222222222"


def test_upsert_idempotent_when_existing_row_unchanged() -> None:
    """Second call with the same payload → no audit, no insert."""
    existing = CommunityDiscussionSource(
        question_id=42,
        source_name=CommunitySourceName.examtopics,
        source_url="https://www.examtopics.com/x",
        external_question_id="EXT-001",
        discussion_count=12,
        vote_distribution={"A": 21, "D": 6},
        total_votes=27,
        fetch_status=CommunityFetchStatus.pending,
        approved_for_student=False,
        row_version=0,
    )
    existing.id = 999
    s = _FakeSession(lookup_results=[[existing], []])  # 1st: external-id hit
    out = upsert_community_source(
        s,
        question_id=42,
        payload={
            "discussion_url": "https://www.examtopics.com/x",
            "external_question_id": "EXT-001",
            "discussion_count": 12,
            "vote_distribution": {"A": 21, "D": 6},
        },
        request_id="33333333-3333-3333-3333-333333333333",
    )
    assert out is existing
    # No NEW CDS row added; no audit emitted.
    assert _cds_rows(s) == []
    assert _audit_actions(s) == []


def test_upsert_text_changed_resets_approval_and_emits_audit() -> None:
    existing = CommunityDiscussionSource(
        question_id=42,
        source_name=CommunitySourceName.examtopics,
        source_url="https://www.examtopics.com/x",
        external_question_id="EXT-001",
        discussion_count=12,
        vote_distribution={"A": 21, "D": 6},
        total_votes=27,
        fetch_status=CommunityFetchStatus.pending,
        approved_for_student=True,  # was approved
        row_version=4,
    )
    existing.id = 999
    s = _FakeSession(lookup_results=[[existing]])
    upsert_community_source(
        s,
        question_id=42,
        payload={
            "discussion_url": "https://www.examtopics.com/x",
            "external_question_id": "EXT-001",
            "discussion_count": 30,  # changed
            "vote_distribution": {"A": 25, "D": 9},  # changed
        },
        request_id="44444444-4444-4444-4444-444444444444",
    )
    assert existing.discussion_count == 30
    assert existing.vote_distribution == {"A": 25, "D": 9}
    assert existing.total_votes == 34
    assert existing.approved_for_student is False  # reset
    assert existing.row_version == 5  # bumped
    assert AuditAction.COMMUNITY_SOURCE_RELINKED_TEXT_CHANGED.value in _audit_actions(s)


def test_upsert_relink_when_existing_row_belongs_to_different_question() -> None:
    """External id matches an existing CDS bound to a different question."""
    existing = CommunityDiscussionSource(
        question_id=10,  # different
        source_name=CommunitySourceName.examtopics,
        source_url="https://www.examtopics.com/x",
        external_question_id="EXT-001",
        discussion_count=12,
        vote_distribution={"A": 21},
        total_votes=21,
        fetch_status=CommunityFetchStatus.pending,
    )
    existing.id = 999
    s = _FakeSession(lookup_results=[[existing]])
    upsert_community_source(
        s,
        question_id=42,  # new question
        payload={
            "discussion_url": "https://www.examtopics.com/x",
            "external_question_id": "EXT-001",
            "discussion_count": 12,
            "vote_distribution": {"A": 21},
        },
        request_id="55555555-5555-5555-5555-555555555555",
    )
    assert existing.question_id == 42
    actions = _audit_actions(s)
    assert AuditAction.COMMUNITY_SOURCE_RELINKED.value in actions
    # Same content → no text_changed audit.
    assert AuditAction.COMMUNITY_SOURCE_RELINKED_TEXT_CHANGED.value not in actions


# ---------------------------------------------------------------------------
# Boundary checks
# ---------------------------------------------------------------------------


def test_no_internet_fetch_imports_in_import_service_or_community_helpers() -> None:
    """Phase 13 boundary: NO httpx / requests / urllib.request usage in
    the import_service / import_community modules.
    """
    import app.services.import_community as ic
    import app.services.import_service as svc

    forbidden = {"httpx", "requests"}
    for module in (svc, ic):
        for fn_or_attr in dir(module):
            obj = getattr(module, fn_or_attr)
            mod_name = getattr(obj, "__module__", "") or ""
            top = mod_name.split(".", 1)[0]
            assert top not in forbidden, (
                f"{module.__name__}.{fn_or_attr} pulls in {top!r} — Phase 13 must NOT fetch."
            )


def test_no_student_facing_routes_reference_community_model() -> None:
    """No STUDENT-facing route may reference CDS. Admin routes are allowed
    (Phase 16a admin community tab) — only `app/routers/public/` and
    sibling student modules are forbidden from touching the model.
    """
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    routers_dir = repo / "app" / "routers"
    if not routers_dir.exists():
        return  # nothing to check
    forbidden_dirs = ("public",)
    forbidden_modules = ("attempts.py", "practice.py", "reports.py")
    for f in routers_dir.rglob("*.py"):
        rel = f.relative_to(routers_dir)
        is_forbidden = any(part in forbidden_dirs for part in rel.parts) or rel.name in (
            forbidden_modules
        )
        if not is_forbidden:
            continue
        text = f.read_text(encoding="utf-8")
        assert "community_discussion_sources" not in text, (
            f"{f} references CDS table — student routes must NOT touch community signal."
        )
        assert "CommunityDiscussionSource" not in text, (
            f"{f} imports CDS model — student routes must NOT touch community signal."
        )
