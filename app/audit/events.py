"""Typed catalog of audit actions. Extended by each subsequent phase.

Values are dot-namespaced strings — `"user.registered"`, `"exam.published"`,
etc. — so future log indexers / filters can prefix-match.
"""

from __future__ import annotations

import enum


class AuditAction(enum.StrEnum):
    # Identity / auth
    USER_REGISTERED = "user.registered"
    USER_ROLE_CHANGED = "user.role_changed"
    LOGIN_SUCCEEDED = "auth.login_succeeded"
    LOGIN_FAILED = "auth.login_failed"
    LOGOUT = "auth.logout"

    # Phase 04 — catalog
    PROVIDER_CREATED = "provider.created"
    PROVIDER_UPDATED = "provider.updated"
    PROVIDER_SOFT_DELETED = "provider.soft_deleted"
    PRODUCT_VERSION_CREATED = "product_version.created"
    PRODUCT_VERSION_UPDATED = "product_version.updated"
    PRODUCT_VERSION_SOFT_DELETED = "product_version.soft_deleted"
    COURSE_CREATED = "course.created"
    COURSE_UPDATED = "course.updated"
    COURSE_SOFT_DELETED = "course.soft_deleted"
    EXAM_CREATED = "exam.created"
    EXAM_UPDATED = "exam.updated"
    EXAM_PUBLISHED = "exam.published"
    EXAM_UNPUBLISHED = "exam.unpublished"
    EXAM_SOFT_DELETED = "exam.soft_deleted"
    TOPIC_CREATED = "topic.created"
    TOPIC_UPDATED = "topic.updated"
    TOPIC_SOFT_DELETED = "topic.soft_deleted"

    # Phase 05 — Excel import pipeline
    IMPORT_UPLOADED = "import.uploaded"
    IMPORT_MAPPING_SAVED = "import.mapping_saved"
    IMPORT_PARSED = "import.parsed"
    IMPORT_ROW_TOGGLED = "import.row_toggled"
    IMPORT_CONFIRMED = "import.confirmed"
    IMPORT_PARTIAL_FAILURE = "import.partial_failure"
    QUESTION_IMPORTED = "question.imported"

    # Phase 06 — question bank CRUD
    QUESTION_CREATED = "question.created"
    QUESTION_TEXT_EDITED = "question.text_edited"
    QUESTION_OPTION_EDITED = "question.option_edited"
    QUESTION_EXPLANATION_EDITED = "question.explanation_edited"
    QUESTION_RETIRED = "question.retired"
    QUESTION_RESTORED = "question.restored"
    QUESTION_TOPIC_ASSIGNED = "question.topic_assigned"

    # Phase 07 — practice / exam attempts
    ATTEMPT_STARTED = "attempt.started"
    ATTEMPT_RESUMED = "attempt.resumed"
    ATTEMPT_SUBMITTED = "attempt.submitted"
    ATTEMPT_EXPIRED = "attempt.expired"

    # Phase 08 — scoring + reports
    ATTEMPT_SCORED = "attempt.scored"
    QUESTION_REPORT_FILED = "question_report.filed"
    QUESTION_REPORT_RESOLVED = "question_report.resolved"
    QUESTION_REPORT_REJECTED = "question_report.rejected"

    # Phase 13 — community signal (CDEA Sprint-1)
    # System-actor events emitted by the import pipeline when a community
    # discussion source is staged from an admin dump. NO Internet fetch
    # happens here — that's Phase 14.
    COMMUNITY_SOURCE_CANDIDATE_CREATED = "community_source.candidate_created"
    COMMUNITY_SOURCE_RELINKED = "community_source.relinked"
    COMMUNITY_SOURCE_RELINKED_TEXT_CHANGED = "community_source.relinked_text_changed"
