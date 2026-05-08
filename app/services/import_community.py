"""Phase 13 — community-signal helpers for the import pipeline (CDEA Sprint-1).

Two responsibilities:
  1. **Pure** validation/extraction: turn a validator's `canonical` row into
     a JSONB-safe community payload (`extract_community_payload`) — no DB,
     no Session, easy to unit-test.
  2. **Session-aware** upsert: find-or-create the matching
     `community_discussion_sources` row and emit the right audit action
     in the SAME transaction as the question row (`upsert_community_source`).

Phase 13 only writes the `pending` candidate row. Phase 14 fetcher will
move it through the rest of the lifecycle.

NO Internet IO. NO AI. Pure parsing + DB write within an existing session.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.events import AuditAction
from app.audit.writer import write_audit_log
from app.models.community import (
    CommunityDiscussionSource,
    CommunityFetchStatus,
    CommunitySourceName,
)
from app.models.enums import ActorType
from app.schemas.community import ParsedCommunityRow
from app.security.url_validator import BlockedURLError, validate_url


def _coerce_int(value: Any) -> int | None:
    """Excel/JSON values arrive as int|str|float|None. Coerce safely; bool rejected."""
    if value is None:
        return None
    if isinstance(value, bool):  # bool is int subclass — block explicitly
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            return None
    return None


def _build_vote_distribution(normalized: dict[str, Any]) -> dict[str, int] | None:
    """Aggregate `vote_a..vote_f` columns into `{label: count}`.

    Skips missing / non-numeric / negative cells silently — the validator
    surfaces the row-level warning if needed. Returns None when nothing
    survives.
    """
    out: dict[str, int] = {}
    for letter in ("A", "B", "C", "D", "E", "F", "G", "H"):
        cell = normalized.get(f"vote_{letter.lower()}")
        n = _coerce_int(cell)
        if n is None or n < 0:
            continue
        out[letter] = n
    return out or None


def extract_community_payload(
    normalized: dict[str, Any],
    *,
    warnings: list[str],
) -> dict[str, Any] | None:
    """Pull Phase 13 community fields from a normalized row.

    Returns a JSONB-safe dict (the shape stored on `import_items.normalized_data
    ['community']` and consumed by `upsert_community_source`), or `None` when
    the row carries no community signal.

    Side-effect: appends human-readable strings to `warnings` for invalid URLs
    or vote distributions. The caller (validator) decides whether warnings
    cause a row-status downgrade.
    """
    discussion_url_raw = normalized.get("discussion_url")
    external_question_id_raw = normalized.get("external_question_id")
    discussion_count_raw = normalized.get("discussion_count")
    vote_dist = _build_vote_distribution(normalized)
    discussion_count = _coerce_int(discussion_count_raw)

    # Early exit when no community column at all is populated.
    if not (
        discussion_url_raw or external_question_id_raw or discussion_count is not None or vote_dist
    ):
        return None

    # Syntactic SSRF guard on URL — failure → drop URL + warn, keep other fields.
    validated_url: str | None = None
    if isinstance(discussion_url_raw, str) and discussion_url_raw.strip():
        try:
            v = validate_url(discussion_url_raw.strip())
            validated_url = v.raw
        except BlockedURLError as exc:
            warnings.append(f"discussion_url rejected: {exc.reason}")

    try:
        row = ParsedCommunityRow(
            external_question_id=(
                external_question_id_raw if isinstance(external_question_id_raw, str) else None
            ),
            discussion_url=validated_url,
            discussion_count=discussion_count,
            vote_distribution=vote_dist,
        )
    except ValidationError as exc:
        # Pydantic surfaces the first issue; keep the message short for UI.
        details = exc.errors()
        msg = details[0].get("msg", "validation_error") if details else "validation_error"
        warnings.append(f"community_signal invalid: {msg}")
        return None

    return row.to_jsonable()


def compare_community_state(
    existing: CommunityDiscussionSource,
    payload: dict[str, Any],
) -> tuple[bool, bool]:
    """Return `(relinked, text_changed)` flags for the upsert path.

    `relinked` = the row already exists for a different question id and we
    are about to move it.

    `text_changed` = vote_distribution or discussion_count differs from
    what was previously cached. Drives the approval-reset rule.
    """
    new_vote = payload.get("vote_distribution") or None
    new_count = payload.get("discussion_count")
    text_changed = existing.vote_distribution != new_vote or existing.discussion_count != new_count
    # Caller passes the new `question_id` separately — `relinked` is
    # computed there to avoid leaking ORM details into the comparator.
    return False, text_changed


def upsert_community_source(
    session: Session,
    *,
    question_id: int,
    payload: dict[str, Any],
    request_id: str | None,
) -> CommunityDiscussionSource | None:
    """Find-or-create the CDS row for `(question_id, examtopics, source_url)`.

    Behavior:
      * No `discussion_url` → cannot create (source_url NOT NULL); skip.
      * No existing row → INSERT, audit `community_source.candidate_created`.
      * Existing row, same question + url, content unchanged → no-op (idempotent).
      * Existing row, different question (matched via external_id+url) →
        relink, audit `community_source.relinked`.
      * Existing row, content (votes/count) changed → reset
        `approved_for_student=False`, bump `row_version`, audit
        `community_source.relinked_text_changed`.
    """
    discussion_url: str | None = payload.get("discussion_url")
    external_id: str | None = payload.get("external_question_id")
    if not discussion_url:
        # Phase 13 candidate rows must carry a fetchable URL. Without one,
        # there is nothing for Phase 14 to fetch and no UNIQUE-key tuple
        # we could safely build. Leave the question untouched.
        return None

    source_name = CommunitySourceName.examtopics
    new_vote: dict[str, Any] | None = payload.get("vote_distribution") or None
    new_total = sum(int(v) for v in new_vote.values()) if new_vote else None
    new_count = payload.get("discussion_count")

    existing = _select_existing_cds(
        session,
        question_id=question_id,
        external_id=external_id,
        source_url=discussion_url,
        source_name=source_name,
    )

    if existing is None:
        cds = CommunityDiscussionSource(
            question_id=question_id,
            source_name=source_name,
            source_url=discussion_url,
            external_question_id=external_id,
            discussion_count=new_count,
            vote_distribution=new_vote,
            total_votes=new_total,
            fetch_status=CommunityFetchStatus.pending,
        )
        session.add(cds)
        session.flush()
        write_audit_log(
            session,
            actor_type=ActorType.system,
            actor_id=None,
            action=AuditAction.COMMUNITY_SOURCE_CANDIDATE_CREATED,
            entity_type="community_source",
            entity_id=cds.id,
            new_value={
                "question_id": question_id,
                "source_name": source_name.value,
                "source_url": discussion_url,
                "external_question_id": external_id,
                "discussion_count": new_count,
                "total_votes": new_total,
            },
            request_id=request_id,
        )
        return cds

    # Existing row path.
    relinked = existing.question_id != question_id
    _, text_changed = compare_community_state(existing, payload)

    if relinked:
        old_qid = existing.question_id
        existing.question_id = question_id
        existing.external_question_id = external_id or existing.external_question_id
        write_audit_log(
            session,
            actor_type=ActorType.system,
            actor_id=None,
            action=AuditAction.COMMUNITY_SOURCE_RELINKED,
            entity_type="community_source",
            entity_id=existing.id,
            old_value={"question_id": old_qid},
            new_value={"question_id": question_id},
            request_id=request_id,
        )

    if text_changed:
        old_state = {
            "vote_distribution": existing.vote_distribution,
            "discussion_count": existing.discussion_count,
            "approved_for_student": existing.approved_for_student,
        }
        existing.vote_distribution = new_vote
        existing.discussion_count = new_count
        existing.total_votes = new_total
        existing.approved_for_student = False
        existing.row_version = (existing.row_version or 0) + 1
        write_audit_log(
            session,
            actor_type=ActorType.system,
            actor_id=None,
            action=AuditAction.COMMUNITY_SOURCE_RELINKED_TEXT_CHANGED,
            entity_type="community_source",
            entity_id=existing.id,
            old_value=old_state,
            new_value={
                "vote_distribution": new_vote,
                "discussion_count": new_count,
                "approved_for_student": False,
            },
            request_id=request_id,
        )
    return existing


def _select_existing_cds(
    session: Session,
    *,
    question_id: int,
    external_id: str | None,
    source_url: str,
    source_name: CommunitySourceName,
) -> CommunityDiscussionSource | None:
    """Look up an existing CDS row.

    Lookup precedence:
      1. `(external_question_id, source_name, source_url)` — finds rows
         already pinned to a stable upstream id, even when the question_id
         has changed (re-import of an edited question).
      2. `(question_id, source_name, source_url)` — pure question-scoped
         match (idempotent re-import of the same question).
    """
    if external_id:
        hit = session.scalars(
            select(CommunityDiscussionSource)
            .where(CommunityDiscussionSource.external_question_id == external_id)
            .where(CommunityDiscussionSource.source_name == source_name)
            .where(CommunityDiscussionSource.source_url == source_url)
            .limit(1)
        ).first()
        if hit is not None:
            return hit
    return session.scalars(
        select(CommunityDiscussionSource)
        .where(CommunityDiscussionSource.question_id == question_id)
        .where(CommunityDiscussionSource.source_name == source_name)
        .where(CommunityDiscussionSource.source_url == source_url)
        .limit(1)
    ).first()


__all__ = [
    "compare_community_state",
    "extract_community_payload",
    "upsert_community_source",
]
