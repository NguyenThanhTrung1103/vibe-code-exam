"""Public catalog routes (anonymous-friendly).

Public visibility rule:
  * Exam.publish_status == 'published'
  * Exam.deleted_at IS NULL
Filters applied explicitly in every public query — never hidden in events.
"""
